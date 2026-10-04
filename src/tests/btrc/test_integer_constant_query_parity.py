"""Both compilers give one integer-constant query the same three answers (C2).

Python ``ExpressionAnalyzer.integer_constant_expression`` and btrc
``ConstantValidator.integerConstant`` answer every integer constant
expression with one of three results (docs/design/c-compatibility.md,
"Shared owners"): not a constant expression; a constant expression btrc
cannot evaluate (``sizeof``, a C macro, a value only an unsigned type can
hold); or a ``long long`` value. Every evaluated value is a C ``long long``:
an operation whose result leaves that range is not a constant expression,
which is the rule Python adopted from btrc in the shared-owner commit.

``switch`` labels observe the three answers without a dedicated flag: a
label that is not a constant is refused, two labels with one known value are
duplicates, and an unevaluated label is accepted unchecked. A known value is
pinned by pairing the expression with a literal label of that value.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.tests.btrc.diagnostic_harness import REFERENCE_DIAGNOSTIC, SELFHOST_DIAGNOSTIC

REPO = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires the POSIX self-host driver")

NOT_CONSTANT = "not constant"
CANNOT_EVALUATE = "cannot evaluate"

_REFUSED = "Switch case requires an integral constant expression"
_DUPLICATE = "Duplicate switch case value"


@dataclass(frozen=True)
class ConstantProbe:
    """One expression and its answer: a value, NOT_CONSTANT or CANNOT_EVALUATE."""

    name: str
    expression: str
    answer: int | str


BATTERY = (
    ConstantProbe("literal", "7", 7),
    ConstantProbe("llong-max", "9223372036854775807", 9223372036854775807),
    ConstantProbe("beyond-llong-literal", "18446744073709551615ULL", CANNOT_EVALUATE),
    ConstantProbe("hex-beyond-llong-literal", "0xFFFFFFFFFFFFFFFF", CANNOT_EVALUATE),
    ConstantProbe("arithmetic", "(1 + 2) * 3 - 4", 5),
    ConstantProbe("truncating-division", "-7 / 2", -3),
    ConstantProbe("truncating-remainder", "-7 % 2", -1),
    ConstantProbe("add-overflow", "9223372036854775807 + 1", NOT_CONSTANT),
    ConstantProbe("subtract-overflow", "-9223372036854775807 - 2", NOT_CONSTANT),
    ConstantProbe("multiply-overflow", "4611686018427387904 * 2", NOT_CONSTANT),
    ConstantProbe("negate-llong-min", "-(-9223372036854775807 - 1)", NOT_CONSTANT),
    ConstantProbe("divide-llong-min", "(-9223372036854775807 - 1) / -1", NOT_CONSTANT),
    ConstantProbe("remainder-by-zero-shifted", "7 % (1 >> 1)", NOT_CONSTANT),
    ConstantProbe("shift", "1 << 62", 4611686018427387904),
    ConstantProbe("shift-overflow", "1 << 63", NOT_CONSTANT),
    ConstantProbe("shift-negative-left", "-1 << 1", NOT_CONSTANT),
    ConstantProbe("shift-width", "1 << 64", NOT_CONSTANT),
    ConstantProbe("negative-right-shift", "-8 >> 1", CANNOT_EVALUATE),
    ConstantProbe("right-shift", "64 >> 3", 8),
    ConstantProbe("bitwise", "(12 & 10) | (1 ^ 3) | ~-1", 10),
    ConstantProbe("comparison", "(3 < 4 && 4 <= 4) == (5 != 5) ? 20 : 30", 30),
    ConstantProbe("logical", "(2 > 1 && 0 > 1) || !(0 > 1 || 3 > 1) ? 1 : 7", 7),
    ConstantProbe("signed-cast-out-of-range", "(short)70000", NOT_CONSTANT),
    ConstantProbe("float-cast-out-of-range", "(int)100000000000.0", NOT_CONSTANT),
    ConstantProbe("ternary", "1 ? 11 : 12", 11),
    ConstantProbe("ternary-unknown-equal-arms", "sizeof(int) ? 4 : 4", 4),
    ConstantProbe("ternary-unknown-condition", "sizeof(int) ? 4 : 5", CANNOT_EVALUATE),
    ConstantProbe("character", "'A'", 65),
    ConstantProbe("bool", "(int)true + (int)true", 2),
    ConstantProbe("sizeof", "sizeof(int)", CANNOT_EVALUATE),
    ConstantProbe("sizeof-string", 'sizeof("abc")', 4),
    ConstantProbe("hosted-macro", "INT_MAX", CANNOT_EVALUATE),
    ConstantProbe("unsigned-cast-wrap", "(unsigned char)300", 44),
    ConstantProbe("unsigned-cast-beyond-llong", "(unsigned long long)-1", CANNOT_EVALUATE),
    ConstantProbe("float-cast", "(int)2.9", 2),
    ConstantProbe("enum-member", "Color.GREEN", 1),
    ConstantProbe("variable", "x", NOT_CONSTANT),
)


def _program(first: str, second: str) -> str:
    return (
        "enum Color { RED, GREEN };\n"
        "int main() {\n"
        "    long long x = 0;\n"
        "    switch (x) {\n"
        f"        case {first}: break;\n"
        f"        case {second}: break;\n"
        "    }\n"
        "    return 0;\n"
        "}\n"
    )


@dataclass(frozen=True)
class Outcome:
    """A compile's first diagnostic, or ``None`` for acceptance."""

    message: str | None
    line: int = 0
    col: int = 0


class ConstantHarness:
    def __init__(self, btrcc: Path, workspace: Path) -> None:
        self._btrcc = btrcc
        self._workspace = workspace

    def compile(self, source: str) -> tuple[Outcome, Outcome]:
        program = self._workspace / "probe.btrc"
        program.write_text(source)
        reference = subprocess.run(
            [sys.executable, "-m", "src.compiler.python.main", str(program), "--no-cache", "--no-stdlib"]
            + ["-o", str(self._workspace / "reference.c")],
            cwd=REPO,
            capture_output=True,
            text=True,
            env={**os.environ, "BTRC_CACHE_DIR": str(self._workspace / "reference-cache")},
            timeout=120,
        )
        selfhost = subprocess.run(
            [str(self._btrcc), "--no-stdlib", str(program)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return (
            self._outcome(reference, REFERENCE_DIAGNOSTIC),
            self._outcome(selfhost, SELFHOST_DIAGNOSTIC),
        )

    @staticmethod
    def _outcome(result: subprocess.CompletedProcess[str], pattern) -> Outcome:
        if result.returncode == 0:
            return Outcome(None)
        match = pattern.search(result.stderr)
        assert match is not None, result.stderr
        message = match.group(1)
        # Python names the duplicated value; the label position is the identity.
        if message.startswith(_DUPLICATE):
            message = _DUPLICATE
        return Outcome(message, int(match.group(2)), int(match.group(3)))


@pytest.fixture
def harness(immutable_btrcc: Path, tmp_path: Path) -> ConstantHarness:
    return ConstantHarness(immutable_btrcc, tmp_path)


@pytest.mark.parametrize("probe", BATTERY, ids=lambda probe: probe.name)
def test_both_compilers_answer_the_integer_constant_query_identically(
    harness: ConstantHarness, probe: ConstantProbe
) -> None:
    reference, selfhost = harness.compile(_program(probe.expression, probe.expression))
    assert selfhost == reference
    if probe.answer == NOT_CONSTANT:
        assert reference.message == _REFUSED
        assert reference.line == 5
    elif probe.answer == CANNOT_EVALUATE:
        assert reference.message is None
    else:
        assert reference == Outcome(_DUPLICATE, 6, reference.col)
        pinned_reference, pinned_selfhost = harness.compile(_program(probe.expression, str(probe.answer)))
        assert pinned_selfhost == pinned_reference
        assert pinned_reference.message == _DUPLICATE
