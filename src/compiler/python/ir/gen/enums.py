"""Enum lowering: EnumDecl, RichEnumDecl → structured IR nodes."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import EnumDecl, RichEnumDecl
from ..nodes import (
    CType, IRAssign, IRBlock, IRCase, IREnumDef, IREnumValue,
    IRFieldAccess, IRFunctionDef, IRLiteral, IRParam, IRReturn,
    IRStructDef, IRStructField, IRSwitch, IRVar, IRVarDecl,
)

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
    """Emit a simple enum as IREnumDef + toString IRFunctionDef."""
    # Build enum definition
    values = []
    for i, v in enumerate(decl.values):
        if v.value is not None:
            from .expressions import lower_expr
            from .statements import _quick_text
            val_text = _quick_text(lower_expr(gen, v.value))
            values.append(IREnumValue(
                name=f"{decl.name}_{v.name}", value=val_text))
        else:
            values.append(IREnumValue(
                name=f"{decl.name}_{v.name}", value=str(i)))
    gen.module.enum_defs.append(IREnumDef(name=decl.name, values=values))

    # Generate toString function as IRFunctionDef
    cases = [
        IRCase(
            value=IRLiteral(text=f"{decl.name}_{v.name}"),
            body=[IRReturn(value=IRLiteral(text=f'"{v.name}"'))])
        for v in decl.values
    ]
    cases.append(IRCase(
        value=None,
        body=[IRReturn(value=IRLiteral(text='"unknown"'))]))

    gen.module.function_defs.append(IRFunctionDef(
        name=f"{decl.name}_toString",
        return_type=CType(text="const char*"),
        params=[IRParam(c_type=CType(text=decl.name), name="val")],
        is_static=True,
        body=IRBlock(stmts=[
            IRSwitch(value=IRVar(name="val"), cases=cases),
        ]),
    ))


def _emit_rich_enum(gen: IRGenerator, decl: RichEnumDecl):
    """Emit a rich enum as tag IREnumDef + data structs + tagged union + ctors."""
    name = decl.name

    # Tag enum → IREnumDef
    tag_values = [
        IREnumValue(name=f"{name}_{v.name}_TAG", value=str(i))
        for i, v in enumerate(decl.variants)
    ]
    gen.module.enum_defs.append(IREnumDef(
        name=f"{name}_Tag", values=tag_values))

    # Data structs for each variant with parameters → IRStructDef + typedef
    for v in decl.variants:
        if v.params:
            from .types import type_to_c
            struct_name = f"{name}_{v.name}_Data"
            gen.module.forward_decls.append(
                f"typedef struct {struct_name} {struct_name};")
            fields = [
                IRStructField(c_type=CType(text=type_to_c(p.type)), name=p.name)
                for p in v.params
            ]
            gen.module.struct_defs.append(IRStructDef(
                name=struct_name, fields=fields))

    # Main struct with tag + union → raw_sections
    # (IRStructDef doesn't support unions; keep as raw C text)
    union_fields = []
    for v in decl.variants:
        if v.params:
            union_fields.append(
                f"        {name}_{v.name}_Data {v.name};")
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

    # Constructor functions → IRFunctionDef
    for v in decl.variants:
        from .types import type_to_c
        if v.params:
            params = [
                IRParam(c_type=CType(text=type_to_c(p.type)), name=p.name)
                for p in v.params
            ]
            body_stmts = [
                IRVarDecl(c_type=CType(text=name), name="c", init=None),
                IRAssign(
                    target=IRFieldAccess(
                        obj=IRVar(name="c"), field="tag", arrow=False),
                    value=IRLiteral(text=f"{name}_{v.name}_TAG")),
            ]
            for p in v.params:
                body_stmts.append(IRAssign(
                    target=IRFieldAccess(
                        obj=IRFieldAccess(
                            obj=IRFieldAccess(
                                obj=IRVar(name="c"),
                                field="data", arrow=False),
                            field=v.name, arrow=False),
                        field=p.name, arrow=False),
                    value=IRVar(name=p.name)))
            body_stmts.append(IRReturn(value=IRVar(name="c")))
        else:
            params = []
            body_stmts = [
                IRVarDecl(c_type=CType(text=name), name="c", init=None),
                IRAssign(
                    target=IRFieldAccess(
                        obj=IRVar(name="c"), field="tag", arrow=False),
                    value=IRLiteral(text=f"{name}_{v.name}_TAG")),
                IRReturn(value=IRVar(name="c")),
            ]

        gen.module.function_defs.append(IRFunctionDef(
            name=f"{name}_{v.name}",
            return_type=CType(text=name),
            params=params,
            is_static=True,
            body=IRBlock(stmts=body_stmts),
        ))

    # Generate toString function as IRFunctionDef
    cases = [
        IRCase(
            value=IRLiteral(text=f"{name}_{v.name}_TAG"),
            body=[IRReturn(value=IRLiteral(text=f'"{v.name}"'))])
        for v in decl.variants
    ]
    cases.append(IRCase(
        value=None,
        body=[IRReturn(value=IRLiteral(text='"unknown"'))]))

    gen.module.function_defs.append(IRFunctionDef(
        name=f"{name}_toString",
        return_type=CType(text="const char*"),
        params=[IRParam(c_type=CType(text=name), name="val")],
        is_static=True,
        body=IRBlock(stmts=[
            IRSwitch(
                value=IRFieldAccess(
                    obj=IRVar(name="val"), field="tag", arrow=False),
                cases=cases),
        ]),
    ))
