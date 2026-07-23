"""Structural ownership contract for selfhost setjmp qualifier validation."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "src/compiler/btrc/setjmp_qualifier_safety.btrc"
CONTROL_FLOW = REPO / "src/compiler/btrc/setjmp_control_flow.btrc"

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
    source = SOURCE.read_text()

    assert "setjmpQualifierGlobals" not in source
    assert "setjmpVisibleGlobal" not in source
    assert _TOP_LEVEL_MUTABLE_DECLARATION.findall(source) == []


def test_setjmp_qualifier_behavior_has_one_instance_owner() -> None:
    source = SOURCE.read_text()

    assert "class SetjmpQualifierValidator {" in source
    assert "public void validateGlobals(IRModule module)" in source
    assert "public void validateFunction(IRFunction definition)" in source
    assert _TOP_LEVEL_BEHAVIOR.findall(source) == []


def test_setjmp_control_flow_reuses_one_qualifier_validator() -> None:
    source = CONTROL_FLOW.read_text()
    apply = source[source.index("void applySetjmpVolatility(IRModule module)") :]

    construction = "SetjmpQualifierValidator qualifierValidator ="
    validate_globals = "qualifierValidator.validateGlobals(module);"
    validate_function = "qualifierValidator.validateFunction(definition);"

    assert apply.count(construction) == 1
    assert apply.count(validate_globals) == 1
    assert apply.count(validate_function) == 1
    assert apply.index(construction) < apply.index(validate_globals)
    assert apply.index(validate_globals) < apply.index("bool hasSetjmp")
    assert apply.index("scanSetjmpBlock(") < apply.index(validate_function)
