"""Unary expression lowering for monomorphized generic bodies."""

from ...nodes import IRAddressOf, IRCommaExpr, IRDeref, IRUnaryOp, IRVar
from ..updates import lower_incdec


def lower_generic_unary_plain(emitter, expression):
    """Lower one generic unary expression after ownership sequencing."""

    if expression.op in {"++", "--"} and emitter._gen:
        result = lower_incdec(emitter._update_context(), expression)
        if emitter._mutates_self_storage(expression.operand):
            from ..arc_ops import invalidate_cycle_proof

            return IRCommaExpr(
                expressions=[
                    invalidate_cycle_proof(emitter._gen, IRVar(name="self")),
                    result,
                ]
            )
        return result
    operand = emitter._expr(expression.operand)
    if expression.op == "&":
        return IRAddressOf(expr=operand, source_expression=True)
    if expression.op == "*":
        return IRDeref(expr=operand)
    return IRUnaryOp(op=expression.op, operand=operand, prefix=expression.prefix)


__all__ = ["lower_generic_unary_plain"]
