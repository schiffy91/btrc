"""Host-C literal selection and constant-conversion contracts.

The generated translation unit is compiled for the same ABI as the running
compiler.  Deriving the C rank widths from ``ctypes`` keeps literal inference
aligned on LP64 and LLP64 hosts instead of silently assuming one data model.
"""

from __future__ import annotations

import ctypes
import math
import struct


def _signed_limits(bits: int) -> tuple[int, int]:
    return -(1 << (bits - 1)), (1 << (bits - 1)) - 1


def _unsigned_limits(bits: int) -> tuple[int, int]:
    return 0, (1 << bits) - 1


_SIGNED_LIMITS = {
    "signed char": _signed_limits(ctypes.sizeof(ctypes.c_byte) * 8),
    "short": _signed_limits(ctypes.sizeof(ctypes.c_short) * 8),
    "int": _signed_limits(ctypes.sizeof(ctypes.c_int) * 8),
    "long": _signed_limits(ctypes.sizeof(ctypes.c_long) * 8),
    "long long": _signed_limits(ctypes.sizeof(ctypes.c_longlong) * 8),
}
_UNSIGNED_LIMITS = {
    "unsigned char": _unsigned_limits(ctypes.sizeof(ctypes.c_ubyte) * 8),
    "unsigned short": _unsigned_limits(ctypes.sizeof(ctypes.c_ushort) * 8),
    "unsigned int": _unsigned_limits(ctypes.sizeof(ctypes.c_uint) * 8),
    "unsigned long": _unsigned_limits(ctypes.sizeof(ctypes.c_ulong) * 8),
    "unsigned long long": _unsigned_limits(ctypes.sizeof(ctypes.c_ulonglong) * 8),
}

_SIGNED_ALIASES = {
    "byte": "signed char",
    "short int": "short",
    "signed short": "short",
    "signed short int": "short",
    "signed": "int",
    "signed int": "int",
    "long int": "long",
    "signed long": "long",
    "signed long int": "long",
    "long long int": "long long",
    "signed long long": "long long",
    "signed long long int": "long long",
}
_UNSIGNED_ALIASES = {
    "uint": "unsigned int",
    "unsigned": "unsigned int",
    "unsigned short int": "unsigned short",
    "unsigned long int": "unsigned long",
    "unsigned long long int": "unsigned long long",
}
_SIMPLE_ESCAPES = {
    "'": ord("'"),
    '"': ord('"'),
    "?": ord("?"),
    "\\": ord("\\"),
    "a": 7,
    "b": 8,
    "f": 12,
    "n": 10,
    "r": 13,
    "t": 9,
    "v": 11,
}


def integer_literal_type(raw: str, value: int) -> str:
    """Return the first C11 candidate type that can represent ``value``."""
    body, suffix = _integer_parts(raw)
    decimal = not (body.startswith(("0x", "0X", "0b", "0B", "0o", "0O")) or (len(body) > 1 and body.startswith("0")))
    candidates = _integer_candidates(suffix, decimal)
    for candidate in candidates:
        limits = _type_limits(candidate)
        if limits is not None and limits[0] <= value <= limits[1]:
            return candidate
    raise ValueError(f"Integer literal '{raw}' is out of range for its C suffix")


def float_literal_type(raw: str) -> str:
    return "float" if raw.endswith(("f", "F")) else "double"


def float_literal_problem(raw: str, value: float) -> str | None:
    """Explain a literal that cannot survive strict-C emission, if any."""
    if not math.isfinite(value):
        return f"Floating literal '{raw}' is outside the finite double range"
    nonzero_source = any(char in "123456789" for char in raw.split("e", 1)[0].split("E", 1)[0])
    if value == 0.0 and nonzero_source:
        return f"Floating literal '{raw}' underflows to zero"
    if not raw.endswith(("f", "F")):
        return None
    return float32_literal_problem(raw, value)


def float32_literal_problem(raw: str, value: float) -> str | None:
    """Explain a literal that cannot retain a finite nonzero f32 value."""
    nonzero_source = any(char in "123456789" for char in raw.split("e", 1)[0].split("E", 1)[0])
    try:
        narrowed = struct.unpack("=f", struct.pack("=f", value))[0]
    except OverflowError:
        narrowed = math.inf
    if not math.isfinite(narrowed):
        return f"Floating literal '{raw}' is outside the finite float range"
    if narrowed == 0.0 and nonzero_source:
        return f"Floating literal '{raw}' underflows to zero as float"
    return None


def decode_character_constant(raw: str) -> int | None:
    """Decode the single narrow-character spellings accepted by the lexer."""
    if len(raw) < 3 or raw[0] != "'" or raw[-1] != "'":
        return None
    content = raw[1:-1]
    if len(content) == 1 and content != "\\":
        return ord(content)
    if not content.startswith("\\") or len(content) < 2:
        return None
    escaped = content[1:]
    if len(escaped) == 1 and escaped in _SIMPLE_ESCAPES:
        return _SIMPLE_ESCAPES[escaped]
    if escaped.startswith("x") and len(escaped) > 1:
        try:
            return int(escaped[1:], 16)
        except ValueError:
            return None
    if 1 <= len(escaped) <= 3 and all(char in "01234567" for char in escaped):
        return int(escaped, 8)
    return None


def convert_integral_constant(
    value: int | float,
    target_base: str,
) -> int | None:
    """Apply a defined C scalar-to-integer constant conversion."""
    if target_base == "bool":
        return int(value != 0)
    limits = _type_limits(target_base)
    if limits is None:
        return None
    minimum, maximum = limits
    converted = math.trunc(value) if isinstance(value, float) else value
    unsigned = minimum == 0
    if isinstance(value, float):
        return converted if minimum <= converted <= maximum else None
    if unsigned:
        return converted % (maximum + 1)
    return converted if minimum <= converted <= maximum else None


def _integer_parts(raw: str) -> tuple[str, str]:
    split = len(raw)
    while split and raw[split - 1] in "uUlL":
        split -= 1
    return raw[:split], raw[split:].lower()


def _integer_candidates(suffix: str, decimal: bool) -> tuple[str, ...]:
    if suffix == "":
        return (
            ("int", "long", "long long")
            if decimal
            else (
                "int",
                "unsigned int",
                "long",
                "unsigned long",
                "long long",
                "unsigned long long",
            )
        )
    if suffix == "u":
        return ("unsigned int", "unsigned long", "unsigned long long")
    if suffix == "l":
        return ("long", "long long") if decimal else ("long", "unsigned long", "long long", "unsigned long long")
    if suffix in {"ul", "lu"}:
        return ("unsigned long", "unsigned long long")
    if suffix == "ll":
        return ("long long",) if decimal else ("long long", "unsigned long long")
    if suffix in {"ull", "llu"}:
        return ("unsigned long long",)
    raise ValueError(f"invalid integer suffix '{suffix}'")


def _type_limits(base: str) -> tuple[int, int] | None:
    base = _SIGNED_ALIASES.get(base, _UNSIGNED_ALIASES.get(base, base))
    if base == "char":
        return None
    if base in _SIGNED_LIMITS:
        return _SIGNED_LIMITS[base]
    if base in _UNSIGNED_LIMITS:
        return _UNSIGNED_LIMITS[base]
    if base.startswith(("int", "uint")) and base.endswith("_t"):
        unsigned = base.startswith("uint")
        digits = "".join(char for char in base if char.isdigit())
        if digits and "least" not in base and "fast" not in base:
            bits = int(digits)
            return _unsigned_limits(bits) if unsigned else _signed_limits(bits)
    return None


__all__ = [
    "convert_integral_constant",
    "decode_character_constant",
    "float32_literal_problem",
    "float_literal_problem",
    "float_literal_type",
    "integer_literal_type",
]
