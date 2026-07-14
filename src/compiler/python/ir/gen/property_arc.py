"""Ownership transfer for compiler-generated auto-property setters."""

from __future__ import annotations

from ...ast_nodes import AssignExpr, FieldAccessExpr, SelfExpr
from ...class_storage import property_needs_backing
from ..nodes import CType, IRBinOp, IRCall, IRCommaExpr, IRStmtExpr, IRVar, IRVarDecl
from .managed_values import (
    is_managed_type,
    poll_released_values,
    release_value,
)
from .ownership import owns_result
from .types import mangle_generic_type, type_to_c


def lower_managed_property_assignment(gen, node: AssignExpr):
    """Lower an auto-property store, or return None for other properties."""
    if node.op != "=" or not isinstance(node.target, FieldAccessExpr):
        return None
    if isinstance(node.target.obj, SelfExpr) and gen.current_property_backing == node.target.field:
        return None
    receiver_type = gen.analyzed.node_types.get(id(node.target.obj))
    if receiver_type is None:
        return None
    class_info = gen.analyzed.class_table.get(receiver_type.base)
    if class_info is None:
        return None
    prop = class_info.properties.get(node.target.field)
    if (
        prop is None
        or prop.setter_body is not None
        or not property_needs_backing(prop)
        or not is_managed_type(gen, prop.type)
    ):
        return None

    from .expressions import lower_expr
    from .upcast import upcast_class_pointer
    from .updates import _lower_assignment_value

    value = _lower_assignment_value(gen, prop.type, node.value)
    value_type = gen.analyzed.node_types.get(id(node.value))
    value = upcast_class_pointer(gen, prop.type, value_type, value)
    receiver_decl = _temp_decl(
        gen,
        "__btrc_property_obj",
        type_to_c(receiver_type),
    )
    value_decl = _temp_decl(gen, "__btrc_property_new", type_to_c(prop.type))
    receiver = IRVar(name=receiver_decl.name)
    new_value = IRVar(name=value_decl.name)
    prefix = receiver_type.base
    if receiver_type.generic_args and class_info.generic_params:
        prefix = mangle_generic_type(receiver_type.base, receiver_type.generic_args)

    sequence = [
        IRBinOp(left=receiver, op="=", right=lower_expr(gen, node.target.obj)),
        IRBinOp(left=new_value, op="=", right=value),
        IRCall(
            callee=f"{prefix}_set_{node.target.field}",
            args=[receiver, new_value],
        ),
    ]
    # The setter retains its input. Drop the expression's original +1 so the
    # backing slot becomes the sole owner of a fresh temporary.
    if owns_result(gen, node.value):
        sequence.append(release_value(gen, new_value, prop.type))
        flush = poll_released_values(gen, prop.type)
        if flush is not None:
            sequence.append(flush)
    sequence.append(new_value)
    return IRStmtExpr(
        stmts=[receiver_decl, value_decl],
        result=IRCommaExpr(expressions=sequence),
    )


def _temp_decl(gen, prefix: str, c_type: str) -> IRVarDecl:
    declaration = IRVarDecl(
        c_type=CType(text=c_type),
        name=gen.fresh_temp(prefix),
    )
    gen._func_var_decls.append(declaration)
    return declaration


__all__ = ["lower_managed_property_assignment"]
