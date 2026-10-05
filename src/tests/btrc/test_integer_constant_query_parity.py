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


# Known integer-constant divergences after CL-C-08, recorded so later lanes see
# them: probe -> (meaning, program, Python's first diagnostic, btrc's first
# diagnostic). ``None`` is acceptance; a duplicate label is ``_DUPLICATE``.
# Each is pinned by the test below, so a lane that brings the two compilers
# together must move its row into BATTERY. The C2 shared-owner commit changed
# only Python's ``long long`` rule; none of these was in scope.
_CASE_PAIR = "enum Color {{ RED, GREEN }};\n{prefix}int main() {{\n    long long x = 0;\n    switch (x) {{\n        case {label}: break;\n        case {label}: break;\n    }}\n    return 0;\n}}\n"
KNOWN_DIVERGENCES = {
    "errno": (
        "Python: not a constant; btrc: a C macro it cannot evaluate",
        _CASE_PAIR.format(prefix="", label="errno"),
        _REFUSED,
        None,
    ),
    "lowercase-source-macro": (
        "a declared lowercase source macro: Python cannot evaluate it; btrc says not a constant",
        _CASE_PAIR.format(prefix="#define limit 4\n", label="limit"),
        None,
        _REFUSED,
    ),
    "enum-cast": (
        "(Color)1: Python cannot evaluate (no range for an enum target); btrc folds it to 1",
        _CASE_PAIR.format(prefix="", label="(Color)1"),
        None,
        _DUPLICATE,
    ),
    "case-division-by-zero": (
        "7 / 0 in a case label: Python's expression analysis reports first; btrc reports the constant refusal",
        _CASE_PAIR.format(prefix="", label="7 / 0"),
        "Division by zero",
        _REFUSED,
    ),
    "enum-value-from-other-enum": (
        "enum Other { X = RED }: Python accepts a member of another enum; btrc refuses it",
        "enum Color { RED, GREEN };\nenum Other { X = RED };\nint main() { return 0; }\n",
        None,
        "Enum value 'X' requires an integral constant expression using only earlier members",
    ),
}

# Divergences no switch probe reaches, or that depend on the platform:
# - an unsupported binary operator over an operand btrc cannot evaluate:
#   btrc answers "cannot evaluate", Python "not a constant";
# - the cast-range tables are separate (btrc ConstantValidator.integralCastRange,
#   Python NumericLiteralSemantics._type_limits); nothing compares them;
# - float-literal casts: btrc converts with strtold (80-bit on Linux x86-64,
#   double on macOS arm64), Python and gcc/clang with double. On Linux x86-64
#   `(unsigned long long)18446744073709551615.0` is "cannot evaluate" in btrc and
#   "not a constant" in Python, and `(long long)9007199254740993.0` is
#   9007199254740993 in btrc and 9007199254740992 in Python; on macOS arm64
#   both compilers agree.
PLATFORM_DIVERGENCES = {
    "float-cast-beyond-double": (
        _CASE_PAIR.format(prefix="", label="(unsigned long long)18446744073709551615.0"),
        _REFUSED,
        None,
    ),
    # Python folds the cast to 9007199254740992 (a double), so the second
    # label duplicates it; btrc's 80-bit strtold keeps 9007199254740993.
    "float-cast-beyond-53-bits": (
        _CASE_PAIR.replace("{label}: break;\n        case {label}", "{first}: break;\n        case {second}").format(
            prefix="", first="(long long)9007199254740993.0", second="9007199254740992"
        ),
        _DUPLICATE,
        None,
    ),
}


@pytest.mark.parametrize("name", sorted(KNOWN_DIVERGENCES))
def test_recorded_integer_constant_divergences_still_hold(harness: ConstantHarness, name: str) -> None:
    _meaning, program, python, btrc = KNOWN_DIVERGENCES[name]
    reference, selfhost = harness.compile(program)
    assert (reference.message, selfhost.message) == (python, btrc)


@pytest.mark.skipif(
    not (sys.platform.startswith("linux") and os.uname().machine == "x86_64"),
    reason="btrc's strtold is 80-bit only on Linux x86-64",
)
@pytest.mark.parametrize("name", sorted(PLATFORM_DIVERGENCES))
def test_recorded_platform_divergences_still_hold(harness: ConstantHarness, name: str) -> None:
    program, python, btrc = PLATFORM_DIVERGENCES[name]
    reference, selfhost = harness.compile(program)
    assert (reference.message, selfhost.message) == (python, btrc)
