"""Target-directed value lowering with effective ownership metadata."""

from __future__ import annotations

from dataclasses import dataclass

from ...ast_nodes import TypeExpr
from ..nodes import IRBinOp, IRExpr, IRLiteral, IRTernary
from .call_boundary import CallOperand, sequence_call_boundary
from .stringable import to_string_call


@dataclass(frozen=True)
class PreparedValue:
    """A lowered value after target-directed conversion."""

    value: IRExpr
    effective_type: object
    owned: bool
    converted: bool = False


def prepare_value(
    gen,
    node,
    target_type,
    *,
    lower_expr,
    type_of,
    owns_result,
    render_type,
    fresh_temp,
    cleanup_active,
    record_decl,
    activate_cleanup=None,
) -> PreparedValue:
    """Lower ``node`` and expose the type/ownership after implicit coercion."""
    from .type_resolution import canonical_type

    source_type = canonical_type(type_of(node), gen.analyzed.typedef_table)
    resolved_target = canonical_type(target_type, gen.analyzed.typedef_table)
    lowered = lower_expr(node)
    if not requires_string_conversion(gen, target_type, source_type):
        return PreparedValue(
            value=lowered,
            effective_type=source_type or resolved_target or target_type,
            owned=bool(owns_result(node)),
        )

    source_owned = bool(owns_result(node))
    operand = CallOperand(
        node=node,
        type_expr=source_type,
        c_type=render_type(source_type),
        owned=source_owned,
        lowered=lowered,
    )
    string_type = TypeExpr(base="string")

    def build(overrides):
        receiver = overrides[id(node)]
        return IRTernary(
            condition=IRBinOp(
                left=receiver,
                op="!=",
                right=IRLiteral(text="NULL"),
            ),
            true_expr=to_string_call(gen, source_type, receiver),
            false_expr=IRLiteral(text='""'),
        )

    converted = sequence_call_boundary(
        gen,
        [operand],
        lower_expr=lower_expr,
        build_call=build,
        result_c_type=render_type(string_type),
        result_type=string_type,
        fresh_temp=fresh_temp,
        cleanup_active=cleanup_active,
        record_decl=record_decl,
        activate_cleanup=activate_cleanup,
        result_owned=True,
    )
    return PreparedValue(
        value=converted,
        effective_type=string_type,
        owned=True,
        converted=True,
    )


def prepare_normal_value(gen, node, target_type, *, lowered=None) -> PreparedValue:
    """Prepare one value with the normal generator's concrete dependencies."""
    from .expressions import lower_expr
    from .ownership import owns_result
    from .types import type_to_c

    return prepare_value(
        gen,
        node,
        target_type,
        lower_expr=lambda value: lowered if value is node and lowered is not None else lower_expr(gen, value),
        type_of=lambda value: gen.analyzed.node_types.get(id(value)),
        owns_result=lambda value: bool(id(value) not in gen._owning_temp_overrides and owns_result(gen, value)),
        render_type=type_to_c,
        fresh_temp=gen.fresh_temp,
        cleanup_active=gen.exception_cleanup_active(),
        record_decl=gen._func_var_decls.append,
    )


def prepare_generic_value(emitter, node, target_type, *, lowered=None) -> PreparedValue:
    """Prepare one value inside a monomorphized generic method body."""
    return prepare_value(
        emitter._gen,
        node,
        target_type,
        lower_expr=lambda value: lowered if value is node and lowered is not None else emitter._expr(value),
        type_of=emitter._resolve_expr_type,
        owns_result=lambda value: bool(id(value) not in emitter._arc_overrides and emitter._owns_expr(value)),
        render_type=emitter.iter_value_c,
        fresh_temp=emitter._fresh_temp,
        cleanup_active=emitter._exception_cleanup_active(),
        record_decl=emitter._func_var_decls.append,
        activate_cleanup=emitter._activate_cleanup_registration,
    )


def requires_string_conversion(gen, target_type, source_type) -> bool:
    from ...string_conversion import requires_class_to_string
    from .type_resolution import canonical_type

    target = canonical_type(target_type, gen.analyzed.typedef_table)
    source = canonical_type(source_type, gen.analyzed.typedef_table)
    return requires_class_to_string(
        gen.analyzed.class_table,
        target,
        source,
        canonicalize=lambda value: canonical_type(
            value,
            gen.analyzed.typedef_table,
        ),
    )


def prepared_value_pin_flags(gen, values, *, type_of=None) -> list[bool]:
    """Mark borrowed managed values invalidatable by later evaluation."""
    from .evaluation_order import has_observable_effect, source_order_pin_flags

    effects = [
        prepared.converted
        or has_observable_effect(
            gen,
            node,
            type_of=type_of,
        )
        for node, prepared in values
    ]
    return source_order_pin_flags(
        gen,
        [node for node, _prepared in values],
        [prepared.effective_type for _node, prepared in values],
        [prepared.owned for _node, prepared in values],
        type_of=type_of,
        effects=effects,
    )


__all__ = [
    "PreparedValue",
    "prepare_generic_value",
    "prepare_normal_value",
    "prepare_value",
    "prepared_value_pin_flags",
    "requires_string_conversion",
]
