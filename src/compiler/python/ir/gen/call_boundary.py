"""Structured full-call ownership sequencing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..nodes import (
    CType,
    IRBinOp,
    IRCast,
    IRCommaExpr,
    IRLiteral,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)


@dataclass(frozen=True)
class CallOperand:
    """One source operand evaluated before invoking a managed call."""

    node: object
    type_expr: object
    c_type: str
    keep: bool = False
    pin: bool = False
    owned: bool = False
    transferred: bool = False
    lowered: object | None = None
    lower_with_overrides: Callable[[dict[int, object]], object] | None = None


class CallBoundaryLowerer:
    """Sequence call operands and their ARC lifetime transitions."""

    def __init__(self, context, lifetime) -> None:
        self.context = context
        self.lifetime = lifetime

    def sequence(
        self,
        operands: list[CallOperand],
        *,
        lower_expr: Callable,
        build_call: Callable,
        result_c_type: str | None,
        result_type=None,
        opaque_result: bool = False,
        opaque_result_site=None,
        promote_result: bool = False,
        activate_cleanup: Callable[[], None] | None = None,
        result_owned: bool = False,
    ):
        """Evaluate operands once, invoke, then release call-owned values."""
        if self.context.is_unevaluated:
            values = {id(operand.node): self._lower_operand(operand, {}, lower_expr) for operand in operands}
            return build_call(values)

        declarations = []
        prefix = []
        handoffs = []
        suffix = []
        overrides = {}
        for operand in operands:
            declaration = self._temporary(
                "__btrc_call_operand",
                operand.c_type,
            )
            declarations.append(declaration)
            value = IRVar(name=declaration.name)
            prefix.append(
                IRBinOp(
                    left=value,
                    op="=",
                    right=self._lower_operand(operand, overrides, lower_expr),
                )
            )
            if operand.owned:
                self.lifetime.protect_temporary(
                    declaration,
                    operand.type_expr,
                    declarations,
                    prefix,
                    "__btrc_call_operand_cleanup",
                    activate_cleanup=activate_cleanup,
                )
            if operand.keep or operand.pin:
                retained_decl = self._temporary(
                    "__btrc_kept_operand",
                    operand.c_type,
                )
                declarations.append(retained_decl)
                retained = IRVar(name=retained_decl.name)
                prefix.extend(
                    [
                        self.lifetime.retain_value(value, operand.type_expr),
                        IRBinOp(left=retained, op="=", right=value),
                    ]
                )
                self.lifetime.protect_temporary(
                    retained_decl,
                    operand.type_expr,
                    declarations,
                    prefix,
                    "__btrc_kept_operand_cleanup",
                    activate_cleanup=activate_cleanup,
                )
                suffix.extend(
                    self.lifetime.release_and_clear(
                        retained,
                        operand.type_expr,
                        declarations,
                        operand.c_type,
                    )
                )
            call_value = value
            if operand.owned:
                if operand.transferred:
                    handoff_decl = self._temporary(
                        "__btrc_transferred_operand",
                        operand.c_type,
                    )
                    declarations.append(handoff_decl)
                    call_value = IRVar(name=handoff_decl.name)
                    handoffs.extend(
                        [
                            IRBinOp(left=call_value, op="=", right=value),
                            IRBinOp(
                                left=value,
                                op="=",
                                right=IRLiteral(text="NULL"),
                            ),
                        ]
                    )
                else:
                    suffix.extend(
                        self.lifetime.release_and_clear(
                            value,
                            operand.type_expr,
                            declarations,
                            operand.c_type,
                        )
                    )
            overrides[id(operand.node)] = call_value

        call = build_call(overrides)
        sequence = [*prefix, *handoffs]
        if opaque_result:
            self._append_opaque_result(
                sequence,
                suffix,
                call,
                result_c_type,
                result_type,
                opaque_result_site,
            )
        elif result_c_type is not None and result_c_type != "void":
            self._append_typed_result(
                sequence,
                suffix,
                declarations,
                call,
                result_c_type,
                result_type,
                promote_result,
                activate_cleanup,
                result_owned,
            )
        else:
            sequence.append(call)
            sequence.extend(suffix)
            sequence.append(IRCast(target_type=CType(text="void"), expr=IRLiteral(text="0")))
        return IRStmtExpr(
            stmts=declarations,
            result=IRCommaExpr(expressions=sequence),
        )

    @staticmethod
    def _lower_operand(operand, overrides, lower_expr=None):
        if operand.lower_with_overrides is not None:
            return operand.lower_with_overrides(overrides)
        if operand.lowered is not None:
            return operand.lowered
        return lower_expr(operand.node)

    @staticmethod
    def _append_opaque_result(
        sequence,
        suffix,
        call,
        result_c_type,
        result_type,
        source_site,
    ) -> None:
        if result_c_type is not None or result_type is not None:
            raise ValueError("opaque call result cannot also have a concrete type")
        if source_site is None:
            raise ValueError("opaque call result requires a source site")
        if suffix:
            from .call_operand_diagnostics import reject_opaque_result_cleanup

            reject_opaque_result_cleanup(source_site)
        sequence.append(call)

    def _append_typed_result(
        self,
        sequence,
        suffix,
        declarations,
        call,
        result_c_type,
        result_type,
        promote_result,
        activate_cleanup,
        result_owned,
    ) -> None:
        result_decl = self._temporary("__btrc_call_result", result_c_type)
        result_decl.is_volatile = True
        declarations.append(result_decl)
        result = IRVar(name=result_decl.name)
        sequence.append(IRBinOp(left=result, op="=", right=call))
        if promote_result:
            if result_type is None:
                raise ValueError("managed result promotion requires its semantic type")
            sequence.append(self.lifetime.retain_value(result, result_type))
        protect_result = bool(
            self.lifetime.cleanup_scope.exception_cleanup_active()
            and result_type is not None
            and (result_owned or promote_result)
            and self.lifetime.values.is_managed(result_type)
        )
        if protect_result:
            self.lifetime.protect_temporary(
                result_decl,
                result_type,
                declarations,
                sequence,
                "__btrc_call_result_cleanup",
                activate_cleanup=activate_cleanup,
            )
            handoff_decl = self._temporary(
                "__btrc_call_result_handoff",
                result_c_type,
            )
            declarations.append(handoff_decl)
            handoff = IRVar(name=handoff_decl.name)
        sequence.extend(suffix)
        if protect_result:
            sequence.extend(
                [
                    IRBinOp(left=handoff, op="=", right=result),
                    IRBinOp(
                        left=result,
                        op="=",
                        right=IRLiteral(text="NULL"),
                    ),
                    handoff,
                ]
            )
        else:
            sequence.append(result)

    def _temporary(
        self,
        prefix: str,
        c_type: str,
        init=None,
    ) -> IRVarDecl:
        declaration = IRVarDecl(
            c_type=CType(text=c_type),
            name=self.context.fresh_temp(prefix),
            init=init,
        )
        self.context.record_declaration(declaration)
        return declaration


__all__ = ["CallBoundaryLowerer", "CallOperand"]
