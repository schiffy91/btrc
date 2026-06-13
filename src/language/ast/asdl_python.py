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

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from asdl_parser import Constructor, Field, Module, Type, parse_file

# ASDL built-in types -> Python type mapping
_BUILTIN_MAP = {
    "identifier": "str",
    "string": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
}

# Positional / provenance field names. These never participate in __eq__
# (compare=False) so two nodes that differ only in source location compare
# equal — see asdl_python task notes. They always carry a default so existing
# construction sites that omit them keep working.
_POSITION_FIELDS = frozenset({"line", "col", "name_line", "name_col"})
_PROVENANCE_FIELDS = frozenset({"source_file"})


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


# Scalar defaults for required built-in-typed fields. These are honest
# (an int field really does default to 0) and are relied on by many
# synthetic-node construction sites, so they are retained.
_SCALAR_DEFAULTS = {
    "str": '""',
    "int": "0",
    "float": "0.0",
    "bool": "False",
}


def _field_line(field: Field, name_map: dict[str, str]) -> str:
    """Emit a single dataclass field declaration: ``name: type[= default]``.

    Required *node-typed* fields (non-opt, non-seq, not a built-in) get NO
    default: a ``= None`` there is a lie — the node is mandatory, not optional.
    The dataclass uses ``kw_only=True`` (every site constructs nodes with
    keyword args), so omitting a default never triggers a field-ordering error
    even when an optional field precedes a required one.

    Required *built-in-typed* fields (int/str/float/bool) keep their honest
    scalar default (0/""/0.0/False).

    Optional ``field?`` keeps ``= None``; sequences ``field*`` keep
    ``default_factory=list``.

    Positional fields (line/col/name_line/name_col) and provenance fields
    (source_file) always carry a default and ``compare=False`` so source
    locations and file provenance never participate in equality.
    """
    py_t = _py_type(field, name_map)
    decl = f"{field.name}: {py_t}"

    if field.name in _POSITION_FIELDS:
        return f"{decl} = _dc_field(default=0, compare=False)"
    if field.name in _PROVENANCE_FIELDS:
        return f"{decl} = _dc_field(default=None, compare=False)"

    if field.seq:
        return f"{decl} = _dc_field(default_factory=list)"
    if field.opt:
        return f"{decl} = None"

    # Required field. Built-in scalars keep an honest default; node-typed
    # required fields get no default to preserve "required" semantics.
    base = name_map.get(field.type, field.type)
    if base in _SCALAR_DEFAULTS:
        return f"{decl} = {_SCALAR_DEFAULTS[base]}"
    return decl


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
    lines.append("")
    # Import field under an alias: a constructor field may legitimately be
    # named "field" (e.g. FieldAccessExpr.field), which would shadow the
    # dataclasses.field helper inside that class body.
    lines.append("from dataclasses import dataclass")
    lines.append("from dataclasses import field as _dc_field")
    lines.append("from typing import Optional, Union")

    # Categorize types
    all_constructors: list[tuple[Constructor, list[Field], Type]] = []
    sum_types: list[Type] = []
    product_types: list[Type] = []
    simple_enums: list[Type] = []

    for t in module.types:
        if _is_simple_enum(t):
            simple_enums.append(t)
        elif _is_sum_type(t):
            sum_types.append(t)
            for c in t.constructors:
                all_constructors.append((c, t.attributes, t))
        else:
            product_types.append(t)
            c = t.constructors[0]
            all_constructors.append((c, t.attributes, t))

    # Emit simple enums (string constants), each block separated by a blank line.
    for t in simple_enums:
        lines.append("")
        lines.append(f"# --- {t.name} (string constants) ---")
        lines.append("")
        for c in t.constructors:
            lines.append(f'{c.name} = "{c.name}"')

    # Emit dataclasses. PEP 8 wants two blank lines before each top-level class;
    # the join below inserts exactly that boundary between consecutive blocks.
    for constructor, attrs, _parent_type in all_constructors:
        lines.append("")
        lines.append("")
        lines.append("@dataclass(kw_only=True)")
        lines.append(f"class {constructor.name}:")

        all_fields = constructor.fields + attrs
        if not all_fields:
            lines.append("    pass")
        else:
            for f in constructor.fields:
                lines.append(f"    {_field_line(f, name_map)}")
            for af in attrs:
                lines.append(f"    {_field_line(af, name_map)}")

    # Emit Union type aliases for sum types.
    lines.append("")
    lines.append("")
    lines.append("# --- Union type aliases for sum types ---")
    lines.append("")
    for t in sum_types:
        names = [c.name for c in t.constructors]
        lines.append(f"{t.name} = Union[{', '.join(names)}]")

    # Emit product type aliases (lowercase ASDL name -> class name).
    lines.append("")
    lines.append("")
    lines.append("# --- Product type aliases ---")
    lines.append("# These alias lowercase ASDL names to the PascalCase class names")
    lines.append("")
    for t in product_types:
        cls_name = t.constructors[0].name
        if t.name != cls_name:
            lines.append(f"{t.name} = {cls_name}")

    # Single trailing newline.
    return "\n".join(lines) + "\n"


def main():
    if len(sys.argv) < 2:
        print("Usage: asdl_python.py <ast.asdl>", file=sys.stderr)
        sys.exit(1)

    module = parse_file(sys.argv[1])
    print(generate(module))


if __name__ == "__main__":
    main()
