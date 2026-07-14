"""Portable reference classification and nominal compatibility rules."""

from collections.abc import Mapping

from .ast_nodes import TypeExpr
from .type_identity import is_semantic_scalar_string

_EMPTY_MAPPING: Mapping[str, object] = {}


def is_scalar_string_type(type_expr: TypeExpr | None) -> bool:
    """Whether a type is one scalar btrc string (including collapsed ``?``)."""
    return is_semantic_scalar_string(type_expr)


def is_null_type(type_expr: TypeExpr | None) -> bool:
    return bool(
        type_expr and type_expr.base in {"null", "void"} and type_expr.pointer_depth > 0 and type_expr.is_nullable
    )


def is_c_string_pointer(type_expr: TypeExpr | None) -> bool:
    """Whether a C interop type is exactly one ``char`` pointer/array."""

    return bool(
        type_expr
        and type_expr.base == "char"
        and type_expr.pointer_depth + int(type_expr.is_array) == 1
        and not type_expr.generic_args
    )


def is_reference_type(
    type_expr: TypeExpr | None,
    class_table: Mapping[str, object] = _EMPTY_MAPPING,
    interface_table: Mapping[str, object] = _EMPTY_MAPPING,
) -> bool:
    if type_expr is None:
        return False
    if is_null_type(type_expr) or is_scalar_string_type(type_expr):
        return True
    return bool(
        type_expr.pointer_depth > 0
        or type_expr.is_array
        or type_expr.base in class_table
        or type_expr.base in interface_table
        or type_expr.base in {"Thread", "Mutex", "__fn_ptr"}
    )


def reference_types_compatible(
    left: TypeExpr | None,
    right: TypeExpr | None,
    class_table: Mapping[str, object] = _EMPTY_MAPPING,
    interface_table: Mapping[str, object] = _EMPTY_MAPPING,
) -> bool:
    if is_null_type(left):
        return is_reference_type(right, class_table, interface_table)
    if is_null_type(right):
        return is_reference_type(left, class_table, interface_table)
    if not (
        is_reference_type(left, class_table, interface_table) and is_reference_type(right, class_table, interface_table)
    ):
        return False
    assert left is not None and right is not None
    if left.base == "__fn_ptr" or right.base == "__fn_ptr":
        return left.base == right.base == "__fn_ptr" and left.generic_args == right.generic_args
    if _is_void_pointer(left) or _is_void_pointer(right):
        return True
    if (is_scalar_string_type(left) and is_c_string_pointer(right)) or (
        is_scalar_string_type(right) and is_c_string_pointer(left)
    ):
        return True
    if _reference_depth(left) != _reference_depth(right):
        return False
    if left.base == right.base:
        return left.generic_args == right.generic_args
    if (left.base not in class_table and left.base not in interface_table) or (
        right.base not in class_table and right.base not in interface_table
    ):
        return False
    return _nominal_specializations_related(left, right, class_table, interface_table)


def nominally_related(
    left: str,
    right: str,
    class_table: Mapping[str, object],
    interface_table: Mapping[str, object],
) -> bool:
    return _is_nominal_subtype(left, right, class_table, interface_table) or _is_nominal_subtype(
        right, left, class_table, interface_table
    )


def _reference_depth(type_expr: TypeExpr) -> int:
    return type_expr.pointer_depth + int(type_expr.is_array)


def _is_void_pointer(type_expr: TypeExpr) -> bool:
    return type_expr.base == "void" and _reference_depth(type_expr) == 1


def _nominal_specializations_related(
    left: TypeExpr,
    right: TypeExpr,
    class_table: Mapping[str, object],
    interface_table: Mapping[str, object],
) -> bool:
    return _specialization_is_subtype(left, right, class_table, interface_table) or _specialization_is_subtype(
        right, left, class_table, interface_table
    )


def _specialization_is_subtype(
    child: TypeExpr,
    parent: TypeExpr,
    class_table: Mapping[str, object],
    interface_table: Mapping[str, object],
) -> bool:
    pending = [(child.base, tuple(child.generic_args))]
    seen = set()
    while pending:
        name, args = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if name == parent.base:
            return args == tuple(parent.generic_args)
        info = class_table.get(name) or interface_table.get(name)
        if info is None:
            continue
        for ancestor in (getattr(info, "parent", None), *(getattr(info, "interfaces", ()) or ())):
            if not ancestor:
                continue
            ancestor_info = class_table.get(ancestor) or interface_table.get(ancestor)
            if ancestor_info is None:
                continue
            ancestor_arity = len(getattr(ancestor_info, "generic_params", ()))
            current_arity = len(getattr(info, "generic_params", ()))
            if ancestor_arity == 0:
                ancestor_args = ()
            elif ancestor_arity == current_arity == len(args):
                ancestor_args = args
            else:
                continue
            pending.append((ancestor, ancestor_args))
    return False


def _is_nominal_subtype(
    child: str,
    parent: str,
    class_table: Mapping[str, object],
    interface_table: Mapping[str, object],
) -> bool:
    pending = [child]
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if name == parent:
            return True
        info = class_table.get(name) or interface_table.get(name)
        if info is None:
            continue
        direct_parent = getattr(info, "parent", None)
        if direct_parent:
            pending.append(direct_parent)
        pending.extend(getattr(info, "interfaces", ()) or ())
    return False
