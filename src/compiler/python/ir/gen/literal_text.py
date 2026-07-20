"""Target-language spelling for source literals lowered into C IR."""

from __future__ import annotations


def format_c_integer_literal(raw: str | None, value: int) -> str:
    """Return a strict-C11 spelling for one parsed integer literal.

    Binary literals are a btrc source feature, not a C11 feature.  Hexadecimal
    is the equivalent C11 spelling that retains the non-decimal integer-type
    selection rules.  Integer suffix spelling is preserved verbatim.
    """
    if not raw:
        return str(value)

    body_end = len(raw)
    while body_end and raw[body_end - 1] in "uUlL":
        body_end -= 1
    body = raw[:body_end]
    suffix = raw[body_end:]

    if body.startswith(("0b", "0B")):
        return f"0x{int(body[2:], 2):x}{suffix}"
    if body.startswith(("0o", "0O")):
        return f"0{body[2:]}{suffix}"
    return raw
