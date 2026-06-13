"""Built-in string-method API — the single shared spec (CMP-23).

One table maps each btrc string-method name to its return type and its
lowering. Consumed by:
  - analyzer/type_utils.py  -> return-type inference (analysis + LSP hover)
  - ir/gen/methods.py       -> dispatch to runtime helpers during lowering

The C source for every helper named here lives in ir/helpers/strings_*.py
under the same helper name; tests/test_truth_sweep.py cross-checks that.

``helper=None`` methods are lowered specially in ir/gen/methods.py: the
strlen/strcmp inlines (len/byteLen/length/equals) and the conversions in
STRING_CONVERSIONS below. ``toBool`` is analysis-only: no lowering exists
yet (pre-existing drift, kept documented here rather than silently split
across files).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StringMethod:
    return_type: str            # btrc type name; "string*" = list of strings
    helper: str | None = None   # runtime helper; None = special-cased lowering
    tracked: bool = False       # result is a new heap string (__btrc_str_track)


STRING_METHODS: dict[str, StringMethod] = {
    # Length / comparison (special-cased: strlen / strcmp inlines)
    "len": StringMethod("int"),
    "byteLen": StringMethod("int"),
    "length": StringMethod("int"),
    "charLen": StringMethod("int", "__btrc_charLen"),
    "equals": StringMethod("bool"),
    # Queries
    "contains": StringMethod("bool", "__btrc_strContains"),
    "startsWith": StringMethod("bool", "__btrc_startsWith"),
    "endsWith": StringMethod("bool", "__btrc_endsWith"),
    "indexOf": StringMethod("int", "__btrc_indexOf"),
    "lastIndexOf": StringMethod("int", "__btrc_lastIndexOf"),
    "find": StringMethod("int", "__btrc_find"),
    "count": StringMethod("int", "__btrc_count"),
    "charAt": StringMethod("char", "__btrc_charAt"),
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
    "substring": StringMethod("string", "__btrc_substring", tracked=True),
    "replace": StringMethod("string", "__btrc_replace", tracked=True),
    "repeat": StringMethod("string", "__btrc_repeat", tracked=True),
    "reverse": StringMethod("string", "__btrc_reverse", tracked=True),
    "capitalize": StringMethod("string", "__btrc_capitalize", tracked=True),
    "title": StringMethod("string", "__btrc_title", tracked=True),
    "swapCase": StringMethod("string", "__btrc_swapCase", tracked=True),
    "padLeft": StringMethod("string", "__btrc_padLeft", tracked=True),
    "padRight": StringMethod("string", "__btrc_padRight", tracked=True),
    "center": StringMethod("string", "__btrc_center", tracked=True),
    "zfill": StringMethod("string", "__btrc_zfill", tracked=True),
    "removePrefix": StringMethod("string", "__btrc_removePrefix", tracked=True),
    "removeSuffix": StringMethod("string", "__btrc_removeSuffix", tracked=True),
    "join": StringMethod("string", "__btrc_join", tracked=True),
    # Split returns a heap list of strings (not a tracked single string)
    "split": StringMethod("string*", "__btrc_split"),
    # Conversions (special-cased: see STRING_CONVERSIONS)
    "toInt": StringMethod("int"),
    "toFloat": StringMethod("float"),
    "toDouble": StringMethod("double"),
    "toLong": StringMethod("long"),
    "toBool": StringMethod("bool"),
}

# Conversion methods lowered to C stdlib calls: name -> (c_func, cast_to).
STRING_CONVERSIONS: dict[str, tuple[str, str | None]] = {
    "toInt": ("atoi", "int"),
    "toFloat": ("atof", "float"),
    "toDouble": ("atof", None),
    "toLong": ("atol", None),
}
