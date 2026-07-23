"""Target-directed value lowering with effective ownership metadata."""

from __future__ import annotations

from dataclasses import dataclass

from ...ast_nodes import TypeExpr
from ..nodes import IRBinOp, IRExpr, IRLiteral, IRTernary
from .call_boundary import CallOperand
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
    ownership,
    lower_expr,
    type_of,
    owns_result,
    render_type,
    activate_cleanup=None,
    hosted_results=None,
) -> PreparedValue:
    """Lower ``node`` and expose the type/ownership after implicit coercion."""
    from .type_resolution import canonical_type

    source_type = canonical_type(type_of(node), gen.analyzed.typedef_table)
    resolved_target = canonical_type(target_type, gen.analyzed.typedef_table)
    from .hosted_result_conversion import (
        ADOPT,
        COPY,
        REJECT,
        hosted_string_conversion_mode,
    )

    hosted_mode = (
        hosted_results.conversion_mode(
            node,
            resolved_target,
            source_type,
        )
        if hosted_results is not None
        else hosted_string_conversion_mode(
            gen,
            node,
            resolved_target,
            source_type,
        )
    )
    if hosted_mode == REJECT:
        from .errors import CodegenError

        raise CodegenError("raw char* to managed string conversion reached IR without a proven hosted ownership effect")
    if hosted_mode in {ADOPT, COPY}:
        # Make the call boundary perform the conversion before releasing its
        # operands.  This is essential for alias results and also registers a
        # fresh result before any throwing suffix cleanup.
        if hosted_results is not None:
            with hosted_results.request(
                node,
                hosted_mode,
                resolved_target,
            ):
                lowered = lower_expr(node)
        else:
            context = getattr(gen, "context", None)
            requests = (
                context.hosted_result_conversion_requests
                if context is not None
                else getattr(
                    gen,
                    "_hosted_result_conversion_requests",
                    None,
                )
            )
            if requests is None:
                requests = {}
                gen._hosted_result_conversion_requests = requests
            key = id(node)
            missing = object()
            previous = requests.get(key, missing)
            requests[key] = (hosted_mode, resolved_target)
            try:
                lowered = lower_expr(node)
            finally:
                if previous is missing:
                    requests.pop(key, None)
                else:
                    requests[key] = previous
        return PreparedValue(
            value=lowered,
            effective_type=resolved_target,
            owned=True,
            converted=True,
        )
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

    converted = ownership.boundaries.sequence(
        [operand],
        lower_expr=lower_expr,
        build_call=build,
        result_c_type=render_type(string_type),
        result_type=string_type,
        activate_cleanup=activate_cleanup,
        result_owned=True,
    )
    return PreparedValue(
        value=converted,
        effective_type=string_type,
        owned=True,
        converted=True,
    )


def prepare_normal_value(
    gen,
    node,
    target_type,
    *,
    lowered=None,
    lower_value=None,
) -> PreparedValue:
    """Prepare one value with the normal generator's concrete dependencies."""
    from .expressions import lower_expr
    from .types import type_to_c

    lower_value = lower_value or (lambda value: lower_expr(gen, value))
    return prepare_value(
        gen,
        node,
        target_type,
        ownership=gen.ownership,
        lower_expr=lambda value: lowered if value is node and lowered is not None else lower_value(value),
        type_of=lambda value: gen.analyzed.node_types.get(id(value)),
        owns_result=lambda value: bool(
            id(value) not in gen.context.owning_overrides and gen.ownership.owns_result(value)
        ),
        render_type=type_to_c,
    )


def prepare_generic_value(
    emitter,
    node,
    target_type,
    *,
    lowered=None,
    lower_value=None,
) -> PreparedValue:
    """Prepare one value inside a monomorphized generic method body."""
    lower_value = lower_value or emitter._expr
    return prepare_value(
        emitter._gen,
        node,
        target_type,
        ownership=emitter._boundary_ownership,
        lower_expr=lambda value: lowered if value is node and lowered is not None else lower_value(value),
        type_of=emitter._resolve_expr_type,
        owns_result=lambda value: bool(id(value) not in emitter._arc_overrides and emitter._owns_expr(value)),
        render_type=emitter.iter_value_c,
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
