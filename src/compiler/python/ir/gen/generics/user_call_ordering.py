"""Evaluation-order classification for monomorphized generic calls."""


def evaluated_callee(expression):
    """Return a side-effecting callable value that precedes call arguments."""
    from ....ast_nodes import FieldAccessExpr, Identifier, LambdaExpr

    callee = expression.callee
    simple_callee = (Identifier, FieldAccessExpr, LambdaExpr)
    return None if isinstance(callee, simple_callee) else callee


def language_ordered_call(context, expression, declaration) -> bool:
    """Whether source-language ordering requires eager operand sequencing."""
    if declaration is not None:
        return True
    if context._gen and id(expression) in context._gen.analyzed.hosted_call_ids:
        return True

    from ....ast_nodes import FieldAccessExpr, Identifier

    callee = expression.callee
    if isinstance(callee, Identifier):
        if callee.name not in context._var_types and callee.name in {"print", "printf", "Mutex"}:
            return True
    if isinstance(callee, FieldAccessExpr):
        if (
            isinstance(callee.obj, Identifier)
            and callee.obj.name not in context._var_types
            and callee.obj.name in context._gen.analyzed.rich_enum_table
        ):
            return True

        from ....string_methods import STRING_METHODS
        from ..type_resolution import canonical_type
        from ..types import is_string_type

        receiver_type = canonical_type(
            context._resolve_expr_type(callee.obj),
            context._gen.analyzed.typedef_table,
        )
        if is_string_type(receiver_type) and callee.field in STRING_METHODS:
            return True
        if receiver_type is not None and receiver_type.base == "Mutex":
            return True
    callee_type = context._resolve_expr_type(callee)
    return bool(callee_type is not None and callee_type.base == "__fn_ptr")


__all__ = ["evaluated_callee", "language_ordered_call"]
