#!/usr/bin/env python3
"""Generate btrc AST node definitions from an ASDL specification.

Usage:
    python3 src/compiler/python/ast/asdl_btrc.py src/language/ast.asdl > generated.btrc

Produces:
    - enum NodeKind with a value for each constructor
    - A base btrc class per ASDL sum type (e.g. ``class Expr {}``)
    - A btrc class for each constructor (extends its sum-type base, if any)
    - A node_kind_name() helper for kind -> name dispatch

Design notes
------------
btrc has no native sum/union types, so each ASDL sum type (``expr``, ``stmt``,
...) becomes an empty base class (PascalCase of the ASDL name: ``expr`` ->
``Expr``). Every constructor of that sum extends the base, and a field typed by
the sum is emitted with the base-class type. btrc classes are reference types,
so a base-class-typed field can hold any subclass instance. Product types map
to their single constructor class, exactly as asdl_python does.

Field names that collide with a btrc keyword (read through the grammar
repository, the same source tokens.py uses -- never hardcoded) are
deterministically renamed by appending an underscore: ``default`` -> ``default_``,
``keep`` -> ``keep_``. The rename is applied consistently to field declarations
and to the constructor's initialiser statements.

Semantics divergence (for the record, out of scope here): asdl_python represents
optional ``field?`` as Python ``None``, whereas this generator uses btrc
sentinels (``-1`` for int, ``false`` for bool, ``""`` for string, ``null`` for
class types). A self-hosting compiler must reconcile this; the present task only
requires the emitted btrc to PARSE.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from asdl_parser import Constructor, Field, Module, Type, parse_file

# ASDL built-in types -> btrc type mapping
_BUILTIN_MAP = {
    "identifier": "string",
    "string": "string",
    "int": "int",
    "float": "float",
    "bool": "bool",
}


def _btrc_keywords() -> set[str]:
    """btrc reserved keywords, from the grammar (single source of truth).

    Imported lazily so this module stays usable even if invoked from a working
    directory where the compiler package is not on sys.path until call time.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here))))
    if root not in sys.path:
        sys.path.insert(0, root)
    from src.compiler.python.ebnf import GrammarRepository

    return set(GrammarRepository.canonical().load().keywords)


_KEYWORDS = _btrc_keywords()


def _safe_name(name: str) -> str:
    """Rename a field whose name collides with a btrc keyword.

    Deterministic: append a single underscore (``default`` -> ``default_``).
    Applied identically wherever the field name appears.
    """
    return f"{name}_" if name in _KEYWORDS else name


def _to_pascal(name: str) -> str:
    """snake_case ASDL type name -> PascalCase class name.

    e.g. type_expr -> TypeExpr, if_else -> IfElse, expr -> Expr.
    """
    return "".join(part[:1].upper() + part[1:] for part in name.split("_"))


def _is_sum_type(t: Type) -> bool:
    return len(t.constructors) > 1


def _is_simple_enum(t: Type) -> bool:
    return _is_sum_type(t) and all(len(c.fields) == 0 for c in t.constructors)


def _build_type_name_map(module: Module) -> dict[str, str]:
    """ASDL type name -> btrc type name used in field declarations.

    - Built-ins: identifier/string -> string, int -> int, etc.
    - Simple enums: stored as int kind values -> "int".
    - Sum types: the generated base class (PascalCase of the ASDL name).
    - Product types: the single constructor's class name.
    """
    name_map = dict(_BUILTIN_MAP)
    for t in module.types:
        if _is_simple_enum(t):
            name_map[t.name] = "int"
        elif _is_sum_type(t):
            name_map[t.name] = _to_pascal(t.name)
        else:
            name_map[t.name] = t.constructors[0].name
    return name_map


def _btrc_type(field: Field, name_map: dict[str, str]) -> str:
    """Convert an ASDL field to a btrc type."""
    base = name_map.get(field.type, field.type)
    if field.seq:
        return f"List<{base}>"
    return base


def _btrc_default(field: Field, name_map: dict[str, str]) -> str:
    """btrc default value for a field (see semantics-divergence note above)."""
    base = name_map.get(field.type, field.type)
    if field.seq:
        return "[]"
    if field.opt:
        return {"int": "-1", "float": "0.0", "bool": "false", "string": '""'}.get(base, "null")
    return {"string": '""', "int": "0", "float": "0.0", "bool": "false"}.get(base, "null")


def _to_screaming_snake(name: str) -> str:
    """PascalCase -> SCREAMING_SNAKE_CASE.

    e.g. BinaryExpr -> BINARY_EXPR, FStringLiteral -> F_STRING_LITERAL"""
    result = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            prev = name[i - 1]
            if prev.islower() or prev.isdigit() or (i + 1 < len(name) and name[i + 1].islower() and prev.isupper()):
                result.append("_")
        result.append(ch.upper())
    return "".join(result)


def _emit_node_kind_enum(module: Module, lines: list[str]) -> list[tuple[Constructor, list[Field], Type]]:
    """Emit the NodeKind enum and return (constructor, attrs, type) tuples."""
    all_constructors: list[tuple[Constructor, list[Field], Type]] = []
    lines.append("enum NodeKind {")
    lines.append("    NK_NONE = 0,")
    for t in module.types:
        if _is_simple_enum(t):
            continue
        for c in t.constructors:
            lines.append(f"    NK_{_to_screaming_snake(c.name)},")
            all_constructors.append((c, t.attributes, t))
    lines.append("};")
    lines.append("")
    return all_constructors


def _emit_simple_enums(module: Module, lines: list[str]) -> None:
    for t in module.types:
        if not _is_simple_enum(t):
            continue
        lines.append(f"enum {_to_pascal(t.name)} {{")
        for i, c in enumerate(t.constructors):
            comma = "," if i < len(t.constructors) - 1 else ""
            lines.append(f"    {_to_screaming_snake(c.name)} = {i}{comma}")
        lines.append("};")
        lines.append("")


def _emit_base_classes(module: Module, lines: list[str]) -> None:
    """Emit an empty base class per (non-enum) sum type, so sum-typed fields
    have a real btrc class backing them."""
    for t in module.types:
        if _is_sum_type(t) and not _is_simple_enum(t):
            lines.append(f"class {_to_pascal(t.name)} {{}}")
    lines.append("")


def _emit_constructor_class(
    constructor: Constructor,
    attrs: list[Field],
    parent: Type,
    name_map: dict[str, str],
    lines: list[str],
) -> None:
    is_sum = _is_sum_type(parent) and not _is_simple_enum(parent)
    extends = f" extends {_to_pascal(parent.name)}" if is_sum else ""
    lines.append(f"class {constructor.name}{extends} {{")
    lines.append("    public int kind;")
    for f in constructor.fields + attrs:
        lines.append(f"    public {_btrc_type(f, name_map)} {_safe_name(f.name)};")
    lines.append("")

    # Constructor: positional params come from the sum/product attributes.
    params = ", ".join(f"{_btrc_type(af, name_map)} {_safe_name(af.name)}" for af in attrs)
    lines.append(f"    public {constructor.name}({params}) {{")
    lines.append(f"        self.kind = NK_{_to_screaming_snake(constructor.name)};")
    for f in constructor.fields:
        lines.append(f"        self.{_safe_name(f.name)} = {_btrc_default(f, name_map)};")
    for af in attrs:
        lines.append(f"        self.{_safe_name(af.name)} = {_safe_name(af.name)};")
    lines.append("    }")
    lines.append("}")
    lines.append("")


def generate(module: Module) -> str:
    """Generate btrc source code from an ASDL module."""
    name_map = _build_type_name_map(module)
    lines: list[str] = [
        "/* btrc AST node definitions.",
        " *",
        " * Auto-generated from src/language/ast.asdl by src/compiler/python/ast/asdl_btrc.py.",
        " * DO NOT EDIT BY HAND.",
        " */",
        "",
    ]

    all_constructors = _emit_node_kind_enum(module, lines)
    _emit_simple_enums(module, lines)
    _emit_base_classes(module, lines)

    for constructor, attrs, parent in all_constructors:
        _emit_constructor_class(constructor, attrs, parent, name_map, lines)

    lines.append("string node_kind_name(int kind) {")
    lines.append("    switch (kind) {")
    for constructor, _attrs, _t in all_constructors:
        kind_name = f"NK_{_to_screaming_snake(constructor.name)}"
        lines.append(f'        case {kind_name}: return "{constructor.name}";')
    lines.append('        default: return "Unknown";')
    lines.append("    }")
    lines.append("}")
    lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: asdl_btrc.py <ast.asdl>", file=sys.stderr)
        sys.exit(1)
    module = parse_file(sys.argv[1])
    print(generate(module))


if __name__ == "__main__":
    main()
