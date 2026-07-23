"""Unevaluated sizeof lowering for monomorphized generic bodies."""

from ....ast_nodes import SizeofExprOp, SizeofType, StringLiteral
from ...nodes import CType, IRSizeof
from ..errors import unsupported_node


def lower_generic_sizeof(emitter, operand):
    if isinstance(operand, SizeofType):
        return IRSizeof(operand=CType(text=emitter.resolve_c(operand.type)))
    if not isinstance(operand, SizeofExprOp):
        raise unsupported_node("generic sizeof operand", operand)

    expression_type = emitter._resolve_expr_type(operand.expr)
    if expression_type is not None and not expression_type.is_array and not isinstance(operand.expr, StringLiteral):
        return IRSizeof(operand=CType(text=emitter.iter_value_c(expression_type)))

    emitter._unevaluated_depth += 1
    emitter._boundary_ownership.context.unevaluated_depth += 1
    if emitter._gen is not None:
        emitter._gen.context.unevaluated_depth += 1
    try:
        return IRSizeof(operand=emitter._expr(operand.expr))
    finally:
        emitter._unevaluated_depth -= 1
        emitter._boundary_ownership.context.unevaluated_depth -= 1
        if emitter._gen is not None:
            emitter._gen.context.unevaluated_depth -= 1


__all__ = ["lower_generic_sizeof"]
