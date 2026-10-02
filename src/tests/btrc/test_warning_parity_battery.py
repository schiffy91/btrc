"""Both compilers report the same analyzer warnings, rendered the same way.

Each probe is compiled by the Python reference compiler's CLI and by the
self-hosted ``btrcc``. Both must succeed (a warning never changes the exit
status) and print the same warnings: the same message, file, line and column,
the same source line and caret. The pinned positions below hold the nullable
flow itself -- guards, non-returning calls, loops, branches, lambdas and
imported modules -- so a rule changed in one compiler alone fails here. The
corpus runner holds every corpus program's warnings to a golden in both
compilers (``expected/<Stem>.warnings``).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
WARNING = re.compile(r"^warning: (.*)\n\s*--> (.*?):(\d+):(\d+)$", re.MULTILINE)
ACCESS = re.compile(r"^Non-optional access '\.(\w+)' on nullable type '(\w+)\?' — use '\?\.\1' or check for null$")

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires the POSIX self-host driver")

PRELUDE = """class Box {
    public int value;
    public Box? next;
    public Box(int value) { self.value = value; self.next = null; }
}
Box? maybeBox(int value) {
    if (value > 0) { return Box(value); }
    return null;
}
"""
PRELUDE_LINES = PRELUDE.count("\n")


@dataclass(frozen=True)
class WarningProbe:
    """A program after the Box prelude, and the (line, column, field) of every access it warns on."""

    name: str
    body: str
    warnings: tuple[tuple[int, int, str], ...] = ()

    @property
    def source(self) -> str:
        return PRELUDE + self.body + "int main() { return 0; }\n"


def _at(line: int, col: int, field: str = "value") -> tuple[int, int, str]:
    """A position in the probe body, counted from the body's first line."""
    return (PRELUDE_LINES + line, col, field)


PROBES = (
    WarningProbe("unguarded-parameter", "int read(Box? box) {\n    return box.value;\n}\n", (_at(2, 12),)),
    WarningProbe(
        "guards-refine",
        "int read(Box? box) {\n"
        "    if (box == null) { return 0; }\n"
        "    int a = box.value;\n"
        "    int b = box != null && box.value > 0 ? 1 : 0;\n"
        "    return box == null ? a + b : box.value;\n"
        "}\n",
    ),
    WarningProbe(
        "hosted-noreturn-guards",
        "int read(Box? box, Box? other) {\n"
        "    if (box == null) { exit(1); }\n"
        '    if (other == null) { fprintf(stderr, "none\\n"); abort(); }\n'
        "    return box.value + other.value;\n"
        "}\n",
    ),
    WarningProbe(
        "diverging-callables",
        'void die(string message) { fprintf(stderr, "%s\\n", message); exit(1); }\n'
        "void dieTwice(string message) { die(message); }\n"
        "void raise(string message) { throw message; }\n"
        "void maybe(bool stop) { if (stop) { return; } exit(1); }\n"
        "void ping(int depth) { pong(depth); }\n"
        "void pong(int depth) { ping(depth); }\n"
        "int read(Box? a, Box? b, Box? c, Box? d) {\n"
        '    if (a == null) { dieTwice("a"); }\n'
        '    if (b == null) { raise("b"); }\n'
        "    if (c == null) { maybe(true); }\n"
        "    if (d == null) { ping(0); }\n"
        "    return a.value + b.value + c.value + d.value;\n"
        "}\n",
        (_at(12, 32), _at(12, 42)),
    ),
    WarningProbe(
        "diverging-methods",
        "class Checks {\n"
        '    class void fail(string message) { fprintf(stderr, "%s\\n", message); exit(1); }\n'
        "    public void stop(string message) { throw message; }\n"
        "    public int viaSelf(Box? box) {\n"
        '        if (box == null) { self.stop("missing"); }\n'
        "        return box.value;\n"
        "    }\n"
        "}\n"
        "class Lenient extends Checks {\n"
        "    public void stop(string message) { }\n"
        "}\n"
        "int viaStatic(Box? box) {\n"
        '    if (box == null) { Checks.fail("missing"); }\n'
        "    return box.value;\n"
        "}\n",
        (_at(6, 16),),
    ),
    WarningProbe(
        "unreachable-after-divergence",
        "int afterExit(Box? box) {\n"
        "    exit(1);\n"
        "    return box.value;\n"
        "}\n"
        "int afterBranches(Box? box, bool flag) {\n"
        '    if (flag) { exit(1); } else { throw "no"; }\n'
        "    return box.value;\n"
        "}\n"
        "int afterTry(Box? box) {\n"
        '    try { throw "no"; } catch (string error) { abort(); }\n'
        "    return box.value;\n"
        "}\n"
        "int switched(Box? box, int kind) {\n"
        "    switch (kind) {\n"
        "        case 0: exit(1);\n"
        "        default: if (box == null) { return 0; }\n"
        "    }\n"
        "    return box.value;\n"
        "}\n",
        (_at(18, 12),),
    ),
    WarningProbe(
        "loops",
        "int walk(Box? head) {\n"
        "    int total = 0;\n"
        "    Box? node = head;\n"
        "    while (node != null) { total += node.value; node = node.next; }\n"
        "    for (Box? cursor = head; cursor != null; cursor = cursor.next) { total += cursor.value; }\n"
        "    return total;\n"
        "}\n"
        "int unguardedWalk(Box head) {\n"
        "    int total = 0;\n"
        "    Box? node = head;\n"
        "    for (int index = 0; index < 3; index++) { total += node.value; node = node.next; }\n"
        "    return total;\n"
        "}\n",
        (_at(11, 56), _at(11, 75, "next")),
    ),
    WarningProbe(
        "calls-stores-and-escapes",
        "class Holder {\n"
        "    public Box? item;\n"
        "    public Holder() { self.item = null; }\n"
        "}\n"
        "void clear(Holder holder) { holder.item = null; }\n"
        "void touch(void* slot) { }\n"
        "int read(Holder holder) {\n"
        "    holder.item = Box(1);\n"
        "    int first = holder.item.value;\n"
        "    clear(holder);\n"
        "    Box? local = Box(2);\n"
        "    touch(&local);\n"
        "    return first + holder.item.value + local.value;\n"
        "}\n",
        (_at(13, 20, "value"), _at(13, 40)),
    ),
    WarningProbe(
        "lambda-body",
        "int read(Box? box) {\n"
        "    var get = (Box? item) => { return item.value; };\n"
        "    if (box == null) { return 0; }\n"
        "    return get(box);\n"
        "}\n",
        (_at(2, 39),),
    ),
)


@dataclass(frozen=True)
class WarningOutcome:
    """What one compiler printed for one program."""

    returncode: int
    blocks: tuple[str, ...]
    stderr: str


class WarningHarness:
    """Compile one program through both compilers and keep their warning output."""

    def __init__(self, btrcc: Path, workspace: Path) -> None:
        self._btrcc = btrcc
        self._workspace = workspace

    def compile(self, source: Path) -> tuple[WarningOutcome, WarningOutcome]:
        return self._reference(source), self._selfhost(source)

    def _reference(self, source: Path) -> WarningOutcome:
        result = subprocess.run(
            [sys.executable, "-m", "src.compiler.python.main", str(source), "--no-cache"]
            + ["-o", str(self._workspace / "reference.c")],
            cwd=REPO,
            capture_output=True,
            text=True,
            env={**os.environ, "BTRC_CACHE_DIR": str(self._workspace / "reference-cache")},
            timeout=300,
        )
        return WarningOutcome(result.returncode, self._blocks(result.stderr), result.stderr)

    def _selfhost(self, source: Path) -> WarningOutcome:
        result = subprocess.run([str(self._btrcc), str(source)], cwd=REPO, capture_output=True, text=True, timeout=300)
        return WarningOutcome(result.returncode, self._blocks(result.stderr), result.stderr)

    @staticmethod
    def _blocks(stderr: str) -> tuple[str, ...]:
        """Each rendered warning: its message line, location and source excerpt."""
        starts = [match.start() for match in re.finditer(r"^warning: ", stderr, re.MULTILINE)]
        ends = [*starts[1:], len(stderr)] if starts else []
        return tuple(sorted(stderr[start:end].rstrip("\n") for start, end in zip(starts, ends, strict=True)))


@pytest.fixture
def harness(immutable_btrcc: Path, tmp_path: Path) -> WarningHarness:
    return WarningHarness(immutable_btrcc, tmp_path)


@pytest.mark.parametrize("probe", PROBES, ids=lambda probe: probe.name)
def test_both_compilers_report_the_same_nullable_warnings(
    harness: WarningHarness, tmp_path: Path, probe: WarningProbe
) -> None:
    source = tmp_path / "Probe.btrc"
    source.write_text(probe.source)

    reference, selfhost = harness.compile(source)

    assert (reference.returncode, selfhost.returncode) == (0, 0), reference.stderr + selfhost.stderr
    assert selfhost.blocks == reference.blocks
    reported = []
    for match in WARNING.finditer(reference.stderr):
        access = ACCESS.match(match.group(1))
        assert access is not None and access.group(2) == "Box", match.group(1)
        assert match.group(2) == str(source)
        reported.append((int(match.group(3)), int(match.group(4)), access.group(1)))
    assert sorted(reported) == sorted(probe.warnings)


def test_warnings_in_an_imported_module_name_its_file(harness: WarningHarness, tmp_path: Path) -> None:
    library = tmp_path / "Lib.btrc"
    library.write_text(PRELUDE + "int useBox() {\n    Box? box = maybeBox(1);\n    return box.value;\n}\n")
    main = tmp_path / "Main.btrc"
    main.write_text(
        "import ./Lib.btrc;\n\nint main() {\n    Box? other = maybeBox(2);\n    return other.value + useBox();\n}\n"
    )

    reference, selfhost = harness.compile(main)

    assert (reference.returncode, selfhost.returncode) == (0, 0), reference.stderr + selfhost.stderr
    assert selfhost.blocks == reference.blocks
    locations = sorted((match.group(2), match.group(3), match.group(4)) for match in WARNING.finditer(reference.stderr))
    assert locations == [
        (str(library), str(PRELUDE_LINES + 3), "12"),
        (str(main), "5", "12"),
    ]
    assert " 5 |     return other.value + useBox();\n   |            ^" in reference.stderr


def test_a_warning_free_program_prints_nothing_in_either_compiler(harness: WarningHarness, tmp_path: Path) -> None:
    source = tmp_path / "Clean.btrc"
    source.write_text(PRELUDE + "int main() {\n    Box? box = maybeBox(1);\n    return box?.value ?? 0;\n}\n")

    reference, selfhost = harness.compile(source)

    assert (reference.returncode, selfhost.returncode) == (0, 0)
    assert reference.blocks == selfhost.blocks == ()
    assert selfhost.stderr == ""


def test_probe_names_are_unique() -> None:
    names = [probe.name for probe in PROBES]
    assert len(names) == len(set(names))


def test_a_replayed_validation_record_reports_the_same_warnings(immutable_btrcc: Path, tmp_path: Path) -> None:
    """Module units replay unchanged groups' validation records instead of validating; warnings ride the record."""
    source = tmp_path / "Recorded.btrc"
    source.write_text(PROBES[0].source)
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache"), "BTRC_TIMING": "1"}

    def build(name: str) -> subprocess.CompletedProcess[str]:
        output = tmp_path / name
        output.mkdir()
        return subprocess.run(
            [str(immutable_btrcc), str(source), "-o", str(output / "program.c")]
            + ["--emit-units", str(output / "program"), "--module-units", "--jobs", "1"],
            cwd=REPO,
            capture_output=True,
            text=True,
            env=environment,
            timeout=300,
        )

    first, second = build("first"), build("second")

    assert (first.returncode, second.returncode) == (0, 0), first.stderr + second.stderr
    replayed = re.search(r"a-records-stored\(replayed=(\d+),journaled=\d+\)", second.stderr)
    assert replayed is not None and int(replayed.group(1)) > 0, second.stderr

    def blocks(stderr: str) -> tuple[str, ...]:
        timing = re.compile(r"^btrcc (worker )?timing:.*\n?", re.MULTILINE)
        return WarningHarness._blocks(timing.sub("", stderr))

    assert blocks(second.stderr) == blocks(first.stderr) != ()
    assert [match.group(3, 4) for match in WARNING.finditer(first.stderr)] == [(str(PRELUDE_LINES + 2), "12")]
