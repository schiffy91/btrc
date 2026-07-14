"""Single-evaluation ARC replacement for owned local slots."""

from __future__ import annotations

from ...ast_nodes import AssignExpr, Identifier
from ..nodes import IRBinOp
from .managed_values import is_managed_type
from .ownership import owns_result
from .types import type_to_c


def lower_managed_local_assignment(gen, node: AssignExpr):
    """Lower replacement of an owned local, or return None when borrowed."""
    if not isinstance(node.target, Identifier):
        return None
    target_type = gen.analyzed.node_types.get(id(node.target))
    if not _owned_identifier_slot(gen, node.target, target_type):
        return None
    if not is_managed_type(gen, target_type):
        return None

    from .expressions import lower_expr

    target = lower_expr(gen, node.target)
    return lower_managed_slot_assignment(gen, node, target, target_type)


def lower_managed_slot_assignment(gen, node, target, target_type):
    """Replace one persistent non-edge slot (local, global, or static)."""
    from .upcast import upcast_class_pointer
    from .updates import _lower_assignment_value

    if node.op != "=":
        return _lower_managed_slot_compound(gen, node, target, target_type)
    value = _lower_assignment_value(gen, target_type, node.value)
    value_type = gen.analyzed.node_types.get(id(node.value))
    value = upcast_class_pointer(gen, target_type, value_type, value)
    owned = owns_result(gen, node.value)
    from .managed_replacement import lower_managed_slot_replacement

    return lower_managed_slot_replacement(
        gen,
        target=target,
        target_type=target_type,
        value=value,
        value_owned=owned,
        c_type=type_to_c,
        fresh_temp=gen.fresh_temp,
        record_decl=gen._func_var_decls.append,
        cleanup_active=gen.exception_cleanup_active(),
    )


def _lower_managed_slot_compound(gen, node, target, target_type):
    from .managed_compound import (
        lower_managed_compound_operator,
        managed_compound_keeps_rhs,
    )
    from .managed_updates import lower_managed_compound_update
    from .updates import _lower_assignment_value

    right_type = gen.analyzed.node_types.get(id(node.value)) or target_type
    return lower_managed_compound_update(
        gen,
        value_type=target_type,
        right_type=right_type,
        old_expr=target,
        right_expr=_lower_assignment_value(gen, target_type, node.value),
        compute=lambda old, right: lower_managed_compound_operator(
            gen,
            node,
            old,
            right,
            target_type,
            right_type,
            fresh_temp=gen.fresh_temp,
        ),
        commit=lambda _old, replacement: [IRBinOp(left=target, op="=", right=replacement)],
        result_expr=lambda: target,
        old_temporary_owned=False,
        right_owned=bool(is_managed_type(gen, right_type) and owns_result(gen, node.value)),
        right_keep=managed_compound_keeps_rhs(gen, target_type, node.op[:-1]),
        release_replaced_old=True,
        commit_releases_old=False,
        result_owned=False,
        c_type=type_to_c,
        fresh_temp=gen.fresh_temp,
        record_decl=gen._func_var_decls.append,
        cleanup_active=gen.exception_cleanup_active(),
    )


def _owned_identifier_slot(gen, target: Identifier, target_type) -> bool:
    if gen.managed_local_type(target.name) is not None:
        return True
    if gen.local_ownership_declared(target.name):
        return False
    from ...ast_nodes import VarDeclStmt

    return bool(
        any(
            isinstance(declaration, VarDeclStmt)
            and declaration.name == target.name
            and not (declaration.type is not None and declaration.type.is_extern and declaration.initializer is None)
            for declaration in gen.analyzed.program.declarations
        )
    )


__all__ = ["lower_managed_local_assignment", "lower_managed_slot_assignment"]
