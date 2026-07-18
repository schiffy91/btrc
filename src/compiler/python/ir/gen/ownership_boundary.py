"""Single-evaluation boundaries for expressions consuming owned operands."""

from __future__ import annotations

from .call_boundary import CallOperand, sequence_call_boundary
from .evaluation_order import (
    borrowed_value_can_be_pinned,
    operand_c_type,
    source_order_pin_flags,
)
from .ownership import owns_result
from .types import type_to_c


def sequence_owned_operands(
    gen,
    nodes,
    *,
    build,
    result_type,
    promote_result: bool = False,
    result_owned: bool = False,
    keep_nodes=(),
    pin_nodes=(),
    force: bool = False,
    allow_trailing_opaque: bool = False,
    opaque_context: str = "expression",
    prepared_values=None,
):
    """Evaluate eager source operands once and stabilize managed values.

    ``force`` establishes source order even for scalar operands. ``pin_nodes``
    keeps borrowed managed values alive while later operands execute.
    """
    specs = []
    prepared_values = prepared_values or {}
    keep_ids = {id(node) for node in keep_nodes}
    pin_ids = {id(node) for node in pin_nodes}
    for node in nodes:
        prepared = prepared_values.get(id(node))
        type_expr = prepared.effective_type if prepared is not None else gen.analyzed.node_types.get(id(node))
        # An enclosing boundary owns and will consume an installed override.
        # Nested field/index/lvalue lowering must treat that stabilized slot as
        # borrowed or it would wrap an assignable projection in a non-lvalue
        # statement expression and release the same reference twice.
        owned = bool(
            prepared.owned
            if prepared is not None
            else id(node) not in gen._owning_temp_overrides and owns_result(gen, node)
        )
        keep = id(node) in keep_ids
        pin = id(node) in pin_ids and not owned and borrowed_value_can_be_pinned(node)
        specs.append((node, type_expr, owned, keep, pin, prepared))
    automatic_pins = source_order_pin_flags(
        gen,
        nodes,
        [type_expr for _node, type_expr, _owned, _keep, _pin, _prepared in specs],
        [owned for _node, _type_expr, owned, _keep, _pin, _prepared in specs],
    )
    specs = [
        (node, type_expr, owned, keep, pin or automatic_pins[index], prepared)
        for index, (node, type_expr, owned, keep, pin, prepared) in enumerate(specs)
    ]
    lifetime_required = any(owned or keep or pin for _node, _type_expr, owned, keep, pin, _prepared in specs)
    needs_boundary = force or lifetime_required
    if not needs_boundary:
        return None
    missing = [index for index, spec in enumerate(specs) if spec[1] is None]
    if missing and allow_trailing_opaque:
        trailing = len(specs) - 1
        if missing == [trailing] and trailing > 0:
            node, _type_expr, owned, keep, pin, _prepared = specs.pop()
            if owned or keep or pin:
                from .evaluation_order import reject_opaque_ordering

                reject_opaque_ordering(node, opaque_context)
        else:
            from .evaluation_order import reject_opaque_ordering

            reject_opaque_ordering(specs[missing[0]][0], opaque_context)
    elif missing:
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
            lowered=prepared.value if prepared is not None else None,
        )
        for node, type_expr, owned, keep, pin, prepared in specs
    ]

    def build_with_overrides(overrides):
        previous = {key: gen._owning_temp_overrides.get(key) for key in overrides}
        previous_types = {key: gen._type_temp_overrides.get(key) for key in overrides}
        gen._owning_temp_overrides.update(overrides)
        gen._type_temp_overrides.update(
            {id(node): type_expr for node, type_expr, _owned, _keep, _pin, _prepared in specs}
        )
        try:
            return build()
        finally:
            for key, value in previous.items():
                if value is None:
                    gen._owning_temp_overrides.pop(key, None)
                else:
                    gen._owning_temp_overrides[key] = value
            for key, value in previous_types.items():
                if value is None:
                    gen._type_temp_overrides.pop(key, None)
                else:
                    gen._type_temp_overrides[key] = value

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
        result_owned=bool(result_owned or promote_result),
    )


__all__ = ["sequence_owned_operands"]
