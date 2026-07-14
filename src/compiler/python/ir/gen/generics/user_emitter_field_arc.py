"""ARC replacement for managed fields in generic specializations."""

from __future__ import annotations

from ...nodes import CType, IRBinOp, IRCommaExpr, IRFieldAccess, IRStmtExpr, IRVar, IRVarDecl
from ..managed_values import (
    adopt_edge_value,
    is_class_type,
    poll_released_values,
    release_edge_value,
    replace_edge_value,
    retain_edge_value,
    unlink_edge_value,
)


def lower_generic_field_assignment(emitter, expression):
    """Retain/store/release a managed field, or return ``None``."""
    from ....ast_nodes import FieldAccessExpr, SelfExpr

    if expression.op != "=" or not isinstance(
        expression.target,
        FieldAccessExpr,
    ):
        return None
    receiver_type = emitter._resolve_expr_type(expression.target.obj)
    field_type = emitter._member_type(
        receiver_type,
        expression.target.field,
    )
    if receiver_type is None or not emitter._is_managed_type(field_type):
        return None

    field = expression.target.field
    class_info = emitter._gen.analyzed.class_table.get(receiver_type.base)
    backing_property = bool(isinstance(expression.target.obj, SelfExpr) and emitter._current_property_backing == field)
    if class_info and field in class_info.properties and not backing_property:
        # Properties are callable boundaries, not physical fields.  Let the
        # shared lvalue planner route them through their setter; custom
        # properties may have no backing slot at all.
        return None
    if backing_property:
        field = f"_prop_{field}"

    receiver_decl = _temporary(
        emitter,
        "__btrc_field_obj",
        receiver_type,
    )
    value_decl = _temporary(
        emitter,
        "__btrc_field_new",
        field_type,
    )
    receiver = IRVar(name=receiver_decl.name)
    new_value = IRVar(name=value_decl.name)
    target = IRFieldAccess(obj=receiver, field=field, arrow=True)

    value = emitter._assignment_value(field_type, expression.value)
    value_type = emitter._resolve_expr_type(expression.value)
    from ..upcast import upcast_class_pointer

    value = upcast_class_pointer(
        emitter._gen,
        field_type,
        value_type,
        value,
    )
    sequence = [
        IRBinOp(
            left=receiver,
            op="=",
            right=emitter._expr(expression.target.obj),
        ),
        IRBinOp(left=new_value, op="=", right=value),
    ]
    declarations = [receiver_decl, value_decl]
    owned = emitter._owns_expr(expression.value)
    if is_class_type(emitter._gen, field_type):
        sequence.append(
            replace_edge_value(
                emitter._gen,
                target,
                new_value,
                field_type,
                receiver,
                adopt=owned,
            )
        )
    else:
        old_decl = _temporary(
            emitter,
            "__btrc_field_old",
            field_type,
        )
        declarations.append(old_decl)
        old_value = IRVar(name=old_decl.name)
        sequence.append(IRBinOp(left=old_value, op="=", right=target))
        sequence.append(unlink_edge_value(emitter._gen, old_value, field_type, receiver))
        if owned:
            sequence.append(adopt_edge_value(emitter._gen, new_value, field_type, receiver))
        else:
            sequence.append(retain_edge_value(emitter._gen, new_value, field_type, receiver))
        sequence.extend(
            [
                IRBinOp(left=target, op="=", right=new_value),
                release_edge_value(
                    emitter._gen,
                    old_value,
                    field_type,
                    replacement=new_value,
                ),
            ]
        )
    flush = poll_released_values(emitter._gen, field_type)
    if flush is not None:
        sequence.append(flush)
    sequence.append(target)
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=sequence),
    )


def _temporary(emitter, prefix: str, type_expr) -> IRVarDecl:
    declaration = IRVarDecl(
        c_type=CType(text=emitter.iter_value_c(type_expr)),
        name=emitter._fresh_temp(prefix),
    )
    emitter._func_var_decls.append(declaration)
    return declaration


__all__ = ["lower_generic_field_assignment"]
