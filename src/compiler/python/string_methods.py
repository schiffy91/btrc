"""Built-in string-method API — the single shared spec (CMP-23).

One table maps each btrc string-method name to its return type and its
lowering. Consumed by:
  - analyzer/type_utils.py  -> return-type inference (analysis + LSP hover)
  - ir/gen/methods.py       -> dispatch to runtime helpers during lowering

The C source for every helper named here lives in ir/helpers/strings_*.py
under the same helper name; src/tests/python/test_truth_sweep.py cross-checks it.

``helper=None`` methods are lowered specially in ir/gen/methods.py: the
strlen/strcmp inlines (len/byteLen/length/equals) and the conversions in
STRING_CONVERSIONS below.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StringMethod:
    return_type: str  # btrc type name; "string*" = list of strings
    helper: str | None = None  # runtime helper; None = special-cased lowering
    tracked: bool = False  # result is a new heap string (__btrc_str_track)
    argument_types: tuple[str, ...] = ()


STRING_METHODS: dict[str, StringMethod] = {
    # Length / comparison (special-cased: strlen / strcmp inlines)
    "len": StringMethod("int"),
    "byteLen": StringMethod("int"),
    "length": StringMethod("int"),
    "charLen": StringMethod("int", "__btrc_charLen"),
    "equals": StringMethod("bool", argument_types=("string",)),
    # Queries
    "contains": StringMethod("bool", "__btrc_strContains", argument_types=("string",)),
    "startsWith": StringMethod("bool", "__btrc_startsWith", argument_types=("string",)),
    "endsWith": StringMethod("bool", "__btrc_endsWith", argument_types=("string",)),
    "indexOf": StringMethod("int", "__btrc_indexOf", argument_types=("string",)),
    "lastIndexOf": StringMethod("int", "__btrc_lastIndexOf", argument_types=("string",)),
    "find": StringMethod("int", "__btrc_find", argument_types=("string", "int")),
    "count": StringMethod("int", "__btrc_count", argument_types=("string",)),
    "charAt": StringMethod("char", "__btrc_charAt", argument_types=("int",)),
    # Predicates
    "isEmpty": StringMethod("bool", "__btrc_isEmpty"),
    "isBlank": StringMethod("bool", "__btrc_isBlank"),
    "isUpper": StringMethod("bool", "__btrc_isUpper"),
    "isLower": StringMethod("bool", "__btrc_isLower"),
    "isAlnum": StringMethod("bool", "__btrc_isAlnumStr"),
    "isAlnumStr": StringMethod("bool", "__btrc_isAlnumStr"),
    "isDigit": StringMethod("bool", "__btrc_isDigitStr"),
    "isDigitStr": StringMethod("bool", "__btrc_isDigitStr"),
    "isAlpha": StringMethod("bool", "__btrc_isAlphaStr"),
    "isAlphaStr": StringMethod("bool", "__btrc_isAlphaStr"),
    # Transforms (helpers return a new heap string -> tracked)
    "trim": StringMethod("string", "__btrc_trim", tracked=True),
    "lstrip": StringMethod("string", "__btrc_lstrip", tracked=True),
    "rstrip": StringMethod("string", "__btrc_rstrip", tracked=True),
    "toUpper": StringMethod("string", "__btrc_toUpper", tracked=True),
    "toLower": StringMethod("string", "__btrc_toLower", tracked=True),
    "substring": StringMethod(
        "string",
        "__btrc_substring",
        tracked=True,
        argument_types=("int", "int"),
    ),
    "replace": StringMethod(
        "string",
        "__btrc_replace",
        tracked=True,
        argument_types=("string", "string"),
    ),
    "repeat": StringMethod(
        "string",
        "__btrc_repeat",
        tracked=True,
        argument_types=("int",),
    ),
    "reverse": StringMethod("string", "__btrc_reverse", tracked=True),
    "capitalize": StringMethod("string", "__btrc_capitalize", tracked=True),
    "title": StringMethod("string", "__btrc_title", tracked=True),
    "swapCase": StringMethod("string", "__btrc_swapCase", tracked=True),
    "padLeft": StringMethod(
        "string",
        "__btrc_padLeft",
        tracked=True,
        argument_types=("int", "char"),
    ),
    "padRight": StringMethod(
        "string",
        "__btrc_padRight",
        tracked=True,
        argument_types=("int", "char"),
    ),
    "center": StringMethod(
        "string",
        "__btrc_center",
        tracked=True,
        argument_types=("int", "char"),
    ),
    "zfill": StringMethod(
        "string",
        "__btrc_zfill",
        tracked=True,
        argument_types=("int",),
    ),
    "removePrefix": StringMethod(
        "string",
        "__btrc_removePrefix",
        tracked=True,
        argument_types=("string",),
    ),
    "removeSuffix": StringMethod(
        "string",
        "__btrc_removeSuffix",
        tracked=True,
        argument_types=("string",),
    ),
    # Split returns a heap list of strings (not a tracked single string)
    "split": StringMethod("string*", "__btrc_split", argument_types=("string",)),
    # Conversions (special-cased: see STRING_CONVERSIONS)
    "toInt": StringMethod("int"),
    "toFloat": StringMethod("float"),
    "toDouble": StringMethod("double"),
    "toLong": StringMethod("long"),
    "toBool": StringMethod("bool"),
}

# Conversion methods lowered to C library/runtime calls: name -> (callee, cast).
STRING_CONVERSIONS: dict[str, tuple[str, str | None]] = {
    "toInt": ("__btrc_parseInt", None),
    "toFloat": ("strtof", None),
    "toDouble": ("strtod", None),
    "toLong": ("__btrc_parseLong", None),
    "toBool": ("__btrc_parseBool", None),
}
