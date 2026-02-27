"""Single source of truth for built-in type members in the btrc language.

Auto-generated from stdlib .btrc files by tools/gen_builtins.py.
DO NOT EDIT BY HAND — edit the stdlib source or the generator instead.

Used by completion, hover, and signature help providers to avoid
maintaining separate (and inevitably divergent) copies of the same data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BuiltinMember:
    """One member (field or method) of a built-in type."""

    name: str
    return_type: str
    kind: str  # "field" or "method"
    params: list[tuple[str, str]] = field(default_factory=list)  # [(type, name)]
    doc: str = ""


# ---------------------------------------------------------------------------
# Built-in type member tables
# ---------------------------------------------------------------------------

# String methods are language intrinsics (not defined in any .btrc file)
STRING_MEMBERS: list[BuiltinMember] = [
    BuiltinMember("len", "int", "field", [], "Length of the string (bytes)"),
    BuiltinMember("charAt", "char", "method", [("int", "index")], "Character at index"),
    BuiltinMember("trim", "string", "method", [], "Remove leading/trailing whitespace"),
    BuiltinMember("lstrip", "string", "method", [], "Remove leading whitespace"),
    BuiltinMember("rstrip", "string", "method", [], "Remove trailing whitespace"),
    BuiltinMember("toUpper", "string", "method", [], "Convert to uppercase"),
    BuiltinMember("toLower", "string", "method", [], "Convert to lowercase"),
    BuiltinMember("contains", "bool", "method", [("string", "sub")], "Check if contains substring"),
    BuiltinMember("startsWith", "bool", "method", [("string", "prefix")], "Check prefix"),
    BuiltinMember("endsWith", "bool", "method", [("string", "suffix")], "Check suffix"),
    BuiltinMember("indexOf", "int", "method", [("string", "sub")], "Index of first occurrence"),
    BuiltinMember("lastIndexOf", "int", "method", [("string", "sub")], "Index of last occurrence"),
    BuiltinMember("substring", "string", "method", [("int", "start"), ("int", "end")], "Extract substring"),
    BuiltinMember("equals", "bool", "method", [("string", "other")], "Compare strings"),
    BuiltinMember("split", "List<string>", "method", [("string", "delim")], "Split into list"),
    BuiltinMember("replace", "string", "method", [("string", "old"), ("string", "replacement")], "Replace occurrences"),
    BuiltinMember("repeat", "string", "method", [("int", "count")], "Repeat N times"),
    BuiltinMember("count", "int", "method", [("string", "sub")], "Count non-overlapping occurrences"),
    BuiltinMember("find", "int", "method", [("string", "sub"), ("int", "start")], "Find from start index"),
    BuiltinMember("capitalize", "string", "method", [], "Uppercase first char"),
    BuiltinMember("title", "string", "method", [], "Capitalize each word"),
    BuiltinMember("swapCase", "string", "method", [], "Swap upper/lower case"),
    BuiltinMember("padLeft", "string", "method", [("int", "width"), ("char", "fill")], "Left-pad"),
    BuiltinMember("padRight", "string", "method", [("int", "width"), ("char", "fill")], "Right-pad"),
    BuiltinMember("center", "string", "method", [("int", "width"), ("char", "fill")], "Center with padding"),
    BuiltinMember("charLen", "int", "method", [], "UTF-8 character count"),
    BuiltinMember("byteLen", "int", "method", [], "Byte length"),
    BuiltinMember("isDigitStr", "bool", "method", [], "All chars are digits"),
    BuiltinMember("isAlphaStr", "bool", "method", [], "All chars are alphabetic"),
    BuiltinMember("isBlank", "bool", "method", [], "Empty or all whitespace"),
    BuiltinMember("isAlnum", "bool", "method", [], "All chars are alphanumeric"),
    BuiltinMember("isUpper", "bool", "method", [], "All chars are uppercase"),
    BuiltinMember("isLower", "bool", "method", [], "All chars are lowercase"),
    BuiltinMember("reverse", "string", "method", [], "Reverse the string"),
    BuiltinMember("isEmpty", "bool", "method", [], "True if string is empty"),
    BuiltinMember("removePrefix", "string", "method", [("string", "prefix")], "Remove prefix if present"),
    BuiltinMember("removeSuffix", "string", "method", [("string", "suffix")], "Remove suffix if present"),
    BuiltinMember("toInt", "int", "method", [], "Parse as integer"),
    BuiltinMember("toFloat", "float", "method", [], "Parse as float"),
    BuiltinMember("toDouble", "double", "method", [], "Parse as double"),
    BuiltinMember("toLong", "long", "method", [], "Parse as long"),
    BuiltinMember("toBool", "bool", "method", [], "Parse as bool (false for empty, \"false\", \"0\")"),
    BuiltinMember("zfill", "string", "method", [("int", "width")], "Left-pad with zeros (preserves sign)"),
]

# Generated from src/stdlib/list.btrc
LIST_MEMBERS: list[BuiltinMember] = [
    BuiltinMember("len", "int", "field", doc="len"),
    BuiltinMember("push", "void", "method", [("T", "val")], "push"),
    BuiltinMember("pop", "T", "method", [], "pop"),
    BuiltinMember("get", "T", "method", [("int", "i")], "get"),
    BuiltinMember("set", "void", "method", [("int", "i"), ("T", "val")], "set"),
    BuiltinMember("free", "void", "method", [], "free"),
    BuiltinMember("remove", "void", "method", [("int", "idx")], "remove"),
    BuiltinMember("reverse", "void", "method", [], "reverse"),
    BuiltinMember("reversed", "List<T>", "method", [], "reversed"),
    BuiltinMember("swap", "void", "method", [("int", "i"), ("int", "j")], "swap"),
    BuiltinMember("clear", "void", "method", [], "clear"),
    BuiltinMember("fill", "void", "method", [("T", "val")], "fill"),
    BuiltinMember("size", "int", "method", [], "size"),
    BuiltinMember("isEmpty", "bool", "method", [], "isEmpty"),
    BuiltinMember("first", "T", "method", [], "first"),
    BuiltinMember("last", "T", "method", [], "last"),
    BuiltinMember("slice", "List<T>", "method", [("int", "start"), ("int", "end")], "slice"),
    BuiltinMember("take", "List<T>", "method", [("int", "n")], "take"),
    BuiltinMember("drop", "List<T>", "method", [("int", "n")], "drop"),
    BuiltinMember("extend", "void", "method", [("List<T>", "other")], "extend"),
    BuiltinMember("insert", "void", "method", [("int", "idx"), ("T", "val")], "insert"),
    BuiltinMember("contains", "bool", "method", [("T", "val")], "contains"),
    BuiltinMember("indexOf", "int", "method", [("T", "val")], "indexOf"),
    BuiltinMember("lastIndexOf", "int", "method", [("T", "val")], "lastIndexOf"),
    BuiltinMember("count", "int", "method", [("T", "val")], "count"),
    BuiltinMember("removeAll", "void", "method", [("T", "val")], "removeAll"),
    BuiltinMember("distinct", "List<T>", "method", [], "distinct"),
    BuiltinMember("sort", "void", "method", [], "sort"),
    BuiltinMember("sorted", "List<T>", "method", [], "sorted"),
    BuiltinMember("min", "T", "method", [], "min"),
    BuiltinMember("max", "T", "method", [], "max"),
    BuiltinMember("sum", "T", "method", [], "sum"),
    BuiltinMember("join", "string", "method", [("string", "sep")], "join"),
    BuiltinMember("joinToString", "string", "method", [("string", "sep")], "joinToString"),
    BuiltinMember("forEach", "void", "method", [("fn", "callback")], "Call fn for each element"),
    BuiltinMember("filter", "List<T>", "method", [("fn", "predicate")], "Filter by predicate"),
    BuiltinMember("any", "bool", "method", [("fn", "predicate")], "True if any element matches"),
    BuiltinMember("all", "bool", "method", [("fn", "predicate")], "True if all elements match"),
    BuiltinMember("findIndex", "int", "method", [("fn", "predicate")], "Index of first match, -1 if not found"),
    BuiltinMember("map", "List<T>", "method", [("fn", "transform")], "Apply fn to each element"),
    BuiltinMember("reduce", "T", "method", [("T", "init"), ("fn", "accumulator")], "Fold list into single value"),
]

# Generated from src/stdlib/map.btrc
MAP_MEMBERS: list[BuiltinMember] = [
    BuiltinMember("len", "int", "field", doc="len"),
    BuiltinMember("put", "void", "method", [("K", "key"), ("V", "value")], "put"),
    BuiltinMember("get", "V", "method", [("K", "key")], "get"),
    BuiltinMember("getOrDefault", "V", "method", [("K", "key"), ("V", "fallback")], "getOrDefault"),
    BuiltinMember("has", "bool", "method", [("K", "key")], "has"),
    BuiltinMember("contains", "bool", "method", [("K", "key")], "contains"),
    BuiltinMember("putIfAbsent", "void", "method", [("K", "key"), ("V", "value")], "putIfAbsent"),
    BuiltinMember("free", "void", "method", [], "free"),
    BuiltinMember("remove", "void", "method", [("K", "key")], "remove"),
    BuiltinMember("clear", "void", "method", [], "clear"),
    BuiltinMember("size", "int", "method", [], "size"),
    BuiltinMember("isEmpty", "bool", "method", [], "isEmpty"),
    BuiltinMember("keys", "List<K>", "method", [], "keys"),
    BuiltinMember("values", "List<V>", "method", [], "values"),
    BuiltinMember("merge", "void", "method", [("Map<K, V>", "other")], "merge"),
    BuiltinMember("forEach", "void", "method", [("fn", "callback")], "Call fn(key, value) for each entry"),
    BuiltinMember("containsValue", "bool", "method", [("V", "value")], "Check if any entry has the value"),
]

# Generated from src/stdlib/set.btrc
SET_MEMBERS: list[BuiltinMember] = [
    BuiltinMember("len", "int", "field", doc="len"),
    BuiltinMember("add", "void", "method", [("T", "key")], "add"),
    BuiltinMember("contains", "bool", "method", [("T", "key")], "contains"),
    BuiltinMember("has", "bool", "method", [("T", "key")], "has"),
    BuiltinMember("remove", "void", "method", [("T", "key")], "remove"),
    BuiltinMember("free", "void", "method", [], "free"),
    BuiltinMember("clear", "void", "method", [], "clear"),
    BuiltinMember("size", "int", "method", [], "size"),
    BuiltinMember("isEmpty", "bool", "method", [], "isEmpty"),
    BuiltinMember("unite", "Set<T>", "method", [("Set<T>", "other")], "unite"),
    BuiltinMember("intersect", "Set<T>", "method", [("Set<T>", "other")], "intersect"),
    BuiltinMember("subtract", "Set<T>", "method", [("Set<T>", "other")], "subtract"),
    BuiltinMember("isSubsetOf", "bool", "method", [("Set<T>", "other")], "isSubsetOf"),
    BuiltinMember("isSupersetOf", "bool", "method", [("Set<T>", "other")], "isSupersetOf"),
    BuiltinMember("symmetricDifference", "Set<T>", "method", [("Set<T>", "other")], "symmetricDifference"),
    BuiltinMember("toList", "List<T>", "method", [], "toList"),
    BuiltinMember("copy", "Set<T>", "method", [], "copy"),
    BuiltinMember("forEach", "void", "method", [("fn", "callback")], "Call fn(element) for each element"),
    BuiltinMember("filter", "Set<T>", "method", [("fn", "predicate")], "New set of elements matching predicate"),
    BuiltinMember("any", "bool", "method", [("fn", "predicate")], "True if any element matches predicate"),
    BuiltinMember("all", "bool", "method", [("fn", "predicate")], "True if all elements match predicate"),
]

_MEMBER_TABLES: dict[str, list[BuiltinMember]] = {
    "string": STRING_MEMBERS,
    "List": LIST_MEMBERS,
    "Map": MAP_MEMBERS,
    "Set": SET_MEMBERS,
}


# ---------------------------------------------------------------------------
# Stdlib static method tables
# ---------------------------------------------------------------------------

# Generated from stdlib .btrc files
STDLIB_STATIC_METHODS: dict[str, list[BuiltinMember]] = {
    "Math": [
        BuiltinMember("PI", "float", "method", [], "PI"),
        BuiltinMember("E", "float", "method", [], "E"),
        BuiltinMember("TAU", "float", "method", [], "TAU"),
        BuiltinMember("INF", "float", "method", [], "INF"),
        BuiltinMember("abs", "int", "method", [("int", "x")], "abs"),
        BuiltinMember("fabs", "float", "method", [("float", "x")], "fabs"),
        BuiltinMember("max", "int", "method", [("int", "a"), ("int", "b")], "max"),
        BuiltinMember("min", "int", "method", [("int", "a"), ("int", "b")], "min"),
        BuiltinMember("fmax", "float", "method", [("float", "a"), ("float", "b")], "fmax"),
        BuiltinMember("fmin", "float", "method", [("float", "a"), ("float", "b")], "fmin"),
        BuiltinMember("clamp", "int", "method", [("int", "x"), ("int", "lo"), ("int", "hi")], "clamp"),
        BuiltinMember("power", "float", "method", [("float", "base"), ("int", "exp")], "power"),
        BuiltinMember("sqrt", "float", "method", [("float", "x")], "sqrt"),
        BuiltinMember("factorial", "int", "method", [("int", "n")], "factorial"),
        BuiltinMember("gcd", "int", "method", [("int", "a"), ("int", "b")], "gcd"),
        BuiltinMember("lcm", "int", "method", [("int", "a"), ("int", "b")], "lcm"),
        BuiltinMember("fibonacci", "int", "method", [("int", "n")], "fibonacci"),
        BuiltinMember("isPrime", "bool", "method", [("int", "n")], "isPrime"),
        BuiltinMember("isEven", "bool", "method", [("int", "n")], "isEven"),
        BuiltinMember("isOdd", "bool", "method", [("int", "n")], "isOdd"),
        BuiltinMember("sum", "int", "method", [("List<int>", "items")], "sum"),
        BuiltinMember("fsum", "float", "method", [("List<float>", "items")], "fsum"),
        BuiltinMember("sin", "float", "method", [("float", "x")], "sin"),
        BuiltinMember("cos", "float", "method", [("float", "x")], "cos"),
        BuiltinMember("tan", "float", "method", [("float", "x")], "tan"),
        BuiltinMember("asin", "float", "method", [("float", "x")], "asin"),
        BuiltinMember("acos", "float", "method", [("float", "x")], "acos"),
        BuiltinMember("atan", "float", "method", [("float", "x")], "atan"),
        BuiltinMember("atan2", "float", "method", [("float", "y"), ("float", "x")], "atan2"),
        BuiltinMember("ceil", "float", "method", [("float", "x")], "ceil"),
        BuiltinMember("floor", "float", "method", [("float", "x")], "floor"),
        BuiltinMember("round", "int", "method", [("float", "x")], "round"),
        BuiltinMember("truncate", "int", "method", [("float", "x")], "truncate"),
        BuiltinMember("log", "float", "method", [("float", "x")], "log"),
        BuiltinMember("log10", "float", "method", [("float", "x")], "log10"),
        BuiltinMember("log2", "float", "method", [("float", "x")], "log2"),
        BuiltinMember("exp", "float", "method", [("float", "x")], "exp"),
        BuiltinMember("toRadians", "float", "method", [("float", "degrees")], "toRadians"),
        BuiltinMember("toDegrees", "float", "method", [("float", "radians")], "toDegrees"),
        BuiltinMember("fclamp", "float", "method", [("float", "val"), ("float", "lo"), ("float", "hi")], "fclamp"),
        BuiltinMember("sign", "int", "method", [("int", "x")], "sign"),
        BuiltinMember("fsign", "float", "method", [("float", "x")], "fsign"),
    ],
    "Strings": [
        BuiltinMember("repeat", "string", "method", [("string", "s"), ("int", "count")], "repeat"),
        BuiltinMember("join", "string", "method", [("List<string>", "items"), ("string", "sep")], "join"),
        BuiltinMember("replace", "string", "method", [("string", "s"), ("string", "old"), ("string", "replacement")], "replace"),
        BuiltinMember("isDigit", "bool", "method", [("char", "c")], "isDigit"),
        BuiltinMember("isAlpha", "bool", "method", [("char", "c")], "isAlpha"),
        BuiltinMember("isAlnum", "bool", "method", [("char", "c")], "isAlnum"),
        BuiltinMember("isSpace", "bool", "method", [("char", "c")], "isSpace"),
        BuiltinMember("toInt", "int", "method", [("string", "s")], "toInt"),
        BuiltinMember("toFloat", "float", "method", [("string", "s")], "toFloat"),
        BuiltinMember("count", "int", "method", [("string", "s"), ("string", "sub")], "count"),
        BuiltinMember("find", "int", "method", [("string", "s"), ("string", "sub"), ("int", "start")], "find"),
        BuiltinMember("rfind", "int", "method", [("string", "s"), ("string", "sub")], "rfind"),
        BuiltinMember("capitalize", "string", "method", [("string", "s")], "capitalize"),
        BuiltinMember("title", "string", "method", [("string", "s")], "title"),
        BuiltinMember("swapCase", "string", "method", [("string", "s")], "swapCase"),
        BuiltinMember("padLeft", "string", "method", [("string", "s"), ("int", "width"), ("char", "fill")], "padLeft"),
        BuiltinMember("padRight", "string", "method", [("string", "s"), ("int", "width"), ("char", "fill")], "padRight"),
        BuiltinMember("center", "string", "method", [("string", "s"), ("int", "width"), ("char", "fill")], "center"),
        BuiltinMember("lstrip", "string", "method", [("string", "s")], "lstrip"),
        BuiltinMember("rstrip", "string", "method", [("string", "s")], "rstrip"),
        BuiltinMember("fromInt", "string", "method", [("int", "n")], "fromInt"),
        BuiltinMember("fromFloat", "string", "method", [("float", "f")], "fromFloat"),
        BuiltinMember("isDigitStr", "bool", "method", [("string", "s")], "isDigitStr"),
        BuiltinMember("isAlphaStr", "bool", "method", [("string", "s")], "isAlphaStr"),
        BuiltinMember("isBlank", "bool", "method", [("string", "s")], "isBlank"),
    ],
    "Path": [
        BuiltinMember("exists", "bool", "method", [("string", "path")], "exists"),
        BuiltinMember("readAll", "string", "method", [("string", "path")], "readAll"),
        BuiltinMember("writeAll", "void", "method", [("string", "path"), ("string", "content")], "writeAll"),
    ],
    "Console": [
        BuiltinMember("log", "void", "method", [("string", "msg")], "log"),
        BuiltinMember("error", "void", "method", [("string", "msg")], "error"),
        BuiltinMember("write", "void", "method", [("string", "msg")], "write"),
        BuiltinMember("writeLine", "void", "method", [("string", "msg")], "writeLine"),
    ],
}

# Built-in free function signatures: name -> (return_type, [(param_type, param_name)])
BUILTIN_FUNCTION_SIGNATURES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "println": ("void", [("string", "message")]),
    "print": ("void", [("string", "message")]),
    "input": ("string", [("string", "prompt")]),
    "toString": ("string", [("int", "value")]),
    "toInt": ("int", [("string", "value")]),
    "toFloat": ("float", [("string", "value")]),
    "len": ("int", [("string", "s")]),
    "range": ("List<int>", [("int", "n")]),
    "exit": ("void", [("int", "code")]),
}


# ---------------------------------------------------------------------------
# Accessor functions
# ---------------------------------------------------------------------------


def get_members_for_type(type_name: str) -> list[BuiltinMember]:
    """Return the list of built-in members for a type, or empty list."""
    return _MEMBER_TABLES.get(type_name, [])


def get_member(type_name: str, member_name: str) -> Optional[BuiltinMember]:
    """Look up a specific member on a built-in type."""
    for m in _MEMBER_TABLES.get(type_name, []):
        if m.name == member_name:
            return m
    return None


def get_hover_markdown(type_name: str, member_name: str) -> Optional[str]:
    """Generate a markdown hover string for a built-in type member."""
    m = get_member(type_name, member_name)
    if m is None:
        return None
    if m.kind == "field":
        return f"```btrc\n{m.return_type} {m.name}\n```\n{m.doc}"
    params_str = ", ".join(f"{pt} {pn}" for pt, pn in m.params)
    return f"```btrc\n{m.return_type} {m.name}({params_str})\n```\n{m.doc}"


def get_signature_params(
    type_name: str, method_name: str
) -> Optional[list[tuple[str, str]]]:
    """Return the parameter list for a built-in type method, or None."""
    m = get_member(type_name, method_name)
    if m is None or m.kind == "field":
        return None
    return m.params


def get_stdlib_methods(class_name: str) -> Optional[list[BuiltinMember]]:
    """Return the list of static methods for a stdlib class, or None."""
    return STDLIB_STATIC_METHODS.get(class_name)


def get_stdlib_signature(
    class_name: str, method_name: str
) -> Optional[list[tuple[str, str]]]:
    """Return the parameter list for a stdlib static method, or None."""
    methods = STDLIB_STATIC_METHODS.get(class_name)
    if methods is None:
        return None
    for m in methods:
        if m.name == method_name:
            return m.params
    return None
