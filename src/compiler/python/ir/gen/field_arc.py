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
    if node.op != "=" or not isinstance(node.target, FieldAccessExpr):
        return None
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

    value = _lower_value(gen, node.value, field_type)
    value_type = gen.analyzed.node_types.get(id(node.value))
    value = upcast_class_pointer(gen, field_type, value_type, value)
    value_decl = _temp_decl(gen, "__btrc_field_new", type_to_c(field_type), None)
    new_value = IRVar(name=value_decl.name)

    sequence = [
        IRBinOp(left=receiver, op="=", right=lower_expr(gen, node.target.obj)),
        IRBinOp(left=new_value, op="=", right=value),
    ]
    declarations = [receiver_decl, value_decl]
    owned = _is_owned_value(gen, node.value)
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
