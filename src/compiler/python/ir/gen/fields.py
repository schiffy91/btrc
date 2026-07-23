"""Field access, indexing, and assignment lowering → IR."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    FieldAccessExpr,
    Identifier,
    IndexExpr,
)
from ..nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCommaExpr,
    IRExpr,
    IRFieldAccess,
    IRFunctionRef,
    IRIndex,
    IRLiteral,
    IRStmtExpr,
    IRTernary,
    IRVar,
    IRVarDecl,
)
from .types import (
    CTypeRenderer,
    is_direct_generic_instance_reference,
)

if TYPE_CHECKING:
    from .lowerer import IRLowerer


def _lower_field_access(
    gen: IRLowerer,
    node: FieldAccessExpr,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRExpr:
    """Lower field access, handling optional chaining and special types."""
    from .managed_values import is_managed_type

    result_type = gen.analyzed.node_types.get(id(node))
    from ...class_storage import custom_property_getter

    custom_getter = custom_property_getter(
        gen.analyzed.class_table,
        gen.analyzed.node_types.get(id(node.obj)),
        node.field,
    )
    from .assignment_ownership import borrowed_projection_owner_operands

    dependencies = borrowed_projection_owner_operands(
        node.obj,
        owns=lambda expression: gen.ownership.owns_result(expression),
        overridden=lambda expression: id(expression) in gen.context.owning_overrides,
    )
    sequenced = gen.ownership.sequence_operands(
        [*dependencies, node.obj],
        build=lambda: _lower_field_access_plain(
            gen,
            node,
            type_renderer,
            default_arguments,
        ),
        result_type=result_type,
        pin_nodes=[node.obj] if custom_getter else [],
        promote_result=bool(is_managed_type(gen, result_type) and not gen.ownership.projection_is_owned_call(node)),
    )
    if sequenced is not None:
        return sequenced
    return _lower_field_access_plain(
        gen,
        node,
        type_renderer,
        default_arguments,
    )


def _lower_field_access_plain(
    gen: IRLowerer,
    node: FieldAccessExpr,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRExpr:
    """Lower one field access after any owning receiver is stabilized."""
    from .expressions import lower_expr

    obj = lower_expr(
        gen,
        node.obj,
        type_renderer,
        default_arguments,
    )
    obj_type = gen.analyzed.node_types.get(id(node.obj))
    from .parameters import source_field_c_name

    field_name = source_field_c_name(gen.analyzed, node.obj, node.field)

    # A mixed auto/custom accessor addresses its own backing slot via
    # `self.property`.  All external reads still call the public getter.
    from ...ast_nodes import SelfExpr

    if isinstance(node.obj, SelfExpr) and gen.context.current_property_backing == node.field:
        return IRFieldAccess(
            obj=obj,
            field=f"_prop_{node.field}",
            arrow=True,
        )

    # Generic class field access: coll.len → coll->len
    if (
        obj_type
        and is_direct_generic_instance_reference(obj_type, gen.analyzed.class_table)
        and node.field in ("len", "length", "size")
    ):
        if node.optional:
            return _lower_optional_access(
                gen,
                obj,
                obj_type,
                gen.analyzed.node_types.get(id(node)),
                type_renderer,
                lambda receiver: IRFieldAccess(obj=receiver, field="len", arrow=True),
            )
        return IRFieldAccess(obj=obj, field="len", arrow=True)

    # Simple enum value: CfaPattern.RGGB → CfaPattern_RGGB (namespaced access,
    # the qualified counterpart of bare `RGGB`).
    if (
        isinstance(node.obj, Identifier)
        and node.obj.name in gen.analyzed.enum_table
        and not gen.local_ownership_declared(node.obj.name)
        and node.field in gen.analyzed.enum_table[node.obj.name]
    ):
        return IRVar(name=f"{node.obj.name}_{node.field}")

    # Rich enum variant tag: Color.RGB → Color_RGB_TAG
    if (
        isinstance(node.obj, Identifier)
        and node.obj.name in gen.analyzed.rich_enum_table
        and not gen.local_ownership_declared(node.obj.name)
    ):
        return IRVar(name=f"{node.obj.name}_{node.field}_TAG")

    # Static method/field on a class name: ClassName.field
    if (
        isinstance(node.obj, Identifier)
        and node.obj.name in gen.analyzed.class_table
        and not gen.local_ownership_declared(node.obj.name)
    ):
        class_info = gen.analyzed.class_table[node.obj.name]
        method = class_info.methods.get(node.field)
        symbol = f"{node.obj.name}_{node.field}"
        if method is not None and method.access == "class":
            return IRFunctionRef(name=symbol)
        return IRVar(name=symbol)

    # Property access on class instances
    if obj_type and obj_type.base in gen.analyzed.class_table:
        cls_info = gen.analyzed.class_table[obj_type.base]
        # Use mangled name for generic class instances
        if obj_type.generic_args and cls_info.generic_params:
            callee_prefix = gen.type_identity.specialization_symbol(obj_type.base, obj_type.generic_args)
        else:
            callee_prefix = obj_type.base
        if node.field in cls_info.properties:
            if node.optional:
                return _lower_optional_access(
                    gen,
                    obj,
                    obj_type,
                    gen.analyzed.node_types.get(id(node)),
                    type_renderer,
                    lambda receiver: IRCall(
                        callee=f"{callee_prefix}_get_{node.field}",
                        args=[receiver],
                    ),
                )
            return IRCall(callee=f"{callee_prefix}_get_{node.field}", args=[obj])

    if node.optional:
        return _lower_optional_access(
            gen,
            obj,
            obj_type,
            gen.analyzed.node_types.get(id(node)),
            type_renderer,
            lambda receiver: IRFieldAccess(
                obj=receiver,
                field=field_name,
                arrow=True,
            ),
        )

    field = IRFieldAccess(
        obj=obj,
        field=field_name,
        arrow=receiver_uses_arrow(gen, obj_type, explicit=node.arrow),
    )
    from ..storage_provenance import record_array_projection

    return record_array_projection(field, gen.analyzed.node_types.get(id(node)))


def receiver_uses_arrow(gen: IRLowerer, receiver_type, *, explicit: bool = False) -> bool:
    """Choose C member syntax from the receiver's concrete storage shape."""
    if explicit:
        return True
    from .type_resolution import canonical_type

    resolved = canonical_type(receiver_type, gen.analyzed.typedef_table)
    return bool(resolved and (resolved.pointer_depth > 0 or resolved.base in gen.analyzed.class_table))


def _lower_optional_access(
    gen,
    receiver,
    receiver_type,
    result_type,
    type_renderer: CTypeRenderer,
    access_factory,
) -> IRExpr:
    """Evaluate one nullable receiver once, then conditionally read its value."""
    name = gen.fresh_temp("__btrc_optional")
    temporary = IRVar(name=name)
    c_type = type_renderer.render(receiver_type) if receiver_type is not None else "void*"
    return IRStmtExpr(
        stmts=[IRVarDecl(c_type=CType(text=c_type), name=name)],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(left=temporary, op="=", right=receiver),
                IRTernary(
                    condition=IRBinOp(
                        left=temporary,
                        op="!=",
                        right=IRLiteral(text="NULL"),
                    ),
                    true_expr=access_factory(temporary),
                    false_expr=_optional_zero(
                        gen,
                        result_type,
                        type_renderer,
                    ),
                ),
            ]
        ),
    )


def _optional_zero(gen, result_type, type_renderer: CTypeRenderer):
    from .optional_values import optional_zero_value

    return optional_zero_value(gen, result_type, type_renderer)


def _lower_index(
    gen: IRLowerer,
    node: IndexExpr,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRExpr:
    """Lower index expression: list[i] → List_get(list, i), map[k] → Map_get(map, k)."""
    from .managed_values import is_managed_type

    result_type = gen.analyzed.node_types.get(id(node))
    projection_call = gen.ownership.projection_is_owned_call(node)
    receiver_type = gen.analyzed.node_types.get(id(node.obj))
    protocol_getter = gen.index_protocols.class_info(
        receiver_type,
        method="get",
    )
    from .assignment_ownership import borrowed_projection_owner_operands

    dependencies = borrowed_projection_owner_operands(
        node.obj,
        owns=lambda expression: gen.ownership.owns_result(expression),
        overridden=lambda expression: id(expression) in gen.context.owning_overrides,
    )
    sequenced = gen.ownership.sequence_operands(
        [*dependencies, node.obj, node.index],
        build=lambda: _lower_index_plain(
            gen,
            node,
            type_renderer,
            default_arguments,
        ),
        result_type=result_type,
        pin_nodes=[node.obj] if protocol_getter is not None else [],
        promote_result=bool(is_managed_type(gen, result_type) and not projection_call),
        result_owned=bool(is_managed_type(gen, result_type) and projection_call),
    )
    if sequenced is not None:
        return sequenced
    return _lower_index_plain(
        gen,
        node,
        type_renderer,
        default_arguments,
    )


def _lower_index_plain(
    gen: IRLowerer,
    node: IndexExpr,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRExpr:
    """Lower one index projection after its receiver is stabilized."""
    from .expressions import lower_expr

    obj = lower_expr(
        gen,
        node.obj,
        type_renderer,
        default_arguments,
    )
    index = lower_expr(
        gen,
        node.index,
        type_renderer,
        default_arguments,
    )
    obj_type = gen.analyzed.node_types.get(id(node.obj))
    gpu_lengths = getattr(gen, "_gpu_cpu_array_lengths", None)
    if gpu_lengths and isinstance(node.obj, Identifier) and node.obj.name in gpu_lengths:
        gen.helpers.use("__btrc_gpu_index_check")
        index = IRCall(
            callee="__btrc_gpu_index_check",
            args=[index, IRVar(name=gpu_lengths[node.obj.name])],
            helper_ref="__btrc_gpu_index_check",
        )
    protocol = gen.index_protocols.class_info(obj_type, method="get")
    if protocol is not None:
        prefix = (
            gen.type_identity.specialization_symbol(obj_type.base, obj_type.generic_args)
            if obj_type.generic_args and protocol.generic_params
            else obj_type.base
        )
        return IRCall(callee=f"{prefix}_get", args=[obj, index])
    from ..storage_provenance import record_index_storage

    return record_index_storage(IRIndex(obj=obj, index=index), obj_type)
