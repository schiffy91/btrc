"""Single-evaluation boundaries for expressions consuming owned operands."""

from __future__ import annotations

from .call_boundary import CallOperand, sequence_call_boundary
from .evaluation_order import operand_c_type
from .ownership import owns_result
from .types import type_to_c


def sequence_owned_operands(
    gen,
    nodes,
    *,
    build,
    result_type,
    promote_result: bool = False,
    keep_nodes=(),
    pin_nodes=(),
    force: bool = False,
):
    """Evaluate eager source operands once and stabilize managed values.

    ``force`` establishes source order even for scalar operands. ``pin_nodes``
    keeps borrowed managed values alive while later operands execute.
    """
    specs = []
    keep_ids = {id(node) for node in keep_nodes}
    pin_ids = {id(node) for node in pin_nodes}
    lifetime_required = False
    for node in nodes:
        type_expr = gen.analyzed.node_types.get(id(node))
        # An enclosing boundary owns and will consume an installed override.
        # Nested field/index/lvalue lowering must treat that stabilized slot as
        # borrowed or it would wrap an assignable projection in a non-lvalue
        # statement expression and release the same reference twice.
        owned = bool(id(node) not in gen._owning_temp_overrides and owns_result(gen, node))
        keep = id(node) in keep_ids
        pin = id(node) in pin_ids and not owned
        lifetime_required = lifetime_required or owned or keep or pin
        specs.append((node, type_expr, owned, keep, pin))
    needs_boundary = force or lifetime_required
    if not needs_boundary:
        return None
    if any(type_expr is None for _node, type_expr, _owned, _keep, _pin in specs):
        if not lifetime_required:
            return None
        from .errors import CodegenError

        raise CodegenError("owned expression sequencing requires concrete analyzed operand types")

    operands = [
        CallOperand(
            node=node,
            type_expr=type_expr,
            c_type=operand_c_type(
                gen,
                node,
                type_expr,
                render=type_to_c,
            ),
            keep=keep,
            pin=pin,
            owned=owned,
        )
        for node, type_expr, owned, keep, pin in specs
    ]

    def build_with_overrides(overrides):
        previous = {key: gen._owning_temp_overrides.get(key) for key in overrides}
        gen._owning_temp_overrides.update(overrides)
        try:
            return build()
        finally:
            for key, value in previous.items():
                if value is None:
                    gen._owning_temp_overrides.pop(key, None)
                else:
                    gen._owning_temp_overrides[key] = value

    from .expressions import lower_expr

    return sequence_call_boundary(
        gen,
        operands,
        lower_expr=lambda node: lower_expr(gen, node),
        build_call=build_with_overrides,
        result_c_type=(type_to_c(result_type) if result_type is not None else None),
        result_type=result_type,
        fresh_temp=gen.fresh_temp,
        cleanup_active=gen.exception_cleanup_active(),
        record_decl=gen._func_var_decls.append,
        promote_result=promote_result,
    )


__all__ = ["sequence_owned_operands"]
