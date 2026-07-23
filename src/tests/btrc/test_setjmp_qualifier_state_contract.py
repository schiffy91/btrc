"""Structural ownership contract for selfhost setjmp qualifier validation."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "src/compiler/btrc/setjmp_qualifier_safety.btrc"

_TOP_LEVEL_MUTABLE_DECLARATION = re.compile(
    r"^(?!\s)(?!import\b)(?!typedef\b)"
    r"[A-Za-z_][A-Za-z0-9_<>,? *]*\s+"
    r"[A-Za-z_][A-Za-z0-9_]*\s*(?:=[^;]*)?;$",
    re.MULTILINE,
)


def test_setjmp_qualifier_validation_has_no_mutable_ambient_state() -> None:
    source = SOURCE.read_text()

    assert "setjmpQualifierGlobals" not in source
    assert "setjmpVisibleGlobal" not in source
    assert _TOP_LEVEL_MUTABLE_DECLARATION.findall(source) == []
