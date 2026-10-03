"""Observe and record C-compatibility probe outcomes through both compilers.

``test_c_compatibility_inventory.py`` checks every manifest entry under
``fixtures/c_compat_probe`` against what both compilers do now; its docstring
gives the schema. This module owns the observation that test asserts, and the
one sanctioned way to refresh an entry's recorded outcome:

    python3 -m src.tests.btrc.c_compat_inventory record --btrcc PATH \\
        --rows 1-7,19 [--revision SHA]

``record`` observes each selected entry through both compilers exactly as the
test does, rewrites only that entry's ``revision``, ``python`` and ``btrcc``
lines in place (comments, order and every other line are kept), and refuses
to record an outcome the entry's ``status`` does not allow, so a regression
can never be recorded as the new truth. ``--revision`` defaults to ``HEAD``'s
short commit, the tree the outcome was observed on.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from src.tests.btrc.allocation_tracking_harness import compiler_environment
from src.tests.btrc.selfhost_snippet_harness import compile_reference_source, compile_source
from src.tests.c_toolchains import HOST_C_COMPILERS as COMPILERS

REPO = Path(__file__).resolve().parents[3]
TESTS = REPO / "src/tests"
PROBES = Path(__file__).with_name("fixtures") / "c_compat_probe"
MANIFESTS = ("c1", "c2", "c3_c4", "c5")

_SELFHOST_DIAGNOSTIC = re.compile(r"error: (?P<message>.*) at (?P<line>\d+):(?P<col>\d+)\n?")
_REFERENCE_DIAGNOSTIC = re.compile(r"(?i)error: (?P<message>[^\n]+)\n\s*--> .*:(?P<line>\d+):(?P<col>\d+)\n")
_UNPOSITIONED_DIAGNOSTIC = re.compile(r"(?i)error: (?P<message>[^\n]+)\n?")


def load_probes() -> list[dict]:
    probes = []
    for name in MANIFESTS:
        for probe in tomllib.loads((PROBES / f"{name}.toml").read_text())["probe"]:
            probes.append({**probe, "manifest": name})
    return probes


def probe_source(probe: dict) -> str:
    if "corpus" in probe:
        return (TESTS / probe["corpus"]).read_text()
    return probe["source"]


def diagnostic(stderr: str) -> str:
    for pattern in (_SELFHOST_DIAGNOSTIC, _REFERENCE_DIAGNOSTIC):
        match = pattern.fullmatch(stderr) if pattern is _SELFHOST_DIAGNOSTIC else pattern.match(stderr)
        if match is not None:
            return f"{match.group('message')} at {match.group('line')}:{match.group('col')}"
    # A front-end refusal raised before any token has a position.
    unpositioned = _UNPOSITIONED_DIAGNOSTIC.fullmatch(stderr)
    assert unpositioned is not None, f"unrecognized diagnostic:\n{stderr}"
    return unpositioned.group("message")


def strict_outcome(generated: Path, tmp_path: Path, frontend: str) -> dict:
    """Build with every strict C11 compiler and require one agreed outcome."""
    outcomes = {}
    for compiler in COMPILERS:
        name = Path(compiler).name
        executable = tmp_path / f"{frontend}-{name}"
        environment = compiler_environment(compiler)
        build = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O2",
                str(generated),
                "-pthread",
                "-lm",
                "-o",
                str(executable),
            ],
            cwd=REPO,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if build.returncode != 0:
            outcomes[name] = {"c": "rejected"}
            continue
        run = subprocess.run(
            [str(executable)],
            cwd=REPO,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        outcomes[name] = {"exit": run.returncode, "stdout": run.stdout}
    distinct = {repr(sorted(outcome.items())) for outcome in outcomes.values()}
    assert len(distinct) == 1, f"{frontend}: strict C compilers disagree: {outcomes}"
    return next(iter(outcomes.values()))


def outcome(result: subprocess.CompletedProcess[str], generated: Path, tmp_path: Path, frontend: str) -> dict:
    if result.returncode != 0:
        return {"diagnostic": diagnostic(result.stderr)}
    return strict_outcome(generated, tmp_path, frontend)


def observe(btrcc: Path, tmp_path: Path, probe: dict) -> dict:
    """Both compilers' outcomes for *probe*, as the manifest records them."""
    source = probe_source(probe)
    selfhost, selfhost_c = compile_source(btrcc, tmp_path, source)
    reference, reference_c = compile_reference_source(tmp_path, source)
    return {
        "python": outcome(reference, reference_c, tmp_path, "python"),
        "btrcc": outcome(selfhost, selfhost_c, tmp_path, "btrcc"),
    }


_TOML_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t"}


def _toml_string(value: str) -> str:
    """A TOML basic string: every control character a basic string forbids is escaped."""
    escaped = "".join(
        _TOML_ESCAPES.get(character)
        or (f"\\u{ord(character):04X}" if ord(character) < 0x20 or ord(character) == 0x7F else character)
        for character in value
    )
    return f'"{escaped}"'


def toml_outcome(value: dict) -> str:
    """One recorded outcome as the manifests spell it, keys in their order."""
    order = ("diagnostic", "c", "exit", "stdout")
    assert set(value) <= set(order), value
    fields = [
        f"{key} = {value[key]}" if isinstance(value[key], int) else f"{key} = {_toml_string(value[key])}"
        for key in order
        if key in value
    ]
    return "{ " + ", ".join(fields) + " }"


def _permitted(probe: dict, observed: dict) -> str | None:
    """Why *observed* cannot be recorded for *probe*, or None."""
    status = probe["status"]
    if status == "accepted" and any(observed[frontend].get("exit") != 0 for frontend in ("python", "btrcc")):
        return "an accepted entry must build and exit 0 in both compilers"
    if status in {"rejected", "refused-on-purpose"} and any(
        "diagnostic" not in observed[frontend] for frontend in ("python", "btrcc")
    ):
        return "a rejected entry must be refused by both compilers"
    if (observed["python"] != observed["btrcc"]) != ("divergence" in probe):
        return "the compilers' agreement no longer matches the entry's divergence field"
    if "corpus" in probe:
        corpus = Path(probe["corpus"])
        golden = TESTS / corpus.parent / "expected" / f"{corpus.stem}.stdout"
        if observed["python"].get("stdout") != golden.read_text():
            return f"stdout differs from {golden.relative_to(REPO)}"
    return None


def rewrite_entry(text: str, probe_id: str, revision: str, observed: dict) -> str:
    """Replace one entry's revision and outcome lines, leaving the rest intact."""
    blocks = re.split(r"(?m)^(?=\[\[probe\]\]$)", text)
    matches = [index for index, block in enumerate(blocks) if re.search(rf'(?m)^id = "{re.escape(probe_id)}"$', block)]
    assert len(matches) == 1, probe_id
    block = blocks[matches[0]]
    replacements = {
        "revision": _toml_string(revision),
        "python": toml_outcome(observed["python"]),
        "btrcc": toml_outcome(observed["btrcc"]),
    }
    for key, value in replacements.items():
        line = f"{key} = {value}"
        block, count = re.subn(rf"(?m)^{key} = .*$", lambda _, line=line: line, block)
        assert count == 1, (probe_id, key)
    blocks[matches[0]] = block
    return "".join(blocks)


def _rows(spec: str) -> set[str]:
    rows: set[str] = set()
    for part in spec.split(","):
        if "-" in part and not part.startswith("x-"):
            first, last = part.split("-")
            rows.update(str(row) for row in range(int(first), int(last) + 1))
        else:
            rows.add(part)
    return rows


def record(btrcc: Path, rows: set[str], revision: str) -> int:
    failures = []
    for manifest in MANIFESTS:
        path = PROBES / f"{manifest}.toml"
        text = path.read_text()
        probes = [probe for probe in tomllib.loads(text)["probe"] if probe["row"] in rows]
        for probe in probes:
            with tempfile.TemporaryDirectory(prefix="c-compat-record-") as scratch:
                observed = observe(btrcc, Path(scratch), probe)
            refusal = _permitted(probe, observed)
            if refusal is not None:
                failures.append(f"{probe['id']}: {refusal}: {observed}")
                continue
            text = rewrite_entry(text, probe["id"], revision, observed)
            print(f"recorded {manifest}/{probe['id']}")
        tomllib.loads(text)
        path.write_text(text)
    for failure in failures:
        print(f"not recorded: {failure}", file=sys.stderr)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    recorder = commands.add_parser("record", help="re-observe entries and rewrite their recorded outcomes")
    recorder.add_argument("--btrcc", type=Path, required=True, help="the self-hosted compiler to observe")
    recorder.add_argument("--rows", required=True, help="table rows, e.g. 1-7,19 or x-hex-float")
    recorder.add_argument("--revision", help="the commit observed (default: HEAD's short commit)")
    arguments = parser.parse_args(argv)
    if not COMPILERS:
        parser.error("requires a strict C11 compiler")
    revision = (
        arguments.revision
        or subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()
    )
    return record(arguments.btrcc.resolve(), _rows(arguments.rows), revision)


if __name__ == "__main__":
    raise SystemExit(main())
