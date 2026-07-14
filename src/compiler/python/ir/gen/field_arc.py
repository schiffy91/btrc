"""Single-evaluation ARC lowering for managed field assignments."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    AssignExpr,
    BraceInitializer,
    FieldAccessExpr,
    ListLiteral,
    MapLiteral,
    SelfExpr,
)
from ..nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCommaExpr,
    IRFieldAccess,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from .managed_values import (
    adopt_edge_value,
    is_class_type,
    is_managed_type,
    poll_released_values,
    release_edge_value,
    replace_edge_value,
    retain_edge_value,
    unlink_edge_value,
)
from .types import is_generic_class_type, mangle_generic_type, type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_managed_field_assignment(gen: IRGenerator, node: AssignExpr):
    """Return a sequenced assignment expression, or ``None`` if unmanaged."""
    if not isinstance(node.target, FieldAccessExpr):
        return None
    static_type = _static_managed_field_type(gen, node.target)
    if static_type is not None:
        from .expressions import lower_expr
        from .local_arc import lower_managed_slot_assignment

        return lower_managed_slot_assignment(
            gen,
            node,
            lower_expr(gen, node.target),
            static_type,
        )
    receiver_type = gen.analyzed.node_types.get(id(node.target.obj))
    if not receiver_type or receiver_type.base not in gen.analyzed.class_table:
        return None
    class_info = gen.analyzed.class_table[receiver_type.base]
    field_name = node.target.field
    field = class_info.fields.get(field_name)
    backing_property = bool(
        field is None and isinstance(node.target.obj, SelfExpr) and gen.current_property_backing == field_name
    )
    prop = class_info.properties.get(field_name) if backing_property else None
    if field is None and prop is None:
        return None
    # The declaration can still contain class parameters (for example,
    # ``CycleLink<T>.next``).  The analyzer records the access type after
    # substituting the concrete receiver arguments, which is the type needed
    # for ARC temporaries and the destroy function at this call site.
    field_type = gen.analyzed.node_types.get(id(node.target)) or (field.type if field is not None else prop.type)
    if not is_managed_type(gen, field_type):
        return None

    from .expressions import lower_expr
    from .upcast import upcast_class_pointer

    receiver_decl = _temp_decl(
        gen,
        "__btrc_field_obj",
        type_to_c(receiver_type),
        None,
    )
    receiver = IRVar(name=receiver_decl.name)
    target = IRFieldAccess(
        obj=receiver,
        field=f"_prop_{field_name}" if backing_property else field_name,
        arrow=True,
    )

    if node.op != "=":
        return _lower_managed_field_compound(
            gen,
            node,
            receiver_decl,
            receiver,
            target,
            field_type,
        )
    value = _lower_value(gen, node.value, field_type)
    value_type = gen.analyzed.node_types.get(id(node.value))
    value = upcast_class_pointer(gen, field_type, value_type, value)
    owned = _is_owned_value(gen, node.value)
    value_decl = _temp_decl(gen, "__btrc_field_new", type_to_c(field_type), None)
    new_value = IRVar(name=value_decl.name)

    sequence = [
        IRBinOp(left=receiver, op="=", right=lower_expr(gen, node.target.obj)),
        IRBinOp(left=new_value, op="=", right=value),
    ]
    declarations = [receiver_decl, value_decl]
    if is_class_type(gen, field_type):
        sequence.append(
            replace_edge_value(
                gen,
                target,
                new_value,
                field_type,
                receiver,
                adopt=owned,
            )
        )
    else:
        old_decl = _temp_decl(gen, "__btrc_field_old", type_to_c(field_type), None)
        declarations.append(old_decl)
        old_value = IRVar(name=old_decl.name)
        sequence.append(IRBinOp(left=old_value, op="=", right=target))
        sequence.append(unlink_edge_value(gen, old_value, field_type, receiver))
        if owned:
            sequence.append(adopt_edge_value(gen, new_value, field_type, receiver))
        else:
            sequence.append(retain_edge_value(gen, new_value, field_type, receiver))
        sequence.append(IRBinOp(left=target, op="=", right=new_value))
        sequence.append(release_edge_value(gen, old_value, field_type, replacement=new_value))
    flush = poll_released_values(gen, field_type)
    if flush is not None:
        sequence.append(flush)
    sequence.append(target)
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=sequence),
    )


def _lower_managed_field_compound(
    gen,
    node,
    receiver_decl,
    receiver,
    target,
    field_type,
):
    from .expressions import lower_expr
    from .managed_compound import (
        lower_managed_compound_operator,
        managed_compound_keeps_rhs,
    )
    from .managed_updates import lower_managed_compound_update

    right_type = gen.analyzed.node_types.get(id(node.value)) or field_type
    class_edge = is_class_type(gen, field_type)

    def commit(old, replacement):
        if class_edge:
            return [
                replace_edge_value(
                    gen,
                    target,
                    replacement,
                    field_type,
                    receiver,
                    adopt=True,
                )
            ]
        return [
            unlink_edge_value(gen, old, field_type, receiver),
            adopt_edge_value(gen, replacement, field_type, receiver),
            IRBinOp(left=target, op="=", right=replacement),
        ]

    update = lower_managed_compound_update(
        gen,
        value_type=field_type,
        right_type=right_type,
        old_expr=target,
        current_expr=target,
        right_expr=_lower_value(gen, node.value, field_type),
        compute=lambda old, right: lower_managed_compound_operator(
            gen,
            node,
            old,
            right,
            field_type,
            right_type,
            fresh_temp=gen.fresh_temp,
        ),
        commit=commit,
        result_expr=lambda: target,
        old_temporary_owned=False,
        right_owned=bool(is_managed_type(gen, right_type) and _is_owned_value(gen, node.value)),
        right_keep=managed_compound_keeps_rhs(
            gen,
            field_type,
            node.op[:-1],
            right_type,
        ),
        release_replaced_old=not class_edge,
        transfer_before_commit=class_edge,
        c_type=type_to_c,
        fresh_temp=gen.fresh_temp,
        record_decl=gen._func_var_decls.append,
        cleanup_active=gen.exception_cleanup_active(),
    )
    return IRStmtExpr(
        stmts=[receiver_decl],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(
                    left=receiver,
                    op="=",
                    right=lower_expr(gen, node.target.obj),
                ),
                update,
            ]
        ),
    )


def _temp_decl(gen, prefix: str, c_type: str, init) -> IRVarDecl:
    declaration = IRVarDecl(
        c_type=CType(text=c_type),
        name=gen.fresh_temp(prefix),
        init=init,
    )
    gen._func_var_decls.append(declaration)
    return declaration


def _lower_value(gen, value, field_type):
    from .expressions import lower_expr

    empty_collection = (
        (isinstance(value, BraceInitializer) and not value.elements)
        or (isinstance(value, ListLiteral) and not value.elements)
        or (isinstance(value, MapLiteral) and not value.entries)
    )
    if empty_collection and is_generic_class_type(field_type, gen.analyzed.class_table):
        mangled = mangle_generic_type(field_type.base, field_type.generic_args)
        return IRCall(callee=f"{mangled}_new", args=[])
    return lower_expr(gen, value)


def _is_owned_value(gen, value) -> bool:
    from .ownership import owns_result

    return owns_result(gen, value)


def _static_managed_field_type(gen, target):
    from ...ast_nodes import Identifier

    if not isinstance(target.obj, Identifier):
        return None
    class_info = gen.analyzed.class_table.get(target.obj.name)
    field = class_info.static_fields.get(target.field) if class_info else None
    if field is None or not is_managed_type(gen, field.type):
        return None
    return gen.analyzed.node_types.get(id(target)) or field.type
