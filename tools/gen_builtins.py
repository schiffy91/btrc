#!/usr/bin/env python3
"""Generate src/devex/lsp/builtins.py from stdlib .btrc source files.

Parses each stdlib .btrc file using the compiler's lexer and parser,
walks the AST to extract class declarations (fields, methods, properties),
and generates the builtins module used by the LSP for completion, hover,
and signature help.

String instance methods are language intrinsics (not defined in any .btrc
file — they're lowered to C helpers in the IR gen) and are defined inline
in the INTRINSIC_STRING_MEMBERS table below.

Usage: python tools/gen_builtins.py
"""

import os
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.compiler.python.lexer import Lexer
from src.compiler.python.parser import Parser
from src.compiler.python.ast_nodes import (
    ClassDecl,
    FieldDecl,
    MethodDecl,
    PropertyDecl,
    TypeExpr,
)

STDLIB_DIR = os.path.join(ROOT, "src", "stdlib")
OUTPUT = os.path.join(ROOT, "src", "devex", "lsp", "builtins.py")

# ---------------------------------------------------------------------------
# Which stdlib classes map to which builtin category
# ---------------------------------------------------------------------------

# Collection types → instance member tables (for dot-completion on variables)
COLLECTION_FILES = {
    "list.btrc": ["List"],
    "map.btrc": ["Map"],
    "set.btrc": ["Set"],
}

# Classes with only static (class) methods → STDLIB_STATIC_METHODS
STATIC_CLASS_FILES = {
    "math.btrc": ["Math"],
    "strings.btrc": ["Strings"],
    "io.btrc": ["Path"],
    "console.btrc": ["Console"],
}

# ---------------------------------------------------------------------------
# String instance methods — language intrinsics (not in any .btrc file)
# ---------------------------------------------------------------------------

INTRINSIC_STRING_MEMBERS = [
    ("len", "int", "field", [], "Length of the string (bytes)"),
    ("charAt", "char", "method", [("int", "index")], "Character at index"),
    ("trim", "string", "method", [], "Remove leading/trailing whitespace"),
    ("lstrip", "string", "method", [], "Remove leading whitespace"),
    ("rstrip", "string", "method", [], "Remove trailing whitespace"),
    ("toUpper", "string", "method", [], "Convert to uppercase"),
    ("toLower", "string", "method", [], "Convert to lowercase"),
    ("contains", "bool", "method", [("string", "sub")], "Check if contains substring"),
    ("startsWith", "bool", "method", [("string", "prefix")], "Check prefix"),
    ("endsWith", "bool", "method", [("string", "suffix")], "Check suffix"),
    ("indexOf", "int", "method", [("string", "sub")], "Index of first occurrence"),
    (
        "lastIndexOf",
        "int",
        "method",
        [("string", "sub")],
        "Index of last occurrence",
    ),
    (
        "substring",
        "string",
        "method",
        [("int", "start"), ("int", "end")],
        "Extract substring",
    ),
    ("equals", "bool", "method", [("string", "other")], "Compare strings"),
    ("split", "List<string>", "method", [("string", "delim")], "Split into list"),
    (
        "replace",
        "string",
        "method",
        [("string", "old"), ("string", "replacement")],
        "Replace occurrences",
    ),
    ("repeat", "string", "method", [("int", "count")], "Repeat N times"),
    (
        "count",
        "int",
        "method",
        [("string", "sub")],
        "Count non-overlapping occurrences",
    ),
    (
        "find",
        "int",
        "method",
        [("string", "sub"), ("int", "start")],
        "Find from start index",
    ),
    ("capitalize", "string", "method", [], "Uppercase first char"),
    ("title", "string", "method", [], "Capitalize each word"),
    ("swapCase", "string", "method", [], "Swap upper/lower case"),
    (
        "padLeft",
        "string",
        "method",
        [("int", "width"), ("char", "fill")],
        "Left-pad",
    ),
    (
        "padRight",
        "string",
        "method",
        [("int", "width"), ("char", "fill")],
        "Right-pad",
    ),
    (
        "center",
        "string",
        "method",
        [("int", "width"), ("char", "fill")],
        "Center with padding",
    ),
    ("charLen", "int", "method", [], "UTF-8 character count"),
    ("byteLen", "int", "method", [], "Byte length"),
    ("isDigitStr", "bool", "method", [], "All chars are digits"),
    ("isAlphaStr", "bool", "method", [], "All chars are alphabetic"),
    ("isBlank", "bool", "method", [], "Empty or all whitespace"),
    ("isAlnum", "bool", "method", [], "All chars are alphanumeric"),
    ("isUpper", "bool", "method", [], "All chars are uppercase"),
    ("isLower", "bool", "method", [], "All chars are lowercase"),
    ("reverse", "string", "method", [], "Reverse the string"),
    ("isEmpty", "bool", "method", [], "True if string is empty"),
    (
        "removePrefix",
        "string",
        "method",
        [("string", "prefix")],
        "Remove prefix if present",
    ),
    (
        "removeSuffix",
        "string",
        "method",
        [("string", "suffix")],
        "Remove suffix if present",
    ),
    ("toInt", "int", "method", [], "Parse as integer"),
    ("toFloat", "float", "method", [], "Parse as float"),
    ("toDouble", "double", "method", [], "Parse as double"),
    ("toLong", "long", "method", [], "Parse as long"),
    (
        "toBool",
        "bool",
        "method",
        [],
        'Parse as bool (false for empty, "false", "0")',
    ),
    (
        "zfill",
        "string",
        "method",
        [("int", "width")],
        "Left-pad with zeros (preserves sign)",
    ),
]

# ---------------------------------------------------------------------------
# Collection IR-gen intrinsics (higher-order methods not in stdlib .btrc files)
# These are lowered to C helper templates in ir/helpers/collections.py
# ---------------------------------------------------------------------------

INTRINSIC_COLLECTION_MEMBERS: dict[str, list[tuple]] = {
    "List": [
        ("forEach", "void", "method", [("fn", "callback")], "Call fn for each element"),
        ("filter", "List<T>", "method", [("fn", "predicate")], "Filter by predicate"),
        ("any", "bool", "method", [("fn", "predicate")], "True if any element matches"),
        ("all", "bool", "method", [("fn", "predicate")], "True if all elements match"),
        (
            "findIndex",
            "int",
            "method",
            [("fn", "predicate")],
            "Index of first match, -1 if not found",
        ),
        ("map", "List<T>", "method", [("fn", "transform")], "Apply fn to each element"),
        (
            "reduce",
            "T",
            "method",
            [("T", "init"), ("fn", "accumulator")],
            "Fold list into single value",
        ),
    ],
    "Map": [
        (
            "forEach",
            "void",
            "method",
            [("fn", "callback")],
            "Call fn(key, value) for each entry",
        ),
        (
            "containsValue",
            "bool",
            "method",
            [("V", "value")],
            "Check if any entry has the value",
        ),
    ],
    "Set": [
        (
            "forEach",
            "void",
            "method",
            [("fn", "callback")],
            "Call fn(element) for each element",
        ),
        (
            "filter",
            "Set<T>",
            "method",
            [("fn", "predicate")],
            "New set of elements matching predicate",
        ),
        (
            "any",
            "bool",
            "method",
            [("fn", "predicate")],
            "True if any element matches predicate",
        ),
        (
            "all",
            "bool",
            "method",
            [("fn", "predicate")],
            "True if all elements match predicate",
        ),
    ],
}

# ---------------------------------------------------------------------------
# Built-in free function signatures — language intrinsics
# ---------------------------------------------------------------------------

# Implementation fields/methods to hide from LSP (internal to the stdlib)
# These are public in the .btrc source but not part of the user-facing API.
_HIDDEN_FIELDS = {
    "List": {"data", "cap"},
    "Map": {"keys", "values", "occupied", "cap"},
    "Set": {"keys", "occupied", "cap"},
}
_HIDDEN_METHODS = {
    "Map": {"resize"},
    "Set": {"resize"},
}

INTRINSIC_FUNCTIONS = {
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
# AST helpers
# ---------------------------------------------------------------------------


def type_repr(t: TypeExpr) -> str:
    """Convert a TypeExpr AST node to its string representation."""
    if t is None:
        return "void"
    result = t.base
    if t.generic_args:
        args = ", ".join(type_repr(a) for a in t.generic_args)
        result += f"<{args}>"
    if t.pointer_depth > 0:
        result += "*" * t.pointer_depth
    return result


def parse_file(filename: str) -> dict[str, ClassDecl]:
    """Parse a .btrc file and return {class_name: ClassDecl}."""
    path = os.path.join(STDLIB_DIR, filename)
    with open(path) as f:
        source = f.read()
    tokens = Lexer(source, filename).tokenize()
    program = Parser(tokens).parse()
    return {d.name: d for d in program.declarations if isinstance(d, ClassDecl)}


def extract_members(
    cls: ClassDecl,
) -> tuple[list[tuple], list[tuple]]:
    """Extract (fields, methods) from a ClassDecl.

    Filters out implementation details listed in _HIDDEN_FIELDS/_HIDDEN_METHODS.

    Returns:
        fields: [(name, type_str)]
        methods: [(name, return_type, [(param_type, param_name), ...], is_static)]
    """
    hidden_f = _HIDDEN_FIELDS.get(cls.name, set())
    hidden_m = _HIDDEN_METHODS.get(cls.name, set())
    fields = []
    methods = []
    for member in cls.members:
        if isinstance(member, FieldDecl) and member.access == "public":
            if member.name not in hidden_f:
                fields.append((member.name, type_repr(member.type)))
        elif isinstance(member, MethodDecl):
            # Skip constructors (same name as class), destructors, internal helpers
            if member.name == cls.name or member.name.startswith("__"):
                continue
            if member.access not in ("public", "class"):
                continue
            if member.name in hidden_m:
                continue
            params = [(type_repr(p.type), p.name) for p in member.params]
            is_static = member.access == "class"
            methods.append(
                (member.name, type_repr(member.return_type), params, is_static)
            )
        elif isinstance(member, PropertyDecl) and member.access == "public":
            if member.name not in hidden_f:
                fields.append((member.name, type_repr(member.type)))
    return fields, methods


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


def fmt_params(params: list[tuple]) -> str:
    """Format a parameter list as Python source."""
    if not params:
        return "[]"
    items = ", ".join(f'("{pt}", "{pn}")' for pt, pn in params)
    return f"[{items}]"


def generate_collection_members(
    var_name: str,
    fields: list[tuple],
    methods: list[tuple],
    intrinsics: list[tuple],
) -> str:
    """Generate a Python list of BuiltinMember for a collection type.

    Combines stdlib-parsed members with IR-gen intrinsic methods.
    """
    lines = [f"{var_name}: list[BuiltinMember] = ["]
    for name, type_str in fields:
        lines.append(
            f'    BuiltinMember("{name}", "{type_str}", "field", doc="{name}"),',
        )
    for name, ret, params, _is_static in methods:
        lines.append(
            f'    BuiltinMember("{name}", "{ret}", "method", '
            f'{fmt_params(params)}, "{name}"),',
        )
    # IR-gen intrinsic methods (forEach, filter, etc.)
    for name, ret, _kind, params, doc in intrinsics:
        doc_escaped = doc.replace('"', '\\"')
        lines.append(
            f'    BuiltinMember("{name}", "{ret}", "method", '
            f'{fmt_params(params)}, "{doc_escaped}"),',
        )
    lines.append("]")
    return "\n".join(lines)


def generate_intrinsic_members(var_name: str, entries: list[tuple]) -> str:
    """Generate a Python list of BuiltinMember from intrinsic tuples."""
    lines = [f"{var_name}: list[BuiltinMember] = ["]
    for entry in entries:
        name, ret, kind, params, doc = entry
        doc_escaped = doc.replace('"', '\\"')
        lines.append(
            f'    BuiltinMember("{name}", "{ret}", "{kind}", '
            f'{fmt_params(params)}, "{doc_escaped}"),',
        )
    lines.append("]")
    return "\n".join(lines)


def generate_static_methods(class_name: str, methods: list[tuple]) -> str:
    """Generate entries for STDLIB_STATIC_METHODS."""
    lines = [f'    "{class_name}": [']
    for name, ret, params, _is_static in methods:
        lines.append(
            f'        BuiltinMember("{name}", "{ret}", "method", '
            f'{fmt_params(params)}, "{name}"),',
        )
    lines.append("    ],")
    return "\n".join(lines)


def main():
    # --- Parse collection types ---
    collection_data = {}  # {type_base: (fields, methods)}
    for filename, class_names in COLLECTION_FILES.items():
        classes = parse_file(filename)
        for cname in class_names:
            if cname not in classes:
                print(f"Warning: {cname} not found in {filename}", file=sys.stderr)
                continue
            fields, methods = extract_members(classes[cname])
            # Only include instance methods (not static) for collection members
            instance_methods = [m for m in methods if not m[3]]
            collection_data[cname] = (fields, instance_methods)

    # --- Parse static classes ---
    static_data = {}  # {class_name: methods}
    for filename, class_names in STATIC_CLASS_FILES.items():
        classes = parse_file(filename)
        for cname in class_names:
            if cname not in classes:
                print(f"Warning: {cname} not found in {filename}", file=sys.stderr)
                continue
            _fields, methods = extract_members(classes[cname])
            static_data[cname] = methods

    # --- Generate output ---
    out = []
    out.append('"""Single source of truth for built-in type members in the btrc language.')
    out.append("")
    out.append("Auto-generated from stdlib .btrc files by tools/gen_builtins.py.")
    out.append("DO NOT EDIT BY HAND — edit the stdlib source or the generator instead.")
    out.append("")
    out.append("Used by completion, hover, and signature help providers to avoid")
    out.append("maintaining separate (and inevitably divergent) copies of the same data.")
    out.append('"""')
    out.append("")
    out.append("from __future__ import annotations")
    out.append("")
    out.append("from dataclasses import dataclass, field")
    out.append("from typing import Optional")
    out.append("")
    out.append("")

    # BuiltinMember dataclass
    out.append("@dataclass")
    out.append("class BuiltinMember:")
    out.append('    """One member (field or method) of a built-in type."""')
    out.append("")
    out.append("    name: str")
    out.append("    return_type: str")
    out.append('    kind: str  # "field" or "method"')
    out.append(
        '    params: list[tuple[str, str]] = field(default_factory=list)  # [(type, name)]'
    )
    out.append('    doc: str = ""')
    out.append("")
    out.append("")

    # Separator
    out.append("# " + "-" * 75)
    out.append("# Built-in type member tables")
    out.append("# " + "-" * 75)
    out.append("")

    # String intrinsics
    out.append("# String methods are language intrinsics (not defined in any .btrc file)")
    out.append(generate_intrinsic_members("STRING_MEMBERS", INTRINSIC_STRING_MEMBERS))
    out.append("")

    # Collection types from stdlib + IR-gen intrinsics
    for type_name, (fields, methods) in collection_data.items():
        var_name = f"{type_name.upper()}_MEMBERS"
        out.append(f"# Generated from src/stdlib/{type_name.lower()}.btrc")
        intrinsics = INTRINSIC_COLLECTION_MEMBERS.get(type_name, [])
        out.append(
            generate_collection_members(var_name, fields, methods, intrinsics)
        )
        out.append("")

    # Member table lookup
    out.append("_MEMBER_TABLES: dict[str, list[BuiltinMember]] = {")
    out.append('    "string": STRING_MEMBERS,')
    for type_name in collection_data:
        out.append(f'    "{type_name}": {type_name.upper()}_MEMBERS,')
    out.append("}")
    out.append("")
    out.append("")

    # Separator
    out.append("# " + "-" * 75)
    out.append("# Stdlib static method tables")
    out.append("# " + "-" * 75)
    out.append("")

    # Static methods from stdlib
    out.append("# Generated from stdlib .btrc files")
    out.append("STDLIB_STATIC_METHODS: dict[str, list[BuiltinMember]] = {")
    for class_name, methods in static_data.items():
        out.append(generate_static_methods(class_name, methods))
    out.append("}")
    out.append("")

    # Built-in function signatures
    out.append(
        "# Built-in free function signatures: "
        "name -> (return_type, [(param_type, param_name)])"
    )
    out.append(
        "BUILTIN_FUNCTION_SIGNATURES: dict[str, tuple[str, list[tuple[str, str]]]] = {"
    )
    for fname, (ret, params) in INTRINSIC_FUNCTIONS.items():
        out.append(f'    "{fname}": ("{ret}", {fmt_params(params)}),')
    out.append("}")
    out.append("")
    out.append("")

    # Separator
    out.append("# " + "-" * 75)
    out.append("# Accessor functions")
    out.append("# " + "-" * 75)
    out.append("")
    out.append("")

    # Accessor functions (these are generic code, not data)
    out.append(
        textwrap.dedent("""\
        def get_members_for_type(type_name: str) -> list[BuiltinMember]:
            \"\"\"Return the list of built-in members for a type, or empty list.\"\"\"
            return _MEMBER_TABLES.get(type_name, [])


        def get_member(type_name: str, member_name: str) -> Optional[BuiltinMember]:
            \"\"\"Look up a specific member on a built-in type.\"\"\"
            for m in _MEMBER_TABLES.get(type_name, []):
                if m.name == member_name:
                    return m
            return None


        def get_hover_markdown(type_name: str, member_name: str) -> Optional[str]:
            \"\"\"Generate a markdown hover string for a built-in type member.\"\"\"
            m = get_member(type_name, member_name)
            if m is None:
                return None
            if m.kind == "field":
                return f"```btrc\\n{m.return_type} {m.name}\\n```\\n{m.doc}"
            params_str = ", ".join(f"{pt} {pn}" for pt, pn in m.params)
            return f"```btrc\\n{m.return_type} {m.name}({params_str})\\n```\\n{m.doc}"


        def get_signature_params(
            type_name: str, method_name: str
        ) -> Optional[list[tuple[str, str]]]:
            \"\"\"Return the parameter list for a built-in type method, or None.\"\"\"
            m = get_member(type_name, method_name)
            if m is None or m.kind == "field":
                return None
            return m.params


        def get_stdlib_methods(class_name: str) -> Optional[list[BuiltinMember]]:
            \"\"\"Return the list of static methods for a stdlib class, or None.\"\"\"
            return STDLIB_STATIC_METHODS.get(class_name)


        def get_stdlib_signature(
            class_name: str, method_name: str
        ) -> Optional[list[tuple[str, str]]]:
            \"\"\"Return the parameter list for a stdlib static method, or None.\"\"\"
            methods = STDLIB_STATIC_METHODS.get(class_name)
            if methods is None:
                return None
            for m in methods:
                if m.name == method_name:
                    return m.params
            return None
    """)
    )

    # Write output
    content = "\n".join(out)
    with open(OUTPUT, "w") as f:
        f.write(content)
    print(f"Generated {OUTPUT}")

    # Print summary
    print(f"  STRING_MEMBERS: {len(INTRINSIC_STRING_MEMBERS)} members (intrinsic)")
    for type_name, (fields, methods) in collection_data.items():
        print(
            f"  {type_name.upper()}_MEMBERS: {len(fields)} fields + "
            f"{len(methods)} methods (from stdlib)"
        )
    for class_name, methods in static_data.items():
        print(f"  STDLIB_STATIC_METHODS[{class_name}]: {len(methods)} methods (from stdlib)")
    print(f"  BUILTIN_FUNCTION_SIGNATURES: {len(INTRINSIC_FUNCTIONS)} functions (intrinsic)")


if __name__ == "__main__":
    main()
