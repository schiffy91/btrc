"""Enum lowering: EnumDecl, RichEnumDecl → structured IR nodes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import EnumDecl, RichEnumDecl
from ..nodes import (
    CType,
    IRAssign,
    IRBlock,
    IRCase,
    IREnumDef,
    IREnumValue,
    IRFieldAccess,
    IRFunctionDef,
    IRLiteral,
    IRParam,
    IRReturn,
    IRStructField,
    IRSwitch,
    IRTaggedUnionDef,
    IRTaggedUnionVariant,
    IRVar,
    IRVarDecl,
)
from .parameters import lower_source_param, source_binding_c_name
from .types import type_to_c

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
    """Emit a simple enum and, for named enums, its toString helper."""
    # Build enum definition
    values = []
    prior_members = set()
    for v in decl.values:
        if v.value is not None:
            from .expressions import lower_expr

            previous_owner = getattr(gen, "_enum_lowering_owner", None)
            previous_members = getattr(gen, "_enum_lowering_members", None)
            gen._enum_lowering_owner = decl.name or ""
            gen._enum_lowering_members = frozenset(prior_members)
            try:
                lowered_value = lower_expr(gen, v.value)
            finally:
                gen._enum_lowering_owner = previous_owner
                gen._enum_lowering_members = previous_members
            values.append(
                IREnumValue(
                    name=_enum_value_name(decl.name, v.name),
                    value=lowered_value,
                )
            )
        else:
            values.append(
                IREnumValue(
                    name=_enum_value_name(decl.name, v.name),
                    value=None,
                )
            )
        prior_members.add(v.name)
    gen.module.enum_defs.append(IREnumDef(name=decl.name or None, values=values))

    if not decl.name:
        return

    # Generate toString function as IRFunctionDef
    cases = [
        IRCase(value=IRVar(name=f"{decl.name}_{v.name}"), body=[IRReturn(value=IRLiteral(text=f'"{v.name}"'))])
        for v in decl.values
    ]
    cases.append(IRCase(value=None, body=[IRReturn(value=IRLiteral(text='"unknown"'))]))

    gen.module.function_defs.append(
        IRFunctionDef(
            name=f"{decl.name}_toString",
            return_type=CType(text="const char*"),
            params=[IRParam(c_type=CType(text=decl.name), name="val")],
            is_static=True,
            body=IRBlock(
                stmts=[
                    IRSwitch(value=IRVar(name="val"), cases=cases),
                ]
            ),
        )
    )


def _enum_value_name(enum_name: str, value_name: str) -> str:
    return f"{enum_name}_{value_name}" if enum_name else value_name


def _emit_rich_enum(gen: IRGenerator, decl: RichEnumDecl):
    """Emit a rich enum as tag IREnumDef + data structs + tagged union + ctors."""
    name = decl.name

    # Tag enum → IREnumDef
    tag_values = [
        IREnumValue(
            name=f"{name}_{v.name}_TAG",
            value=IRLiteral(text=str(i)),
        )
        for i, v in enumerate(decl.variants)
    ]
    gen.module.enum_defs.append(IREnumDef(name=f"{name}_Tag", values=tag_values))

    variants = [
        IRTaggedUnionVariant(
            name=variant.name,
            fields=[
                IRStructField(
                    c_type=CType(text=type_to_c(param.type)),
                    name=source_binding_c_name(param.name),
                )
                for param in variant.params
            ],
        )
        for variant in decl.variants
    ]
    gen.module.tagged_union_defs.append(
        IRTaggedUnionDef(
            name=name,
            tag_type=CType(text=f"{name}_Tag"),
            variants=variants,
        )
    )

    # Constructor functions → IRFunctionDef
    for v in decl.variants:
        if v.params:
            params = [lower_source_param(parameter, analyzed=gen.analyzed) for parameter in v.params]
            body_stmts = [
                IRVarDecl(c_type=CType(text=name), name="__result", init=None),
                IRAssign(
                    target=IRFieldAccess(obj=IRVar(name="__result"), field="tag", arrow=False),
                    value=IRVar(name=f"{name}_{v.name}_TAG"),
                ),
            ]
            for p in v.params:
                body_stmts.append(
                    IRAssign(
                        target=IRFieldAccess(
                            obj=IRFieldAccess(
                                obj=IRFieldAccess(obj=IRVar(name="__result"), field="data", arrow=False),
                                field=v.name,
                                arrow=False,
                            ),
                            field=source_binding_c_name(p.name),
                            arrow=False,
                        ),
                        value=IRVar(name=source_binding_c_name(p.name, gen.analyzed)),
                    )
                )
            body_stmts.append(IRReturn(value=IRVar(name="__result")))
        else:
            params = []
            body_stmts = [
                IRVarDecl(c_type=CType(text=name), name="__result", init=None),
                IRAssign(
                    target=IRFieldAccess(obj=IRVar(name="__result"), field="tag", arrow=False),
                    value=IRVar(name=f"{name}_{v.name}_TAG"),
                ),
                IRReturn(value=IRVar(name="__result")),
            ]

        gen.module.function_defs.append(
            IRFunctionDef(
                name=f"{name}_{v.name}",
                return_type=CType(text=name),
                params=params,
                is_static=True,
                body=IRBlock(stmts=body_stmts),
            )
        )

    # Generate toString function as IRFunctionDef
    cases = [
        IRCase(value=IRVar(name=f"{name}_{v.name}_TAG"), body=[IRReturn(value=IRLiteral(text=f'"{v.name}"'))])
        for v in decl.variants
    ]
    cases.append(IRCase(value=None, body=[IRReturn(value=IRLiteral(text='"unknown"'))]))

    gen.module.function_defs.append(
        IRFunctionDef(
            name=f"{name}_toString",
            return_type=CType(text="const char*"),
            params=[IRParam(c_type=CType(text=name), name="val")],
            is_static=True,
            body=IRBlock(
                stmts=[
                    IRSwitch(value=IRFieldAccess(obj=IRVar(name="val"), field="tag", arrow=False), cases=cases),
                ]
            ),
        )
    )
