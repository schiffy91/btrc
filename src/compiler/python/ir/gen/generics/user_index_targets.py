"""Target-directed indexed-key preparation in generic bodies."""


def prepared_generic_index_targets(emitter, expression):
    """Prepare a generic indexed setter key against its concrete contract."""
    from ....ast_nodes import IndexExpr

    if not isinstance(expression.target, IndexExpr):
        return {}
    receiver_type = emitter._resolve_expr_type(expression.target.obj)
    protocol = emitter._gen.index_protocols.resolve(receiver_type)
    if protocol is None or protocol.setter is None:
        return {}
    expected = protocol.setter.params[0].type
    substitutions = protocol.substitutions(receiver_type)
    if substitutions:
        from ..type_resolution import substitute_concrete_type

        expected = substitute_concrete_type(
            expected,
            substitutions,
            emitter._gen.analyzed.typedef_table,
            emitter.type_identity,
        )
    expected = emitter._resolve(expected)
    source = emitter._resolve_expr_type(expression.target.index)
    from ..prepared_values import (
        prepare_generic_value,
        requires_string_conversion,
    )

    if not requires_string_conversion(emitter._gen, expected, source):
        return {}
    return {
        id(expression.target.index): prepare_generic_value(
            emitter,
            expression.target.index,
            expected,
        )
    }


__all__ = ["prepared_generic_index_targets"]
