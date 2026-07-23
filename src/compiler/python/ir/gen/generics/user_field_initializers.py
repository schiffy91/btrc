"""Instance-field defaults for monomorphized user-generic classes."""

from __future__ import annotations

from ....ast_nodes import BraceInitializer, ListLiteral
from ...nodes import (
    IRAssign,
    IRExprStmt,
    IRFieldAccess,
    IRStmt,
    IRVar,
)
from ..aggregate_initializers import lower_brace_initializer
from ..callable_boundaries import reject_persistent_callable_escape
from ..errors import CodegenError
from ..type_resolution import canonical_type
from ..upcast import upcast_class_pointer
from .core import _resolve_type


def emit_generic_field_initializers(
    gen,
    cls_info,
    type_map,
    emitter,
) -> list[IRStmt]:
    """Lower concrete field defaults in declaration/storage order.

    The allocating wrapper registers ``self`` for construction abandon before
    calling the init function.  Consequently, publishing each managed value as
    an edge immediately makes every completed default visible to exception and
    cycle teardown while later defaults and the constructor body execute.
    """
    statements: list[IRStmt] = []
    owner = IRVar(name="self")
    for storage_name, member in cls_info.instance_storage:
        initializer = getattr(member, "initializer", None)
        declared_type = getattr(member, "type", None)
        if initializer is None or declared_type is None:
            continue

        field_type = _resolve_type(
            declared_type,
            type_map,
            gen.analyzed.typedef_table,
            gen.type_identity,
        )
        reject_persistent_callable_escape(
            gen,
            field_type,
            initializer,
            "field storage",
            callable_abi=lambda value: _generic_callable_abi(
                emitter,
                value,
            ),
        )
        target = IRFieldAccess(
            obj=owner,
            field=storage_name,
            arrow=True,
        )
        from ..prepared_values import prepare_generic_value

        prepared = prepare_generic_value(
            emitter,
            initializer,
            field_type,
            lower_value=lambda value, field_type=field_type: lower_generic_field_initializer_value(
                gen,
                emitter,
                field_type,
                value,
            ),
        )
        value = prepared.value
        value = upcast_class_pointer(
            gen,
            field_type,
            prepared.effective_type,
            value,
            emitter._type_renderer,
        )
        owned = prepared.owned

        if gen.managed_values.is_arc(field_type):
            statements.append(
                IRExprStmt(
                    expr=gen.lifetime.replace_edge_value(
                        target,
                        value,
                        field_type,
                        owner,
                        adopt=owned,
                    )
                )
            )
            continue

        statements.append(IRAssign(target=target, value=value))
        if gen.managed_values.is_managed(field_type):
            publish = gen.lifetime.adopt_edge_value if owned else gen.lifetime.retain_edge_value
            statements.append(IRExprStmt(expr=publish(target, field_type, owner)))
    return statements


def lower_generic_field_initializer_value(
    gen,
    emitter,
    field_type,
    initializer,
):
    """Contextual assignment/coercion hook for one generic field default.

    Collection and aggregate literals need the resolved destination type.
    Future managed assignment coercions, including explicit class-to-string
    lowering, belong at this same boundary rather than in lifecycle
    orchestration.
    """
    resolved = canonical_type(field_type, gen.analyzed.typedef_table)
    if resolved is not None and resolved.is_array and isinstance(initializer, (BraceInitializer, ListLiteral)):
        raise CodegenError(
            "array-valued class field defaults require persistent backing storage; "
            "initialize an owned collection or pointer in the constructor instead"
        )
    if isinstance(initializer, (BraceInitializer, ListLiteral)) and _is_value_aggregate(
        gen,
        resolved,
    ):
        return _lower_value_aggregate(gen, emitter, initializer, field_type)
    return emitter._assignment_value(field_type, initializer)


def _lower_value_aggregate(gen, emitter, initializer, target_type):
    return lower_brace_initializer(
        gen,
        initializer,
        emitter._type_renderer,
        node_type=target_type,
        lower=lambda element: _lower_aggregate_element(gen, emitter, element),
    )


def _lower_aggregate_element(gen, emitter, element):
    element_type = emitter._resolve_expr_type(element)
    resolved = canonical_type(element_type, gen.analyzed.typedef_table)
    if isinstance(element, (BraceInitializer, ListLiteral)) and (
        bool(resolved and resolved.is_array) or _is_value_aggregate(gen, resolved)
    ):
        return _lower_value_aggregate(gen, emitter, element, element_type)
    return emitter.lower_expression(element)


def _is_value_aggregate(gen, resolved_type) -> bool:
    if resolved_type is None or resolved_type.pointer_depth > 0 or resolved_type.is_array:
        return False
    struct_name = resolved_type.base.removeprefix("struct ")
    return resolved_type.base == "Tuple" or struct_name in gen.analyzed.struct_table


def _generic_callable_abi(emitter, value):
    from .user_callable_provenance import generic_callable_return_abi

    return generic_callable_return_abi(emitter, value)


__all__ = [
    "emit_generic_field_initializers",
    "lower_generic_field_initializer_value",
]
