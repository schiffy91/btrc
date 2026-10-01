"""Table-driven C-compatibility inventory through both compilers (PLAN.md Stage 14).

The reference plan's 24-row C-compatibility table (ref:3082-3280) was a
hypothesis from an uncommitted probe. This battery replaces it with recorded,
re-checked outcomes. Each manifest under ``fixtures/c_compat_probe`` owns one
track (``c1``, ``c2``, ``c3_c4``, ``c5``); every ``[[probe]]`` entry holds:

``id``, ``row``, ``construct``
    A unique name, the table row (``"1"``-``"24"``, ``"0"`` for the reported
    successes, ``"x-*"`` for the extra gaps) and the C construct exercised.
``intent``
    ``positive`` for valid C11, ``negative`` for a program C11 itself rejects.
``status``
    ``accepted`` -- both compilers build it and it runs strictly as C11.
    ``rejected`` -- refused today; a positive row is a later stage's target.
    ``known-divergence`` -- compiled, or refused, wrongly; see
    ``KNOWN_DIVERGENCES``.
    ``refused-on-purpose`` -- a documented btrc refusal (rows 19-24,
    docs/known-language-gaps.md).
``revision``
    The commit the outcome was recorded against. An entry whose outcome a
    commit changes names that commit's parent, the tree it was changed on.
``python``, ``btrcc``
    The outcome per compiler: ``diagnostic`` (message and ``line:col``), or
    for generated C, ``c = "rejected"`` when every strict C11 compiler refuses
    it, else its ``exit`` code and ``stdout`` under gcc and clang.
``divergence``
    Present exactly when the two compilers' outcomes differ, naming how.
``source`` or ``corpus``
    The program inline, or a runnable corpus file whose golden it must match.

Probe programs are kept inline rather than as ``.btrc`` files because most of
them fail to lex or parse, and the strict-import audit and the lexer-parity
check read every ``.btrc`` file under ``src/tests``. A stage that implements a
row moves its positive program into ``src/tests/c_compat`` and turns the
entry into a ``corpus`` reference in the same commit.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import _compiler_environment
from src.tests.btrc.test_mutex_value_contract import COMPILERS
from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPO = Path(__file__).resolve().parents[3]
TESTS = REPO / "src/tests"
PROBES = Path(__file__).with_name("fixtures") / "c_compat_probe"
MANIFESTS = ("c1", "c2", "c3_c4", "c5")
STATUSES = frozenset({"accepted", "rejected", "known-divergence", "refused-on-purpose"})
ROWS = frozenset(str(row) for row in range(1, 25))
EXTRA_GAPS = frozenset(
    {
        "x-typedef-enum",
        "x-typedef-union",
        "x-enum-tag",
        "x-sizeof-expression",
        "x-hex-float",
        "x-utf8-string",
        "x-pointer-to-array",
        "x-braceless-do",
        "x-const-pointer",
        "x-alignof",
        "x-pointer-compound-assignment",
    }
)
REFUSAL_ROWS = frozenset({"19", "20", "21", "22", "23", "24"})

# Programs that a compiler accepts and miscompiles, or accepts and leaves for
# the C compiler to reject, or rejects for the wrong reason. Each is fixed by
# the named stage, which flips the entry in the same commit.
KNOWN_DIVERGENCES = {
    "r10-designated-index-initializer": "{[2] = 7} parses as a list literal holding an assignment (Stage 17)",
    "r13-flexible-array-member": "int data[] is lowered to int* data, so the struct has pointer layout (Stage 17)",
    "r13-flexible-array-not-last": "a non-final int data[] is accepted as a pointer field (Stage 17)",
    "x-enum-tag-btrc-enum": "the reference rejects enum Color for a btrc enum; btrcc emits C naming no enum (Stage 17)",
    "x-enum-tag-unknown": "an unknown enum tag passes through to C, which rejects it (Stage 17)",
    "x-hex-float-without-exponent": "0x1.8 lexes as a tuple member access 0x1._8 (Stage 19)",
    "x-alignof-expression": "_Alignof(expression) passes through as an unknown call (Stage 19)",
}

_SELFHOST_DIAGNOSTIC = re.compile(r"error: (?P<message>.*) at (?P<line>\d+):(?P<col>\d+)\n?")
_REFERENCE_DIAGNOSTIC = re.compile(r"(?i)error: (?P<message>[^\n]+)\n\s*--> .*:(?P<line>\d+):(?P<col>\d+)\n")
_UNPOSITIONED_DIAGNOSTIC = re.compile(r"(?i)error: (?P<message>[^\n]+)\n?")


def _load() -> list[dict]:
    probes = []
    for name in MANIFESTS:
        for probe in tomllib.loads((PROBES / f"{name}.toml").read_text())["probe"]:
            probes.append({**probe, "manifest": name})
    return probes


PROBE_TABLE = _load()


def _source(probe: dict) -> str:
    if "corpus" in probe:
        return (TESTS / probe["corpus"]).read_text()
    return probe["source"]


def _diagnostic(stderr: str) -> str:
    for pattern in (_SELFHOST_DIAGNOSTIC, _REFERENCE_DIAGNOSTIC):
        match = pattern.fullmatch(stderr) if pattern is _SELFHOST_DIAGNOSTIC else pattern.match(stderr)
        if match is not None:
            return f"{match.group('message')} at {match.group('line')}:{match.group('col')}"
    # A front-end refusal raised before any token has a position.
    unpositioned = _UNPOSITIONED_DIAGNOSTIC.fullmatch(stderr)
    assert unpositioned is not None, f"unrecognized diagnostic:\n{stderr}"
    return unpositioned.group("message")


def _strict_outcome(generated: Path, tmp_path: Path, frontend: str) -> dict:
    """Build with every strict C11 compiler and require one agreed outcome."""
    outcomes = {}
    for compiler in COMPILERS:
        name = Path(compiler).name
        executable = tmp_path / f"{frontend}-{name}"
        environment = _compiler_environment(compiler)
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


def _outcome(result: subprocess.CompletedProcess[str], generated: Path, tmp_path: Path, frontend: str) -> dict:
    if result.returncode != 0:
        return {"diagnostic": _diagnostic(result.stderr)}
    return _strict_outcome(generated, tmp_path, frontend)


def test_manifest_schema_and_status_vocabulary() -> None:
    identifiers = [probe["id"] for probe in PROBE_TABLE]
    assert len(identifiers) == len(set(identifiers)), "probe ids must be unique"
    for probe in PROBE_TABLE:
        label = probe["id"]
        assert probe["status"] in STATUSES, label
        assert probe["intent"] in {"positive", "negative"}, label
        assert probe["row"] in ROWS | EXTRA_GAPS | {"0"}, label
        assert re.fullmatch(r"[0-9a-f]{7,40}", probe["revision"]), label
        assert ("source" in probe) != ("corpus" in probe), label
        if probe["status"] == "refused-on-purpose":
            assert probe["row"] in REFUSAL_ROWS, label
        if probe["status"] == "accepted":
            assert probe["intent"] == "positive", label
            for frontend in ("python", "btrcc"):
                assert probe[frontend].get("exit") == 0, label
        if probe["status"] in {"rejected", "refused-on-purpose"}:
            for frontend in ("python", "btrcc"):
                assert "diagnostic" in probe[frontend], label
        if "corpus" in probe:
            corpus = Path(probe["corpus"])
            golden = TESTS / corpus.parent / "expected" / f"{corpus.stem}.stdout"
            assert probe["status"] == "accepted", label
            assert probe["python"]["stdout"] == golden.read_text(), label


def test_every_row_and_extra_gap_has_a_positive_and_a_negative_program() -> None:
    intents: dict[str, set[str]] = {}
    for probe in PROBE_TABLE:
        intents.setdefault(probe["row"], set()).add(probe["intent"])
    missing = {
        row: {"positive", "negative"} - intents.get(row, set())
        for row in sorted(ROWS | EXTRA_GAPS)
        if {"positive", "negative"} - intents.get(row, set())
    }
    assert not missing, missing


def test_known_divergences_are_exactly_the_listed_ones() -> None:
    recorded = {probe["id"] for probe in PROBE_TABLE if probe["status"] == "known-divergence"}
    assert recorded == set(KNOWN_DIVERGENCES)


def test_every_frontend_divergence_is_named() -> None:
    for probe in PROBE_TABLE:
        differs = probe["python"] != probe["btrcc"]
        assert differs == ("divergence" in probe), probe["id"]


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("probe", PROBE_TABLE, ids=lambda probe: probe["id"])
def test_recorded_outcome_holds_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    probe: dict,
) -> None:
    source = _source(probe)
    selfhost, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = _compile_reference_source(tmp_path, source)

    observed = {
        "python": _outcome(reference, reference_c, tmp_path, "python"),
        "btrcc": _outcome(selfhost, selfhost_c, tmp_path, "btrcc"),
    }
    assert observed == {"python": probe["python"], "btrcc": probe["btrcc"]}
