"""Enum lowering: EnumDecl, RichEnumDecl → C enums and tagged unions."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import EnumDecl, RichEnumDecl
from ..nodes import IRStructDef, IRStructField, CType

if TYPE_CHECKING:
    from .generator import IRGenerator


def emit_enum_decls(gen: IRGenerator):
    """Emit all enum declarations."""
    for decl in gen.analyzed.program.declarations:
        if isinstance(decl, EnumDecl):
            _emit_enum(gen, decl)
        elif isinstance(decl, RichEnumDecl):
            _emit_rich_enum(gen, decl)


def _emit_enum(gen: IRGenerator, decl: EnumDecl):
    """Emit a simple enum as a C enum + toString function."""
    values = []
    for i, v in enumerate(decl.values):
        if v.value is not None:
            from .expressions import lower_expr
            val_text = _expr_text(lower_expr(gen, v.value))
            values.append(f"    {decl.name}_{v.name} = {val_text}")
        else:
            values.append(f"    {decl.name}_{v.name} = {i}")
    body = ",\n".join(values)
    gen.module.raw_sections.append(f"typedef enum {{\n{body}\n}} {decl.name};")

    # Generate toString function
    cases = []
    for v in decl.values:
        cases.append(f'        case {decl.name}_{v.name}: return "{v.name}";')
    cases_text = "\n".join(cases)
    gen.module.raw_sections.append(
        f"static const char* {decl.name}_toString({decl.name} val) {{\n"
        f"    switch (val) {{\n{cases_text}\n"
        f'        default: return "unknown";\n'
        f"    }}\n}}")


def _emit_rich_enum(gen: IRGenerator, decl: RichEnumDecl):
    """Emit a rich enum as a tagged union."""
    name = decl.name

    # Tag enum
    tag_values = [f"    {name}_{v.name}_TAG = {i}" for i, v in enumerate(decl.variants)]
    tag_body = ",\n".join(tag_values)
    gen.module.raw_sections.append(f"typedef enum {{\n{tag_body}\n}} {name}_Tag;")

    # Data structs for each variant with parameters
    for v in decl.variants:
        if v.params:
            fields = []
            for p in v.params:
                from .types import type_to_c
                fields.append(f"    {type_to_c(p.type)} {p.name};")
            field_text = "\n".join(fields)
            gen.module.raw_sections.append(
                f"typedef struct {{\n{field_text}\n}} {name}_{v.name}_Data;")

    # Main struct with tag + union
    union_fields = []
    for v in decl.variants:
        if v.params:
            union_fields.append(f"        {name}_{v.name}_Data {v.name};")
    if union_fields:
        union_text = "\n".join(union_fields)
        gen.module.raw_sections.append(
            f"typedef struct {{\n"
            f"    {name}_Tag tag;\n"
            f"    union {{\n{union_text}\n    }} data;\n"
            f"}} {name};")
    else:
        gen.module.raw_sections.append(
            f"typedef struct {{\n    {name}_Tag tag;\n}} {name};")

    # Constructor functions for each variant
    for v in decl.variants:
        from .types import type_to_c
        if v.params:
            params = [f"{type_to_c(p.type)} {p.name}" for p in v.params]
            assigns = [f"    c.data.{v.name}.{p.name} = {p.name};" for p in v.params]
            gen.module.raw_sections.append(
                f"static {name} {name}_{v.name}({', '.join(params)}) {{\n"
                f"    {name} c; c.tag = {name}_{v.name}_TAG;\n"
                f"{''.join(a + chr(10) for a in assigns)}"
                f"    return c;\n}}")
        else:
            gen.module.raw_sections.append(
                f"static {name} {name}_{v.name}(void) {{\n"
                f"    {name} c; c.tag = {name}_{v.name}_TAG;\n"
                f"    return c;\n}}")

    # Generate toString function
    cases = []
    for v in decl.variants:
        cases.append(f'        case {name}_{v.name}_TAG: return "{v.name}";')
    cases_text = "\n".join(cases)
    gen.module.raw_sections.append(
        f"static const char* {name}_toString({name} val) {{\n"
        f"    switch (val.tag) {{\n{cases_text}\n"
        f'        default: return "unknown";\n'
        f"    }}\n}}")


def _expr_text(expr) -> str:
    from ..nodes import IRLiteral, IRVar, IRRawExpr
    if isinstance(expr, IRLiteral):
        return expr.text
    if isinstance(expr, IRVar):
        return expr.name
    if isinstance(expr, IRRawExpr):
        return expr.text
    return "0"
