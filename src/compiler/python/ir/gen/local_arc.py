"""Single-evaluation ARC replacement for owned local slots."""

from __future__ import annotations

from ...ast_nodes import AssignExpr, Identifier
from ..nodes import CType, IRBinOp, IRCommaExpr, IRStmtExpr, IRVar, IRVarDecl
from .arc_ops import poll_release_batch
from .managed_values import (
    is_class_type,
    is_managed_type,
    release_value,
    retain_value,
)
from .ownership import owns_result
from .types import type_to_c


def lower_managed_local_assignment(gen, node: AssignExpr):
    """Lower replacement of an owned local, or return None when borrowed."""
    if node.op != "=" or not isinstance(node.target, Identifier):
        return None
    if gen.managed_local_type(node.target.name) is None:
        return None
    target_type = gen.analyzed.node_types.get(id(node.target))
    if not is_managed_type(gen, target_type):
        return None

    from .expressions import lower_expr
    from .upcast import upcast_class_pointer
    from .updates import _lower_assignment_value

    value = _lower_assignment_value(gen, target_type, node.value)
    value_type = gen.analyzed.node_types.get(id(node.value))
    value = upcast_class_pointer(gen, target_type, value_type, value)

    new_decl = _temp_decl(gen, "__btrc_local_new", type_to_c(target_type))
    old_decl = _temp_decl(gen, "__btrc_local_old", type_to_c(target_type))
    new_value = IRVar(name=new_decl.name)
    old_value = IRVar(name=old_decl.name)
    target = lower_expr(gen, node.target)
    sequence = [
        IRBinOp(left=new_value, op="=", right=value),
        IRBinOp(left=old_value, op="=", right=target),
    ]
    # Retain first so ``slot = slot`` cannot destroy its own incoming value.
    if not owns_result(gen, node.value):
        sequence.append(retain_value(gen, new_value, target_type))
    sequence.extend(
        [
            release_value(gen, old_value, target_type),
            IRBinOp(left=target, op="=", right=new_value),
        ]
    )
    flush = poll_release_batch(
        gen,
        types=[target_type] if is_class_type(gen, target_type) else [],
    )
    if flush is not None:
        sequence.append(flush)
    sequence.append(target)
    return IRStmtExpr(
        stmts=[new_decl, old_decl],
        result=IRCommaExpr(expressions=sequence),
    )


def _temp_decl(gen, prefix: str, c_type: str) -> IRVarDecl:
    declaration = IRVarDecl(
        c_type=CType(text=c_type),
        name=gen.fresh_temp(prefix),
    )
    gen._func_var_decls.append(declaration)
    return declaration


__all__ = ["lower_managed_local_assignment"]
