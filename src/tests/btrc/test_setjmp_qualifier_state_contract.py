"""Structural ownership contract for selfhost setjmp analysis and safety."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ANALYSIS = REPO / "src/compiler/btrc/ir/optimization/setjmp/analysis.btrc"
SAFETY = REPO / "src/compiler/btrc/ir/optimization/setjmp/safety.btrc"

_TOP_LEVEL_MUTABLE_DECLARATION = re.compile(
    r"^(?!\s)(?!import\b)(?!typedef\b)"
    r"[A-Za-z_][A-Za-z0-9_<>,? *]*\s+"
    r"[A-Za-z_][A-Za-z0-9_]*\s*(?:=[^;]*)?;$",
    re.MULTILINE,
)
_TOP_LEVEL_BEHAVIOR = re.compile(
    r"^(?!\s)[A-Za-z_][A-Za-z0-9_<>,? *]*\s+"
    r"[A-Za-z_][A-Za-z0-9_]*\s*\(",
    re.MULTILINE,
)


def test_setjmp_qualifier_validation_has_no_mutable_ambient_state() -> None:
    source = SAFETY.read_text()

    assert "setjmpQualifierGlobals" not in source
    assert "setjmpVisibleGlobal" not in source
    assert _TOP_LEVEL_MUTABLE_DECLARATION.findall(source) == []


def test_setjmp_effect_analysis_has_one_retained_owner() -> None:
    source = ANALYSIS.read_text()

    assert "class SetjmpEffectAnalysis {" in source
    assert "private IRModule module;" in source
    assert "public Map<string, SetjmpCallEffects> analyze(IRModule module)" in source
    assert _TOP_LEVEL_BEHAVIOR.findall(source) == []


def test_setjmp_safety_has_one_explicit_module_operation() -> None:
    source = SAFETY.read_text()
    apply = source[source.index("public void apply(IRModule module)") :]

    assert "class SetjmpSafetyPlanner {" in source
    assert "private void validateGlobals(IRModule module)" in source
    assert "private void validateFunction(IRFunction definition)" in source
    assert _TOP_LEVEL_BEHAVIOR.findall(source) == []

    assert apply.count("self.validateGlobals(module);") == 1
    assert apply.count("self.effectAnalysis.analyze(module)") == 1
    assert apply.count("self.validateFunction(definition);") == 1
    assert apply.index("self.validateGlobals(module);") < apply.index("bool hasSetjmp")
    assert apply.index("self.effectAnalysis.analyze(module)") < apply.index("self.scanBlock(")
    assert apply.index("self.scanBlock(") < apply.index("self.validateFunction(")
