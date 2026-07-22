"""Evaluation-order classification for monomorphized generic calls."""


def evaluated_callee(context, expression):
    """Return a side-effecting callable value that precedes call arguments."""
    from ....ast_nodes import FieldAccessExpr, Identifier, LambdaExpr

    callee = expression.callee
    if isinstance(callee, Identifier):
        is_variable = callee.name in context._var_types or bool(
            context._gen is not None and callee.name in context._gen.analyzed.global_var_types
        )
        return callee if is_variable else None
    return None if isinstance(callee, (FieldAccessExpr, LambdaExpr)) else callee


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
    from ..type_resolution import function_pointer_signature

    return (
        function_pointer_signature(
            context._resolve_expr_type(callee),
            context._typedefs(),
        )
        is not None
    )


__all__ = ["evaluated_callee", "language_ordered_call"]
