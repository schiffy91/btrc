"""Cohesive declarations IR lowering owner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.compiler.python.analyzer.storage import StorageModel
from src.compiler.python.ir.nodes import (
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
from src.compiler.python.syntax.ast.generated import EnumDecl, RichEnumDecl

from .calls import CallableProvenance, CallableSignatureLowerer
from .types import CTypeLowerer

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalyzedProgram

    from .expressions import ExpressionLowerer
    from .session import LoweringSession


class DeclarationLowerer:
    """Own declarations lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        signatures: CallableSignatureLowerer,
        expressions: ExpressionLowerer,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._signatures = signatures
        self._expressions = expressions

    def lower_declaration(self, declaration):
        if isinstance(declaration, EnumDecl):
            return self._emit_enum(
                declaration,
            )
        if isinstance(declaration, RichEnumDecl):
            return self._emit_rich_enum(
                declaration,
            )
        return None

    def emit_enum_decls(self):
        """Emit all enum declarations."""
        for decl in self._analyzed.program.declarations:
            if isinstance(decl, EnumDecl):
                self._emit_enum(
                    decl,
                )
            elif isinstance(decl, RichEnumDecl):
                self._emit_rich_enum(
                    decl,
                )

    def _emit_enum(self, decl: EnumDecl):
        """Emit a simple enum and, for named enums, its toString helper."""
        provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
        values = []
        prior_members = set()
        for v in decl.values:
            if v.value is not None:
                with self._session.enum_values(
                    decl.name or "",
                    frozenset(prior_members),
                ):
                    lowered_value = self._expressions.lower_expression(v.value, provenance)
                values.append(
                    IREnumValue(name=DeclarationLowerer._enum_value_name(decl.name, v.name), value=lowered_value)
                )
            else:
                values.append(IREnumValue(name=DeclarationLowerer._enum_value_name(decl.name, v.name), value=None))
            prior_members.add(v.name)
        self._session.module.enum_defs.append(IREnumDef(name=decl.name or None, values=values))
        if not decl.name:
            return
        cases = [
            IRCase(value=IRVar(name=f"{decl.name}_{v.name}"), body=[IRReturn(value=IRLiteral(text=f'"{v.name}"'))])
            for v in decl.values
        ]
        cases.append(IRCase(value=None, body=[IRReturn(value=IRLiteral(text='"unknown"'))]))
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=f"{decl.name}_toString",
                return_type=CType(text="const char*"),
                params=[IRParam(c_type=CType(text=decl.name), name="val")],
                is_static=True,
                body=IRBlock(stmts=[IRSwitch(value=IRVar(name="val"), cases=cases)]),
            )
        )

    @staticmethod
    def _enum_value_name(enum_name: str, value_name: str) -> str:
        return f"{enum_name}_{value_name}" if enum_name else value_name

    def _emit_rich_enum(self, decl: RichEnumDecl):
        """Emit a rich enum as tag IREnumDef + data structs + tagged union + ctors."""
        name = decl.name
        tag_values = [
            IREnumValue(name=f"{name}_{v.name}_TAG", value=IRLiteral(text=str(i))) for i, v in enumerate(decl.variants)
        ]
        self._session.module.enum_defs.append(IREnumDef(name=f"{name}_Tag", values=tag_values))
        variants = [
            IRTaggedUnionVariant(
                name=variant.name,
                fields=[
                    IRStructField(
                        c_type=CType(text=self._types.render(param.type)),
                        # A payload member lives in C's member namespace, so it
                        # keeps its source spelling even when that shadows a
                        # type: `payload.data.Some.Item` must name this field.
                        name=param.name,
                        is_volatile=bool(param.type and param.type.is_volatile),
                        effective_is_volatile=StorageModel.effective_outer_volatile(
                            param.type, self._analyzed.typedef_table
                        ),
                    )
                    for param in variant.params
                ],
            )
            for variant in decl.variants
        ]
        self._session.module.tagged_union_defs.append(
            IRTaggedUnionDef(name=name, tag_type=CType(text=f"{name}_Tag"), variants=variants)
        )
        for v in decl.variants:
            provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
            if v.params:
                params = [provenance.lower_source_param(parameter) for parameter in v.params]
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
                                field=p.name,
                                arrow=False,
                            ),
                            value=IRVar(name=provenance.source_binding_c_name(p.name)),
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
            self._session.module.function_defs.append(
                IRFunctionDef(
                    name=f"{name}_{v.name}",
                    return_type=CType(text=name),
                    params=params,
                    is_static=True,
                    body=IRBlock(stmts=body_stmts),
                )
            )
        cases = [
            IRCase(value=IRVar(name=f"{name}_{v.name}_TAG"), body=[IRReturn(value=IRLiteral(text=f'"{v.name}"'))])
            for v in decl.variants
        ]
        cases.append(IRCase(value=None, body=[IRReturn(value=IRLiteral(text='"unknown"'))]))
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=f"{name}_toString",
                return_type=CType(text="const char*"),
                params=[IRParam(c_type=CType(text=name), name="val")],
                is_static=True,
                body=IRBlock(
                    stmts=[IRSwitch(value=IRFieldAccess(obj=IRVar(name="val"), field="tag", arrow=False), cases=cases)]
                ),
            )
        )
