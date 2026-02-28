#!/usr/bin/env python3
"""Generate btrc AST node definitions from an ASDL specification.

Usage:
    python3 spec/ast/asdl_btrc.py spec/ast/ast.asdl > src/compiler/btrc/ast_nodes.btrc

Produces:
    - enum NodeKind with a value for each constructor
    - A btrc class for each constructor (with typed fields)
    - Helper functions for node kind dispatch
"""

from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from asdl_parser import parse_file, Module, Type, Constructor, Field


# ASDL built-in types -> btrc type mapping
_TYPE_MAP = {
    "identifier": "string",
    "string": "string",
    "int": "int",
    "float": "float",
    "bool": "bool",
}


def _btrc_type(field: Field) -> str:
    """Convert an ASDL field to a btrc type."""
    base = _TYPE_MAP.get(field.type, field.type)
    if field.seq:
        return f"List<{base}>"
    elif field.opt:
        # btrc doesn't have Option<T>; use pointer or sentinel
        # For class types, null pointer works. For primitives, use -1 sentinel.
        if base in ("int", "float", "bool"):
            return base  # caller checks sentinel
        return f"{base}"  # nullable pointer
    return base


def _btrc_default(field: Field) -> str:
    """Get the btrc default value for a field."""
    base = _TYPE_MAP.get(field.type, field.type)
    if field.seq:
        return "[]"
    elif field.opt:
        if base == "int":
            return "-1"
        elif base == "float":
            return "0.0"
        elif base == "bool":
            return "false"
        elif base == "string":
            return '""'
        return "null"
    else:
        defaults = {
            "string": '""',
            "int": "0",
            "float": "0.0",
            "bool": "false",
        }
        return defaults.get(base, "null")


def _is_sum_type(t: Type) -> bool:
    return len(t.constructors) > 1


def _is_simple_enum(t: Type) -> bool:
    return _is_sum_type(t) and all(len(c.fields) == 0 for c in t.constructors)


def generate(module: Module) -> str:
    """Generate btrc source code from an ASDL module."""
    lines: list[str] = []

    lines.append("/* btrc AST node definitions.")
    lines.append(" *")
    lines.append(" * Auto-generated from spec/ast/ast.asdl by spec/ast/asdl_btrc.py.")
    lines.append(" * DO NOT EDIT BY HAND.")
    lines.append(" */")
    lines.append("")

    # Collect all constructors
    all_constructors: list[tuple[Constructor, list[Field], Type]] = []

    # Emit NodeKind enum
    lines.append("enum NodeKind {")
    lines.append("    NK_NONE = 0,")
    kind_names: list[str] = []
    for t in module.types:
        if _is_simple_enum(t):
            continue  # these get their own enums
        for c in t.constructors:
            kind_name = f"NK_{_to_screaming_snake(c.name)}"
            kind_names.append(kind_name)
            lines.append(f"    {kind_name},")
            all_constructors.append((c, t.attributes, t))
    lines.append("};")
    lines.append("")

    # Emit simple enums
    for t in module.types:
        if _is_simple_enum(t):
            lines.append(f"enum {t.name} {{")
            for i, c in enumerate(t.constructors):
                comma = "," if i < len(t.constructors) - 1 else ""
                lines.append(
                    f"    {_to_screaming_snake(c.name)} = {i}{comma}")
            lines.append("};")
            lines.append("")

    # Emit class for each constructor
    for constructor, attrs, parent_type in all_constructors:
        all_fields = constructor.fields + attrs
        lines.append(f"class {constructor.name} {{")
        lines.append(f"    public int kind;")
        for f in all_fields:
            bt = _btrc_type(f)
            default = _btrc_default(f)
            lines.append(f"    public {bt} {f.name};")
        lines.append("")
        # Constructor
        param_strs = []
        init_strs = []
        for af in attrs:
            param_strs.append(f"{_btrc_type(af)} {af.name}")
            init_strs.append(f"        self.{af.name} = {af.name};")
        kind_name = f"NK_{_to_screaming_snake(constructor.name)}"
        lines.append(
            f"    public {constructor.name}"
            f"({', '.join(param_strs)}) {{")
        lines.append(f"        self.kind = {kind_name};")
        for f in constructor.fields:
            default = _btrc_default(f)
            lines.append(f"        self.{f.name} = {default};")
        for init in init_strs:
            lines.append(init)
        lines.append("    }")
        lines.append("}")
        lines.append("")

    # Emit kind_name helper function
    lines.append("string node_kind_name(int kind) {")
    lines.append('    switch (kind) {')
    for constructor, _attrs, _t in all_constructors:
        kind_name = f"NK_{_to_screaming_snake(constructor.name)}"
        lines.append(
            f'        case {kind_name}: return "{constructor.name}";')
    lines.append('        default: return "Unknown";')
    lines.append("    }")
    lines.append("}")
    lines.append("")

    return "\n".join(lines)


def _to_screaming_snake(name: str) -> str:
    """Convert PascalCase to SCREAMING_SNAKE_CASE.
    e.g. BinaryExpr -> BINARY_EXPR, FStringLiteral -> F_STRING_LITERAL"""
    result = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            prev = name[i - 1]
            if prev.islower() or prev.isdigit():
                result.append("_")
            elif (i + 1 < len(name) and name[i + 1].islower()
                  and prev.isupper()):
                result.append("_")
        result.append(ch.upper())
    return "".join(result)


def main():
    if len(sys.argv) < 2:
        print("Usage: asdl_btrc.py <ast.asdl>", file=sys.stderr)
        sys.exit(1)

    module = parse_file(sys.argv[1])
    print(generate(module))


if __name__ == "__main__":
    main()
