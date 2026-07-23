"""Owned host-C literal selection and constant-conversion semantics."""

from __future__ import annotations

import ctypes
import math
import struct
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class CIntegerWidths:
    """Bit widths of the C integer ranks used by generated code."""

    char: int
    short: int
    int_: int
    long: int
    long_long: int

    @classmethod
    def native(cls) -> CIntegerWidths:
        """Describe the ABI targeted by the running compiler process."""

        return cls(
            char=ctypes.sizeof(ctypes.c_byte) * 8,
            short=ctypes.sizeof(ctypes.c_short) * 8,
            int_=ctypes.sizeof(ctypes.c_int) * 8,
            long=ctypes.sizeof(ctypes.c_long) * 8,
            long_long=ctypes.sizeof(ctypes.c_longlong) * 8,
        )


class NumericLiteralSemantics:
    """Own literal typing, validation, decoding, and integral conversion."""

    _INTEGER_SUFFIXES = frozenset(
        {"u", "ul", "ull", "l", "ll", "lu", "llu"},
    )
    _SIGNED_ALIASES = MappingProxyType(
        {
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
        },
    )
    _UNSIGNED_ALIASES = MappingProxyType(
        {
            "uint": "unsigned int",
            "unsigned": "unsigned int",
            "unsigned short int": "unsigned short",
            "unsigned long int": "unsigned long",
            "unsigned long long int": "unsigned long long",
        },
    )
    _SIMPLE_ESCAPES = MappingProxyType(
        {
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
        },
    )

    def __init__(self, widths: CIntegerWidths | None = None) -> None:
        self.widths = widths if widths is not None else CIntegerWidths.native()
        self._signed_limits = MappingProxyType(
            {
                "signed char": self._signed_range(self.widths.char),
                "short": self._signed_range(self.widths.short),
                "int": self._signed_range(self.widths.int_),
                "long": self._signed_range(self.widths.long),
                "long long": self._signed_range(self.widths.long_long),
            },
        )
        self._unsigned_limits = MappingProxyType(
            {
                "unsigned char": self._unsigned_range(self.widths.char),
                "unsigned short": self._unsigned_range(self.widths.short),
                "unsigned int": self._unsigned_range(self.widths.int_),
                "unsigned long": self._unsigned_range(self.widths.long),
                "unsigned long long": self._unsigned_range(
                    self.widths.long_long,
                ),
            },
        )

    def integer_type(self, raw: str, value: int) -> str:
        """Return the first C11 candidate type that can represent ``value``."""

        body, suffix = self._integer_parts(raw)
        decimal = not (
            body.startswith(("0x", "0X", "0b", "0B", "0o", "0O")) or (len(body) > 1 and body.startswith("0"))
        )
        for candidate in self._integer_candidates(suffix, decimal):
            limits = self._type_limits(candidate)
            if limits is not None and limits[0] <= value <= limits[1]:
                return candidate
        raise ValueError(
            f"Integer literal '{raw}' is out of range for its C suffix",
        )

    def parse_integer_value(self, raw: str) -> int:
        """Decode one C-style integer token after validating its suffix."""

        body, suffix = self._integer_parts(raw)
        if suffix and suffix not in self._INTEGER_SUFFIXES:
            raise ValueError(f"invalid integer suffix '{suffix}'")
        if not body:
            raise ValueError("empty integer literal")
        if len(body) > 1 and body[0] == "0" and body[1] not in "xXbBoO":
            return int(body, 8)
        return int(body, 0)

    @staticmethod
    def float_type(raw: str) -> str:
        return "float" if raw.endswith(("f", "F")) else "double"

    def float_problem(self, raw: str, value: float) -> str | None:
        """Explain a literal that cannot survive strict-C emission, if any."""

        if not math.isfinite(value):
            return f"Floating literal '{raw}' is outside the finite double range"
        if value == 0.0 and self._has_nonzero_significand(raw):
            return f"Floating literal '{raw}' underflows to zero"
        if not raw.endswith(("f", "F")):
            return None
        return self.float32_problem(raw, value)

    def float32_problem(self, raw: str, value: float) -> str | None:
        """Explain a literal that cannot retain a finite nonzero f32 value."""

        try:
            narrowed = struct.unpack("=f", struct.pack("=f", value))[0]
        except OverflowError:
            narrowed = math.inf
        if not math.isfinite(narrowed):
            return f"Floating literal '{raw}' is outside the finite float range"
        if narrowed == 0.0 and self._has_nonzero_significand(raw):
            return f"Floating literal '{raw}' underflows to zero as float"
        return None

    def decode_character(self, raw: str) -> int | None:
        """Decode one narrow-character spelling accepted by the lexer."""

        if len(raw) < 3 or raw[0] != "'" or raw[-1] != "'":
            return None
        content = raw[1:-1]
        if len(content) == 1 and content != "\\":
            return ord(content)
        if not content.startswith("\\") or len(content) < 2:
            return None
        escaped = content[1:]
        if len(escaped) == 1 and escaped in self._SIMPLE_ESCAPES:
            return self._SIMPLE_ESCAPES[escaped]
        if escaped.startswith("x") and len(escaped) > 1:
            try:
                return int(escaped[1:], 16)
            except ValueError:
                return None
        if 1 <= len(escaped) <= 3 and all(character in "01234567" for character in escaped):
            return int(escaped, 8)
        return None

    def convert_integral(
        self,
        value: int | float,
        target_base: str,
    ) -> int | None:
        """Apply a defined C scalar-to-integer constant conversion."""

        if target_base == "bool":
            return int(value != 0)
        limits = self._type_limits(target_base)
        if limits is None:
            return None
        minimum, maximum = limits
        converted = math.trunc(value) if isinstance(value, float) else value
        if isinstance(value, float):
            return converted if minimum <= converted <= maximum else None
        if minimum == 0:
            return converted % (maximum + 1)
        return converted if minimum <= converted <= maximum else None

    @staticmethod
    def _signed_range(bits: int) -> tuple[int, int]:
        return -(1 << (bits - 1)), (1 << (bits - 1)) - 1

    @staticmethod
    def _unsigned_range(bits: int) -> tuple[int, int]:
        return 0, (1 << bits) - 1

    @staticmethod
    def _has_nonzero_significand(raw: str) -> bool:
        significand = raw.split("e", 1)[0].split("E", 1)[0]
        return any(character in "123456789" for character in significand)

    @staticmethod
    def _integer_parts(raw: str) -> tuple[str, str]:
        split = len(raw)
        while split and raw[split - 1] in "uUlL":
            split -= 1
        return raw[:split], raw[split:].lower()

    @staticmethod
    def _integer_candidates(
        suffix: str,
        decimal: bool,
    ) -> tuple[str, ...]:
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
            return (
                ("long", "long long")
                if decimal
                else (
                    "long",
                    "unsigned long",
                    "long long",
                    "unsigned long long",
                )
            )
        if suffix in {"ul", "lu"}:
            return ("unsigned long", "unsigned long long")
        if suffix == "ll":
            return ("long long",) if decimal else ("long long", "unsigned long long")
        if suffix in {"ull", "llu"}:
            return ("unsigned long long",)
        raise ValueError(f"invalid integer suffix '{suffix}'")

    def _type_limits(self, base: str) -> tuple[int, int] | None:
        base = self._SIGNED_ALIASES.get(
            base,
            self._UNSIGNED_ALIASES.get(base, base),
        )
        if base == "char":
            return None
        if base in self._signed_limits:
            return self._signed_limits[base]
        if base in self._unsigned_limits:
            return self._unsigned_limits[base]
        if base.startswith(("int", "uint")) and base.endswith("_t"):
            unsigned = base.startswith("uint")
            digits = "".join(character for character in base if character.isdigit())
            if digits and "least" not in base and "fast" not in base:
                bits = int(digits)
                return self._unsigned_range(bits) if unsigned else self._signed_range(bits)
        return None


__all__ = ["CIntegerWidths", "NumericLiteralSemantics"]
