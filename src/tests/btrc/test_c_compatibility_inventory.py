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

Recorded outcomes are never edited by hand: ``python3 -m
src.tests.btrc.c_compat_inventory record`` re-observes the selected rows
through both compilers and rewrites their ``revision`` and outcomes, refusing
any outcome the entry's ``status`` forbids (see that module).

Probe programs are kept inline rather than as ``.btrc`` files because most of
them fail to lex or parse, and the strict-import audit and the lexer-parity
check read every ``.btrc`` file under ``src/tests``. A stage that implements a
row moves its positive program into ``src/tests/c_compat`` and turns the
entry into a ``corpus`` reference in the same commit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.tests.btrc.c_compat_inventory import MANIFESTS, PROBES, TESTS, load_probes, observe, rewrite_entry
from src.tests.c_toolchains import HOST_C_COMPILERS as COMPILERS

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

PROBE_TABLE = load_probes()


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


def test_recorder_spells_every_recorded_outcome_as_the_manifest_does() -> None:
    """Re-recording an unchanged outcome leaves each manifest byte-identical."""
    for name in MANIFESTS:
        text = (PROBES / f"{name}.toml").read_text()
        rewritten = text
        for probe in (probe for probe in PROBE_TABLE if probe["manifest"] == name):
            outcome = {"python": probe["python"], "btrcc": probe["btrcc"]}
            rewritten = rewrite_entry(rewritten, probe["id"], probe["revision"], outcome)
        assert rewritten == text, name


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
    observed = observe(semantic_btrcc, tmp_path, probe)
    assert observed == {"python": probe["python"], "btrcc": probe["btrcc"]}
