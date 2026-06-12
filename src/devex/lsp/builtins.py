"""Single source of truth for built-in type members in the btrc language.

Auto-generated from stdlib .btrc files by src/language/ast/gen_builtins.py.
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
    BuiltinMember("split", "Vector<string>", "method", [("string", "delim")], "Split into list"),
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

# Generated from src/stdlib/array.btrc
ARRAY_MEMBERS: list[BuiltinMember] = [
    BuiltinMember("len", "int", "field", doc="len"),
    BuiltinMember("get", "T", "method", [("int", "i")], "get"),
    BuiltinMember("set", "void", "method", [("int", "i"), ("T", "val")], "set"),
    BuiltinMember("fill", "void", "method", [("T", "val")], "fill"),
    BuiltinMember("contains", "bool", "method", [("T", "val")], "contains"),
    BuiltinMember("indexOf", "int", "method", [("T", "val")], "indexOf"),
    BuiltinMember("swap", "void", "method", [("int", "i"), ("int", "j")], "swap"),
    BuiltinMember("reverse", "void", "method", [], "reverse"),
    BuiltinMember("size", "int", "method", [], "size"),
    BuiltinMember("isEmpty", "bool", "method", [], "isEmpty"),
    BuiltinMember("free", "void", "method", [], "free"),
    BuiltinMember("iterLen", "int", "method", [], "iterLen"),
    BuiltinMember("iterGet", "T", "method", [("int", "i")], "iterGet"),
]

# Generated from src/stdlib/listnode.btrc
LISTNODE_MEMBERS: list[BuiltinMember] = [
    BuiltinMember("value", "T", "field", doc="value"),
    BuiltinMember("next", "ListNode<T>", "field", doc="next"),
    BuiltinMember("prev", "ListNode<T>", "field", doc="prev"),
    BuiltinMember("free", "void", "method", [], "free"),
]

# Generated from src/stdlib/list.btrc
LIST_MEMBERS: list[BuiltinMember] = [
    BuiltinMember("head", "ListNode<T>", "field", doc="head"),
    BuiltinMember("tail", "ListNode<T>", "field", doc="tail"),
    BuiltinMember("len", "int", "field", doc="len"),
    BuiltinMember("pushBack", "void", "method", [("T", "val")], "pushBack"),
    BuiltinMember("pushFront", "void", "method", [("T", "val")], "pushFront"),
    BuiltinMember("push", "void", "method", [("T", "val")], "push"),
    BuiltinMember("popBack", "T", "method", [], "popBack"),
    BuiltinMember("popFront", "T", "method", [], "popFront"),
    BuiltinMember("pop", "T", "method", [], "pop"),
    BuiltinMember("front", "T", "method", [], "front"),
    BuiltinMember("back", "T", "method", [], "back"),
    BuiltinMember("get", "T", "method", [("int", "idx")], "get"),
    BuiltinMember("set", "void", "method", [("int", "idx"), ("T", "val")], "set"),
    BuiltinMember("size", "int", "method", [], "size"),
    BuiltinMember("isEmpty", "bool", "method", [], "isEmpty"),
    BuiltinMember("contains", "bool", "method", [("T", "val")], "contains"),
    BuiltinMember("indexOf", "int", "method", [("T", "val")], "indexOf"),
    BuiltinMember("insert", "void", "method", [("int", "idx"), ("T", "val")], "insert"),
    BuiltinMember("remove", "void", "method", [("int", "idx")], "remove"),
    BuiltinMember("reverse", "void", "method", [], "reverse"),
    BuiltinMember("clear", "void", "method", [], "clear"),
    BuiltinMember("free", "void", "method", [], "free"),
    BuiltinMember("toVector", "Vector<T>", "method", [], "toVector"),
    BuiltinMember("iterLen", "int", "method", [], "iterLen"),
    BuiltinMember("iterGet", "T", "method", [("int", "n")], "iterGet"),
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
    BuiltinMember("keys", "Vector<K>", "method", [], "keys"),
    BuiltinMember("values", "Vector<V>", "method", [], "values"),
    BuiltinMember("containsValue", "bool", "method", [("V", "value")], "containsValue"),
    BuiltinMember("set", "void", "method", [("K", "key"), ("V", "value")], "set"),
    BuiltinMember("merge", "void", "method", [("Map<K, V>", "other")], "merge"),
    BuiltinMember("iterLen", "int", "method", [], "iterLen"),
    BuiltinMember("iterGet", "K", "method", [("int", "n")], "iterGet"),
    BuiltinMember("iterValueAt", "V", "method", [("int", "n")], "iterValueAt"),
    BuiltinMember("forEach", "void", "method", [("fn", "callback")], "Call fn(key, value) for each entry"),
]

# Generated from src/stdlib/result.btrc
RESULT_MEMBERS: list[BuiltinMember] = [
    BuiltinMember("isOk", "bool", "method", [], "isOk"),
    BuiltinMember("isErr", "bool", "method", [], "isErr"),
    BuiltinMember("unwrap", "T", "method", [], "unwrap"),
    BuiltinMember("unwrapErr", "E", "method", [], "unwrapErr"),
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
    BuiltinMember("toVector", "Vector<T>", "method", [], "toVector"),
    BuiltinMember("copy", "Set<T>", "method", [], "copy"),
    BuiltinMember("filter", "Set<T>", "method", [("__fn_ptr<bool, T>", "pred")], "filter"),
    BuiltinMember("any", "bool", "method", [("__fn_ptr<bool, T>", "pred")], "any"),
    BuiltinMember("all", "bool", "method", [("__fn_ptr<bool, T>", "pred")], "all"),
    BuiltinMember("forEach", "void", "method", [("__fn_ptr<void, T>", "fn")], "forEach"),
    BuiltinMember("iterLen", "int", "method", [], "iterLen"),
    BuiltinMember("iterGet", "T", "method", [("int", "n")], "iterGet"),
]

# Generated from src/stdlib/state.btrc
STATE_MEMBERS: list[BuiltinMember] = [
    BuiltinMember("value", "T", "field", doc="value"),
    BuiltinMember("version", "int", "field", doc="version"),
    BuiltinMember("get", "T", "method", [], "get"),
    BuiltinMember("set", "State<T>", "method", [("T", "value")], "set"),
    BuiltinMember("changedSince", "bool", "method", [("int", "seenVersion")], "changedSince"),
]

# Generated from src/stdlib/vector.btrc
VECTOR_MEMBERS: list[BuiltinMember] = [
    BuiltinMember("len", "int", "field", doc="len"),
    BuiltinMember("push", "void", "method", [("T", "val")], "push"),
    BuiltinMember("pop", "T", "method", [], "pop"),
    BuiltinMember("get", "T", "method", [("int", "i")], "get"),
    BuiltinMember("set", "void", "method", [("int", "i"), ("T", "val")], "set"),
    BuiltinMember("free", "void", "method", [], "free"),
    BuiltinMember("remove", "void", "method", [("int", "idx")], "remove"),
    BuiltinMember("reverse", "void", "method", [], "reverse"),
    BuiltinMember("reversed", "Vector<T>", "method", [], "reversed"),
    BuiltinMember("swap", "void", "method", [("int", "i"), ("int", "j")], "swap"),
    BuiltinMember("clear", "void", "method", [], "clear"),
    BuiltinMember("fill", "void", "method", [("T", "val")], "fill"),
    BuiltinMember("size", "int", "method", [], "size"),
    BuiltinMember("isEmpty", "bool", "method", [], "isEmpty"),
    BuiltinMember("first", "T", "method", [], "first"),
    BuiltinMember("last", "T", "method", [], "last"),
    BuiltinMember("slice", "Vector<T>", "method", [("int", "start"), ("int", "end")], "slice"),
    BuiltinMember("take", "Vector<T>", "method", [("int", "n")], "take"),
    BuiltinMember("drop", "Vector<T>", "method", [("int", "n")], "drop"),
    BuiltinMember("extend", "void", "method", [("Vector<T>", "other")], "extend"),
    BuiltinMember("insert", "void", "method", [("int", "idx"), ("T", "val")], "insert"),
    BuiltinMember("contains", "bool", "method", [("T", "val")], "contains"),
    BuiltinMember("indexOf", "int", "method", [("T", "val")], "indexOf"),
    BuiltinMember("lastIndexOf", "int", "method", [("T", "val")], "lastIndexOf"),
    BuiltinMember("count", "int", "method", [("T", "val")], "count"),
    BuiltinMember("removeAll", "void", "method", [("T", "val")], "removeAll"),
    BuiltinMember("distinct", "Vector<T>", "method", [], "distinct"),
    BuiltinMember("sort", "void", "method", [], "sort"),
    BuiltinMember("sorted", "Vector<T>", "method", [], "sorted"),
    BuiltinMember("min", "T", "method", [], "min"),
    BuiltinMember("max", "T", "method", [], "max"),
    BuiltinMember("sum", "T", "method", [], "sum"),
    BuiltinMember("join", "string", "method", [("string", "sep")], "join"),
    BuiltinMember("joinToString", "string", "method", [("string", "sep")], "joinToString"),
    BuiltinMember("filter", "Vector<T>", "method", [("__fn_ptr<bool, T>", "pred")], "filter"),
    BuiltinMember("findIndex", "int", "method", [("__fn_ptr<bool, T>", "pred")], "findIndex"),
    BuiltinMember("forEach", "void", "method", [("__fn_ptr<void, T>", "fn")], "forEach"),
    BuiltinMember("map", "Vector<T>", "method", [("__fn_ptr<T, T>", "fn")], "map"),
    BuiltinMember("any", "bool", "method", [("__fn_ptr<bool, T>", "pred")], "any"),
    BuiltinMember("all", "bool", "method", [("__fn_ptr<bool, T>", "pred")], "all"),
    BuiltinMember("reduce", "T", "method", [("T", "init"), ("__fn_ptr<T, T, T>", "fn")], "reduce"),
    BuiltinMember("copy", "Vector<T>", "method", [], "copy"),
    BuiltinMember("removeAt", "void", "method", [("int", "idx")], "removeAt"),
    BuiltinMember("iterLen", "int", "method", [], "iterLen"),
    BuiltinMember("iterGet", "T", "method", [("int", "i")], "iterGet"),
]

_MEMBER_TABLES: dict[str, list[BuiltinMember]] = {
    "string": STRING_MEMBERS,
    "Array": ARRAY_MEMBERS,
    "ListNode": LISTNODE_MEMBERS,
    "List": LIST_MEMBERS,
    "Map": MAP_MEMBERS,
    "Result": RESULT_MEMBERS,
    "Set": SET_MEMBERS,
    "State": STATE_MEMBERS,
    "Vector": VECTOR_MEMBERS,
}


# ---------------------------------------------------------------------------
# Stdlib static method tables
# ---------------------------------------------------------------------------

# Generated from stdlib .btrc files
STDLIB_STATIC_METHODS: dict[str, list[BuiltinMember]] = {
    "Console": [
        BuiltinMember("log", "void", "method", [("string", "msg")], "log"),
        BuiltinMember("error", "void", "method", [("string", "msg")], "error"),
        BuiltinMember("write", "void", "method", [("string", "msg")], "write"),
        BuiltinMember("writeLine", "void", "method", [("string", "msg")], "writeLine"),
    ],
    "UnixFileSystem": [
        BuiltinMember("chmodPath", "int", "method", [("string", "path"), ("int", "mode")], "chmodPath"),
        BuiltinMember("mkdirPath", "int", "method", [("string", "path"), ("int", "mode")], "mkdirPath"),
        BuiltinMember("mkdirOne", "int", "method", [("string", "path"), ("int", "mode")], "mkdirOne"),
        BuiltinMember("mkdirp", "int", "method", [("string", "path")], "mkdirp"),
        BuiltinMember("removeRecursive", "int", "method", [("string", "path")], "removeRecursive"),
        BuiltinMember("symlinkPath", "int", "method", [("string", "target"), ("string", "linkPath")], "symlinkPath"),
        BuiltinMember("readLink", "string", "method", [("string", "path")], "readLink"),
        BuiltinMember("currentDirectory", "string", "method", [], "currentDirectory"),
        BuiltinMember("realPath", "string", "method", [("string", "path")], "realPath"),
        BuiltinMember("tempDir", "string", "method", [("string", "prefix")], "tempDir"),
    ],
    "PathTools": [
        BuiltinMember("shellQuote", "string", "method", [("string", "raw")], "shellQuote"),
        BuiltinMember("basename", "string", "method", [("string", "path")], "basename"),
        BuiltinMember("dirname", "string", "method", [("string", "path")], "dirname"),
        BuiltinMember("join", "string", "method", [("string", "left"), ("string", "right")], "join"),
        BuiltinMember("absolute", "string", "method", [("string", "path")], "absolute"),
    ],
    "FileSystem": [
        BuiltinMember("exists", "bool", "method", [("string", "path")], "exists"),
        BuiltinMember("isDir", "bool", "method", [("string", "path")], "isDir"),
        BuiltinMember("isFile", "bool", "method", [("string", "path")], "isFile"),
        BuiltinMember("isSymlink", "bool", "method", [("string", "path")], "isSymlink"),
        BuiltinMember("chmod", "int", "method", [("string", "path"), ("int", "mode")], "chmod"),
        BuiltinMember("mkdir", "int", "method", [("string", "path"), ("int", "mode")], "mkdir"),
        BuiltinMember("mkdirp", "int", "method", [("string", "path")], "mkdirp"),
        BuiltinMember("removeRecursive", "int", "method", [("string", "path")], "removeRecursive"),
        BuiltinMember("symlink", "int", "method", [("string", "target"), ("string", "linkPath")], "symlink"),
        BuiltinMember("readLink", "string", "method", [("string", "path")], "readLink"),
        BuiltinMember("currentDirectory", "string", "method", [], "currentDirectory"),
        BuiltinMember("absolutePath", "string", "method", [("string", "path")], "absolutePath"),
        BuiltinMember("tempDir", "string", "method", [("string", "prefix")], "tempDir"),
        BuiltinMember("listDir", "Vector<string>", "method", [("string", "path")], "listDir"),
        BuiltinMember("readText", "string", "method", [("string", "path")], "readText"),
        BuiltinMember("writeText", "void", "method", [("string", "path"), ("string", "content")], "writeText"),
    ],
    "GraphCli": [
        BuiltinMember("args", "Map<string, string>", "method", [("CliArgs", "args"), ("int", "startIndex")], "args"),
        BuiltinMember("targets", "Vector<string>", "method", [("CliArgs", "args"), ("int", "startIndex")], "targets"),
    ],
    "GraphReport": [
        BuiltinMember("list", "void", "method", [("ExecutionGraph", "graph")], "list"),
    ],
    "GraphValidation": [
        BuiltinMember("nodeIds", "Vector<string>", "method", [("ExecutionGraph", "graph")], "nodeIds"),
        BuiltinMember("error", "string", "method", [("ExecutionGraph", "graph")], "error"),
    ],
    "GraphParser": [
        BuiltinMember("node", "GraphNode", "method", [("string", "objectText")], "node"),
        BuiltinMember("readFile", "ExecutionGraph", "method", [("string", "path")], "readFile"),
    ],
    "Browser": [
        BuiltinMember("open", "void", "method", [("string", "url")], "open"),
    ],
    "Path": [
        BuiltinMember("exists", "bool", "method", [("string", "path")], "exists"),
        BuiltinMember("readAll", "string", "method", [("string", "path")], "readAll"),
        BuiltinMember("writeAll", "void", "method", [("string", "path"), ("string", "content")], "writeAll"),
    ],
    "JsonText": [
        BuiltinMember("slice", "string", "method", [("string", "text"), ("int", "start"), ("int", "end")], "slice"),
        BuiltinMember("unescape", "string", "method", [("string", "text")], "unescape"),
        BuiltinMember("stringEnd", "int", "method", [("string", "text"), ("int", "start")], "stringEnd"),
        BuiltinMember("balancedEnd", "int", "method", [("string", "text"), ("int", "start")], "balancedEnd"),
        BuiltinMember("skipSpaces", "int", "method", [("string", "text"), ("int", "i")], "skipSpaces"),
        BuiltinMember("isInt", "bool", "method", [("string", "text")], "isInt"),
        BuiltinMember("keyPosition", "int", "method", [("string", "text"), ("string", "key")], "keyPosition"),
        BuiltinMember("valueStart", "int", "method", [("string", "text"), ("string", "key")], "valueStart"),
        BuiltinMember("parseStringValue", "string", "method", [("string", "text"), ("int", "i"), ("string", "fallback")], "parseStringValue"),
        BuiltinMember("field", "string", "method", [("string", "text"), ("string", "key"), ("string", "fallback")], "field"),
        BuiltinMember("intField", "int", "method", [("string", "text"), ("string", "key"), ("int", "fallback")], "intField"),
        BuiltinMember("objectField", "string", "method", [("string", "text"), ("string", "key")], "objectField"),
        BuiltinMember("objectPath", "string", "method", [("string", "text"), ("Vector<string>", "path")], "objectPath"),
        BuiltinMember("fieldPath", "string", "method", [("string", "text"), ("Vector<string>", "path"), ("string", "fallback")], "fieldPath"),
        BuiltinMember("stringArray", "Vector<string>", "method", [("string", "text"), ("string", "key")], "stringArray"),
        BuiltinMember("objectArray", "Vector<string>", "method", [("string", "text"), ("string", "key")], "objectArray"),
        BuiltinMember("objectMap", "Map<string, string>", "method", [("string", "objectText")], "objectMap"),
        BuiltinMember("argsObject", "Map<string, string>", "method", [("string", "text")], "argsObject"),
        BuiltinMember("expand", "string", "method", [("string", "text"), ("Map<string, string>", "args")], "expand"),
        BuiltinMember("putArgPair", "void", "method", [("Map<string, string>", "result"), ("string", "pair")], "putArgPair"),
    ],
    "Json": [
        BuiltinMember("esc", "string", "method", [("string", "s")], "esc"),
        BuiltinMember("str", "string", "method", [("string", "s")], "str"),
        BuiltinMember("getString", "string", "method", [("string", "json"), ("string", "key")], "getString"),
        BuiltinMember("getStringAfter", "string", "method", [("string", "json"), ("string", "anchor"), ("string", "key")], "getStringAfter"),
        BuiltinMember("getStringFrom", "string", "method", [("string", "json"), ("string", "key"), ("int", "from")], "getStringFrom"),
    ],
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
        BuiltinMember("sum", "int", "method", [("Vector<int>", "items")], "sum"),
        BuiltinMember("fsum", "float", "method", [("Vector<float>", "items")], "fsum"),
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
    "UnixPattern": [
        BuiltinMember("matches", "bool", "method", [("string", "pattern"), ("string", "text")], "matches"),
    ],
    "Pattern": [
        BuiltinMember("matches", "bool", "method", [("string", "pattern"), ("string", "text")], "matches"),
        BuiltinMember("anyMatches", "bool", "method", [("Vector<string>", "patterns"), ("string", "text")], "anyMatches"),
    ],
    "UnixPlatform": [
        BuiltinMember("pid", "int", "method", [], "pid"),
        BuiltinMember("euid", "int", "method", [], "euid"),
    ],
    "Platform": [
        BuiltinMember("isUnix", "bool", "method", [], "isUnix"),
        BuiltinMember("isWindows", "bool", "method", [], "isWindows"),
        BuiltinMember("pathSeparator", "string", "method", [], "pathSeparator"),
        BuiltinMember("pid", "int", "method", [], "pid"),
        BuiltinMember("euid", "int", "method", [], "euid"),
        BuiltinMember("isRoot", "bool", "method", [], "isRoot"),
    ],
    "Environment": [
        BuiltinMember("get", "string", "method", [("string", "name"), ("string", "fallback")], "get"),
        BuiltinMember("has", "bool", "method", [("string", "name")], "has"),
    ],
    "UnixProcess": [
        BuiltinMember("system", "ProcessStatus", "method", [("string", "command")], "system"),
        BuiltinMember("pipe", "UnixPipe", "method", [("string", "command")], "pipe"),
    ],
    "ShellWords": [
        BuiltinMember("isEnvNameStart", "bool", "method", [("char", "c")], "isEnvNameStart"),
        BuiltinMember("isEnvNameChar", "bool", "method", [("char", "c")], "isEnvNameChar"),
        BuiltinMember("isEnvName", "bool", "method", [("string", "name")], "isEnvName"),
        BuiltinMember("isSafeArgChar", "bool", "method", [("char", "c")], "isSafeArgChar"),
        BuiltinMember("isSafeArg", "bool", "method", [("string", "raw")], "isSafeArg"),
        BuiltinMember("quote", "string", "method", [("string", "raw")], "quote"),
        BuiltinMember("redact", "string", "method", [("string", "text"), ("string", "sensitive")], "redact"),
        BuiltinMember("envAssignment", "string", "method", [("string", "item")], "envAssignment"),
    ],
    "CommandOutput": [
        BuiltinMember("collect", "string", "method", [], "collect"),
        BuiltinMember("stream", "string", "method", [], "stream"),
        BuiltinMember("combine", "string", "method", [], "combine"),
        BuiltinMember("suppress", "string", "method", [], "suppress"),
        BuiltinMember("valid", "bool", "method", [("string", "mode")], "valid"),
    ],
    "CommandEnvironment": [
        BuiltinMember("empty", "Vector<string>", "method", [], "empty"),
    ],
    "Strings": [
        BuiltinMember("copy", "string", "method", [("string", "s")], "copy"),
        BuiltinMember("repeat", "string", "method", [("string", "s"), ("int", "count")], "repeat"),
        BuiltinMember("join", "string", "method", [("Vector<string>", "items"), ("string", "sep")], "join"),
        BuiltinMember("replace", "string", "method", [("string", "s"), ("string", "old"), ("string", "replacement")], "replace"),
        BuiltinMember("split", "Vector<string>", "method", [("string", "s"), ("string", "delim")], "split"),
        BuiltinMember("isDigit", "bool", "method", [("char", "c")], "isDigit"),
        BuiltinMember("isAlpha", "bool", "method", [("char", "c")], "isAlpha"),
        BuiltinMember("isAlnum", "bool", "method", [("char", "c")], "isAlnum"),
        BuiltinMember("isSpace", "bool", "method", [("char", "c")], "isSpace"),
        BuiltinMember("toInt", "int", "method", [("string", "s")], "toInt"),
        BuiltinMember("toFloat", "float", "method", [("string", "s")], "toFloat"),
        BuiltinMember("count", "int", "method", [("string", "s"), ("string", "sub")], "count"),
        BuiltinMember("find", "int", "method", [("string", "s"), ("string", "sub"), ("int", "start")], "find"),
        BuiltinMember("rfind", "int", "method", [("string", "s"), ("string", "sub")], "rfind"),
        BuiltinMember("compare", "int", "method", [("string", "left"), ("string", "right")], "compare"),
        BuiltinMember("lessThan", "bool", "method", [("string", "left"), ("string", "right")], "lessThan"),
        BuiltinMember("capitalize", "string", "method", [("string", "s")], "capitalize"),
        BuiltinMember("title", "string", "method", [("string", "s")], "title"),
        BuiltinMember("swapCase", "string", "method", [("string", "s")], "swapCase"),
        BuiltinMember("padLeft", "string", "method", [("string", "s"), ("int", "width"), ("char", "fill")], "padLeft"),
        BuiltinMember("padRight", "string", "method", [("string", "s"), ("int", "width"), ("char", "fill")], "padRight"),
        BuiltinMember("center", "string", "method", [("string", "s"), ("int", "width"), ("char", "fill")], "center"),
        BuiltinMember("lstrip", "string", "method", [("string", "s")], "lstrip"),
        BuiltinMember("rstrip", "string", "method", [("string", "s")], "rstrip"),
        BuiltinMember("removePrefix", "string", "method", [("string", "s"), ("string", "prefix")], "removePrefix"),
        BuiltinMember("fromInt", "string", "method", [("int", "n")], "fromInt"),
        BuiltinMember("fromFloat", "string", "method", [("float", "f")], "fromFloat"),
        BuiltinMember("isDigitStr", "bool", "method", [("string", "s")], "isDigitStr"),
        BuiltinMember("isAlphaStr", "bool", "method", [("string", "s")], "isAlphaStr"),
        BuiltinMember("isBlank", "bool", "method", [("string", "s")], "isBlank"),
    ],
    "Terminal": [
        BuiltinMember("readLine", "string", "method", [], "readLine"),
        BuiltinMember("prompt", "string", "method", [("string", "label")], "prompt"),
        BuiltinMember("promptPassword", "string", "method", [("string", "label")], "promptPassword"),
    ],
    "UnixPamPassword": [
        BuiltinMember("change", "bool", "method", [("string", "user"), ("string", "oldPassword"), ("string", "newPassword")], "change"),
    ],
    "Toml": [
        BuiltinMember("stripInlineComment", "string", "method", [("string", "raw")], "stripInlineComment"),
        BuiltinMember("unquote", "string", "method", [("string", "raw")], "unquote"),
        BuiltinMember("key", "string", "method", [("string", "line")], "key"),
        BuiltinMember("value", "string", "method", [("string", "line")], "value"),
        BuiltinMember("sectionName", "string", "method", [("string", "line")], "sectionName"),
        BuiltinMember("tableArrayName", "string", "method", [("string", "line")], "tableArrayName"),
        BuiltinMember("rootMap", "Map<string, string>", "method", [("string", "content")], "rootMap"),
        BuiltinMember("sectionMap", "Map<string, string>", "method", [("string", "content"), ("string", "section")], "sectionMap"),
        BuiltinMember("tableArrayBlocks", "Vector<Map<string, string>>", "method", [("string", "content"), ("string", "table")], "tableArrayBlocks"),
    ],
    "Html": [
        BuiltinMember("escape", "string", "method", [("string", "raw")], "escape"),
    ],
    "LinuxUiBuilder": [
        BuiltinMember("html", "HtmlUiBackend", "method", [], "html"),
        BuiltinMember("native", "NativeUiBackend", "method", [], "native"),
    ],
    "MacUiBuilder": [
        BuiltinMember("html", "HtmlUiBackend", "method", [], "html"),
        BuiltinMember("native", "NativeUiBackend", "method", [], "native"),
    ],
    "WindowsUiBuilder": [
        BuiltinMember("html", "HtmlUiBackend", "method", [], "html"),
        BuiltinMember("native", "NativeUiBackend", "method", [], "native"),
    ],
    "Ui": [
        BuiltinMember("node", "UiNode", "method", [("string", "tag")], "node"),
        BuiltinMember("text", "UiNode", "method", [("string", "value")], "text"),
        BuiltinMember("rawHtml", "UiNode", "method", [("string", "value")], "rawHtml"),
        BuiltinMember("div", "UiNode", "method", [], "div"),
        BuiltinMember("button", "UiNode", "method", [("string", "label")], "button"),
        BuiltinMember("input", "UiNode", "method", [("string", "name"), ("string", "value")], "input"),
        BuiltinMember("document", "UiDocument", "method", [("string", "title"), ("UiNode", "body")], "document"),
    ],
    "NativeUi": [
        BuiltinMember("applescriptString", "string", "method", [("string", "raw")], "applescriptString"),
        BuiltinMember("detect", "NativeUiBackend", "method", [], "detect"),
    ],
    "UiRuntime": [
        BuiltinMember("runCommandAsync", "Thread<int>", "method", [("Command", "command")], "runCommandAsync"),
        BuiltinMember("notifyAsync", "Thread<int>", "method", [("NativeUiBackend", "backend"), ("string", "title"), ("string", "body")], "notifyAsync"),
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
    "range": ("Vector<int>", [("int", "n")]),
    "exit": ("void", [("int", "code")]),
}


# ---------------------------------------------------------------------------
# Accessor functions
# ---------------------------------------------------------------------------


def get_members_for_type(type_name: str) -> list[BuiltinMember]:
    """Return the list of built-in members for a type, or empty list."""
    return _MEMBER_TABLES.get(base_type_name(type_name), [])


def base_type_name(type_name: str) -> str:
    """Return the member-table owner name for a possibly generic type."""
    raw = type_name.strip()
    while raw.endswith("?") or raw.endswith("*"):
        raw = raw[:-1].strip()
    depth = 0
    for index, char in enumerate(raw):
        if char == "<":
            if depth == 0:
                return raw[:index].strip()
            depth += 1
        elif char == ">":
            depth -= 1
    return raw


def get_member(type_name: str, member_name: str) -> Optional[BuiltinMember]:
    """Look up a specific member on a built-in type."""
    for m in get_members_for_type(type_name):
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
