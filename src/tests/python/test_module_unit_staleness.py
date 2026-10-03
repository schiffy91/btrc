"""Module-unit reuse stays exact when a dependency's body or a non-interface fact changes.

Each case builds a small program as module units, edits it once, and builds it
again with the same cache and output directory. The incremental build must
equal a clean build of the edited program in a fresh cache, unit for unit and
diagnostic for diagnostic (docs/design/stage-b-reuse-keys.md, defects SB-D1
to SB-D8). The output directory is the same in every build, because debug
builds name it in their `#line` directives and their keys.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.tests.process_limits import TOOL_TIMEOUT

ROOT = Path(__file__).resolve().parents[3]
# A module-unit build of a small program, through either compiler's CLI.
_BUILD_TIMEOUT = max(TOOL_TIMEOUT, 300.0)


@dataclass(frozen=True)
class _Build:
    """One build's emitted C files, its diagnostics and how many groups it lowered."""

    units: dict[str, str]
    diagnostics: list[str]
    lowered: int


def _command(compiler: str, request) -> list[str]:
    if compiler == "python":
        return [sys.executable, "-m", "src.compiler.python.main"]
    return [str(request.getfixturevalue("immutable_btrcc"))]


def _records(cache: Path) -> dict[Path, int]:
    """The reference compiler's stored unit records and when each was written."""
    return {path: path.stat().st_mtime_ns for path in cache.rglob("*.module.json")} if cache.exists() else {}


def _build(command: list[str], source: Path, output: Path, cache: Path, *extra: str) -> _Build:
    output.mkdir(parents=True, exist_ok=True)
    for stale in output.glob("p*.c"):
        stale.unlink()
    before = _records(cache)
    completed = subprocess.run(
        [
            *command,
            "Main.btrc",
            "-o",
            str(output / "p.c"),
            "--emit-units",
            str(output / "p"),
            "--module-units",
            "--jobs",
            "1",
            *extra,
        ],
        cwd=source,
        env={
            **os.environ,
            "BTRC_HOME": str(ROOT / "src"),
            "PYTHONPATH": str(ROOT),
            "BTRC_CACHE_DIR": str(cache),
            # btrcc reports its module-unit counters in its timing lines.
            **({} if command[0] == sys.executable else {"BTRC_TIMING": "1"}),
        },
        capture_output=True,
        text=True,
        timeout=_BUILD_TIMEOUT,
    )
    assert completed.returncode == 0, completed.stderr
    diagnostics = [line for line in completed.stderr.splitlines() if not line.startswith("btrcc ")]
    if "module-units=lowered:" in completed.stderr:
        lowered = int(completed.stderr.split("module-units=lowered:", 1)[1].split(",", 1)[0])
    else:
        # btrcpy stores a record for each group it lowers.
        lowered = sum(1 for path, written in _records(cache).items() if before.get(path) != written)
    units = {path.name: path.read_text() for path in sorted(output.glob("p*.c"))}
    return _Build(units, diagnostics, lowered)


def _incremental_matches_clean(
    compiler: str,
    request,
    tmp_path: Path,
    files: dict[str, str],
    edits: dict[str, tuple[str, str]],
    *extra: str,
) -> tuple[_Build, _Build, _Build]:
    """Cold build, edit, incremental build; then a clean build of the edited
    program in a fresh cache, into the same output directory. Returns the
    cold, incremental and clean builds after asserting the last two equal."""
    root = tmp_path.resolve()
    source = root / "program"
    source.mkdir()
    for name, text in files.items():
        (source / name).write_text(text)
    command = _command(compiler, request)
    output = root / "out"
    cold = _build(command, source, output, root / "cache", *extra)
    for name, (old, new) in edits.items():
        path = source / name
        text = path.read_text()
        assert old in text, (name, old)
        path.write_text(text.replace(old, new, 1))
    incremental = _build(command, source, output, root / "cache", *extra)
    clean = _build(command, source, output, root / "fresh-cache", *extra)
    assert incremental.diagnostics == clean.diagnostics
    assert incremental.units.keys() == clean.units.keys()
    for name in clean.units:
        assert incremental.units[name] == clean.units[name], name
    return cold, incremental, clean


def _lowered(build: _Build, groups: int) -> None:
    """The edit relowers exactly `groups` groups: the stale ones, and no more."""
    assert build.lowered == groups, build.lowered


_GPU_PROGRAM = {
    "Kernel.btrc": """@gpu float[] twice(float[] a) {
	int i = gpu_id();
	return a[i] * 2.0;
}
""",
    "Use.btrc": """import ./Kernel.btrc;

float scaled(float value) {
	float[] values = [value, value];
	values = twice(values);
	return values[0];
}
""",
    "Main.btrc": """import ./Use.btrc;

int main() {
	print(f"{scaled(1.0)}");
	return 0;
}
""",
}


def test_gpu_kernel_body_edit_relowers_its_dispatcher(compiler: str, tmp_path, request):
    """SB-D1: the dispatcher in `Use` embeds the kernel's WGSL, built from its body."""
    _, incremental, _ = _incremental_matches_clean(
        compiler, request, tmp_path, _GPU_PROGRAM, {"Kernel.btrc": ("a[i] * 2.0", "a[i] * 3.0")}
    )
    _lowered(incremental, 2)


_DESTRUCTOR_PROGRAM = {
    "Base.btrc": """int freed = 0;

class Base {
	public int value = 1;

	public Base() {}

	public void __del__() {
		freed = freed + 1;
	}
}
""",
    "Derived.btrc": """import ./Base.btrc;

class Derived extends Base {
	public int extra = 2;

	public Derived() {}
}

int churn() {
	Derived item = Derived();
	return item.extra;
}
""",
    "Main.btrc": """import ./Base.btrc;
import ./Derived.btrc;

int main() {
	print(f"{churn()} {freed}");
	return 0;
}
""",
}


def test_inherited_destructor_body_edit_relowers_the_child(compiler: str, tmp_path, request):
    """SB-D2: `Derived_destroy` carries `Base.__del__`'s body, lowered in Derived's unit."""
    _, incremental, _ = _incremental_matches_clean(
        compiler, request, tmp_path, _DESTRUCTOR_PROGRAM, {"Base.btrc": ("freed + 1", "freed + 2")}
    )
    _lowered(incremental, 2)


def test_debug_lines_above_an_inherited_destructor_relower_the_child(compiler: str, tmp_path, request):
    """SB-D4: in a debug build, the inherited body carries Base's positions."""
    _, incremental, _ = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        _DESTRUCTOR_PROGRAM,
        {"Base.btrc": ("int freed = 0;\n", "int freed = 0;\n\n\n// moved\n")},
        "--debug",
    )
    _lowered(incremental, 2)


_DEFAULTS_PROGRAM = {
    "Lib.btrc": """int scale(int x, int factor = 3 + 4) {
	return x * factor;
}

class Meter {
	public int base = 1;

	public Meter() {}

	public int read(int offset = 2 * 5) {
		return self.base + offset;
	}
}
""",
    "Use.btrc": """import ./Lib.btrc;

int measure() {
	Meter meter = Meter();
	return scale(2) + meter.read();
}
""",
    "Main.btrc": """import ./Use.btrc;

int main() {
	print(f"{measure()}");
	return 0;
}
""",
}


def test_debug_lines_above_a_default_argument_relower_its_callers(compiler: str, tmp_path, request):
    """SB-D3: btrcc positions a caller's default helper at the callee's default;
    btrcpy's helper is at `<btrc-generated>`, so its callers do not move."""
    _, incremental, _ = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        _DEFAULTS_PROGRAM,
        {"Lib.btrc": ("int scale(", "// one\n// two\nint scale(")},
        "--debug",
    )
    _lowered(incremental, 1 if compiler == "python" else 2)


_PREDEFINED_DEFAULT_PROGRAM = {
    "Lib.btrc": """int where(int line = __LINE__) {
	return line;
}
""",
    "Use.btrc": """import ./Lib.btrc;

int at() {
	return where();
}
""",
    "Main.btrc": """import ./Use.btrc;

int main() {
	print(f"{at()}");
	return 0;
}
""",
}


def test_lines_above_a_line_default_relower_its_callers(compiler: str, tmp_path, request):
    """A `__LINE__` default is frozen at the callee's position, even in a release build."""
    cold, incremental, clean = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        _PREDEFINED_DEFAULT_PROGRAM,
        {"Lib.btrc": ("int where(", "// one\n// two\nint where(")},
    )
    assert cold.units != clean.units
    _lowered(incremental, 2)


_DIVERGENCE_PROGRAM = {
    "Lib.btrc": """void fail() {
	exit(1);
}
""",
    "Use.btrc": """import ./Lib.btrc;

string? lookup(int key) {
	if (key > 0) { return "found"; }
	return null;
}

int use(int key) {
	string? found = lookup(key);
	if (found == null) {
		fail();
	}
	string value = found;
	return value.length();
}
""",
    "Main.btrc": """import ./Use.btrc;

int main() {
	print(f"{use(1)}");
	return 0;
}
""",
}


def test_a_callee_that_starts_returning_replays_no_stale_warning(compiler: str, tmp_path, request):
    """SB-D5: "never returns" is a body fact; the caller's warnings depend on it."""
    cold, _, clean = _incremental_matches_clean(
        compiler, request, tmp_path, _DIVERGENCE_PROGRAM, {"Lib.btrc": ("exit(1);", "return;")}
    )
    assert not cold.diagnostics
    assert any("Possibly-null value stored" in line for line in clean.diagnostics), clean.diagnostics


@pytest.mark.parametrize("debug", [False, True], ids=["release", "debug"])
def test_an_unrelated_line_shift_reuses_every_other_unit(compiler: str, debug: bool, tmp_path, request):
    """The fixes stay narrow: lines added above a plain function relower only its group."""
    files = dict(_DEFAULTS_PROGRAM)
    files["Other.btrc"] = "int other() { return 3; }\n"
    files["Main.btrc"] = files["Main.btrc"].replace("import ./Use.btrc;", "import ./Use.btrc;\nimport ./Other.btrc;")
    _, incremental, _ = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        files,
        {"Other.btrc": ("int other()", "// moved\nint other()")},
        *(["--debug"] if debug else []),
    )
    _lowered(incremental, 1)
