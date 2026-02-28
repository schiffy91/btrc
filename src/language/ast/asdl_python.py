#!/usr/bin/env python3
"""Generate Python AST node definitions from an ASDL specification.

Usage:
    python3 src/language/ast/asdl_python.py src/language/ast/ast.asdl > src/compiler/python/ast_nodes.py

Produces:
    - @dataclass for each constructor (product type or sum variant)
    - Union type aliases for sum types
    - Aliases for product types (type_expr = TypeExpr, etc.)
    - A NodeVisitor base class with visit_* methods
"""

from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from asdl_parser import parse_file, Module, Type, Constructor, Field


# ASDL built-in types -> Python type mapping
_BUILTIN_MAP = {
    "identifier": "str",
    "string": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
}


def _is_sum_type(t: Type) -> bool:
    return len(t.constructors) > 1


def _is_simple_enum(t: Type) -> bool:
    return _is_sum_type(t) and all(len(c.fields) == 0 for c in t.constructors)


def _build_type_name_map(module: Module) -> dict[str, str]:
    """Build mapping from ASDL type name -> Python annotation type name.

    - Built-in types: "identifier" -> "str", "int" -> "int", etc.
    - Sum types: "decl" -> "decl" (will be a Union alias)
    - Product types: "type_expr" -> "TypeExpr" (use constructor class name)
    - Simple enums: "access_level" -> "str" (stored as string constants)
    """
    name_map = dict(_BUILTIN_MAP)
    for t in module.types:
        if _is_simple_enum(t):
            name_map[t.name] = "str"
        elif _is_sum_type(t):
            # Sum type: use ASDL name (will be a Union alias)
            name_map[t.name] = t.name
        else:
            # Product type: use constructor class name
            name_map[t.name] = t.constructors[0].name
    return name_map


def _py_type(field: Field, name_map: dict[str, str]) -> str:
    """Convert an ASDL field to a Python type annotation."""
    base = name_map.get(field.type, field.type)
    if field.seq:
        return f"list[{base}]"
    elif field.opt:
        return f"Optional[{base}]"
    return base


def _py_default(field: Field, name_map: dict[str, str]) -> str:
    """Get the default value for a field."""
    if field.seq:
        return "field(default_factory=list)"
    elif field.opt:
        return "None"
    base = name_map.get(field.type, field.type)
    defaults = {
        "str": '""',
        "int": "0",
        "float": "0.0",
        "bool": "False",
    }
    return defaults.get(base, "None")


def generate(module: Module) -> str:
    """Generate Python source code from an ASDL module."""
    lines: list[str] = []
    name_map = _build_type_name_map(module)

    # Header
    lines.append('"""AST node definitions for the btrc language.')
    lines.append("")
    lines.append("Auto-generated from src/language/ast/ast.asdl by src/language/ast/asdl_python.py.")
    lines.append("DO NOT EDIT BY HAND.")
    lines.append('"""')
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("from dataclasses import dataclass, field")
    lines.append("from typing import Optional, Union")
    lines.append("")
    lines.append("")

    # Categorize types
    all_constructors: list[tuple[Constructor, list[Field], Type]] = []
    sum_types: list[Type] = []
    product_types: list[Type] = []

    for t in module.types:
        if _is_simple_enum(t):
            lines.append(f"# --- {t.name} (string constants) ---")
            lines.append("")
            for c in t.constructors:
                lines.append(f'{c.name} = "{c.name}"')
            lines.append("")
        elif _is_sum_type(t):
            sum_types.append(t)
            for c in t.constructors:
                all_constructors.append((c, t.attributes, t))
        else:
            product_types.append(t)
            c = t.constructors[0]
            all_constructors.append((c, t.attributes, t))

    # Emit dataclasses
    for constructor, attrs, parent_type in all_constructors:
        lines.append("")
        lines.append("@dataclass")
        lines.append(f"class {constructor.name}:")

        all_fields = constructor.fields + attrs
        if not all_fields:
            if attrs:
                for af in attrs:
                    py_t = _py_type(af, name_map)
                    default = _py_default(af, name_map)
                    lines.append(f"    {af.name}: {py_t} = {default}")
            else:
                lines.append("    pass")
        else:
            for f in constructor.fields:
                py_t = _py_type(f, name_map)
                default = _py_default(f, name_map)
                lines.append(f"    {f.name}: {py_t} = {default}")
            for af in attrs:
                py_t = _py_type(af, name_map)
                default = _py_default(af, name_map)
                lines.append(f"    {af.name}: {py_t} = {default}")

    lines.append("")
    lines.append("")

    # Emit Union type aliases for sum types
    lines.append("# --- Union type aliases for sum types ---")
    lines.append("")
    for t in sum_types:
        names = [c.name for c in t.constructors]
        lines.append(f"{t.name} = Union[{', '.join(names)}]")
    lines.append("")

    # Emit product type aliases (lowercase ASDL name -> class name)
    lines.append("")
    lines.append("# --- Product type aliases ---")
    lines.append("# These alias lowercase ASDL names to the PascalCase class names")
    lines.append("")
    for t in product_types:
        cls_name = t.constructors[0].name
        if t.name != cls_name:
            lines.append(f"{t.name} = {cls_name}")
    lines.append("")

    # Emit NodeVisitor
    lines.append("")
    lines.append("# --- Visitor ---")
    lines.append("")
    lines.append("class NodeVisitor:")
    lines.append(
        '    """Base class for AST visitors. Override visit_* methods."""')
    lines.append("")
    lines.append("    def visit(self, node):")
    lines.append('        method = f"visit_{type(node).__name__}"')
    lines.append("        visitor = getattr(self, method, self.generic_visit)")
    lines.append("        return visitor(node)")
    lines.append("")
    lines.append("    def generic_visit(self, node):")
    lines.append("        pass")
    lines.append("")

    for constructor, _attrs, _parent in all_constructors:
        lines.append(
            f"    def visit_{constructor.name}"
            f"(self, node: {constructor.name}):")
        lines.append("        return self.generic_visit(node)")
        lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: asdl_python.py <ast.asdl>", file=sys.stderr)
        sys.exit(1)

    module = parse_file(sys.argv[1])
    print(generate(module))


if __name__ == "__main__":
    main()
