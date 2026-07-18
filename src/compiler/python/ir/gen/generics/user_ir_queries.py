"""Structural queries over monomorphized generic-method IR."""

from __future__ import annotations

import dataclasses

from ....ast_nodes import CallExpr, FieldAccessExpr
from ....type_identity import generic_instance_key
from ...nodes import (
    IRBinOp,
    IRCall,
    IRFieldAccess,
    IRFunctionDef,
    IRIndex,
    IRParam,
    IRVar,
    IRVarDecl,
)
from ...optimizer_walk import iter_ir_nodes


def called_callees(root: object) -> set[str]:
    """Return every structured call target below ``root``."""
    return {node.callee for node in iter_ir_nodes(root) if isinstance(node, IRCall) and isinstance(node.callee, str)}


def referenced_helpers(root: object, candidates: set[str]) -> set[str]:
    """Return helper names referenced by structured call metadata."""
    references = set()
    for node in iter_ir_nodes(root):
        if isinstance(node, IRCall) and isinstance(node.callee, str):
            if node.callee in candidates:
                references.add(node.callee)
            if node.helper_ref in candidates:
                references.add(node.helper_ref)
    return references


def called_generic_methods(
    program,
    node_types: dict[int, object],
    base: str,
    args,
) -> set[str]:
    """Return methods called on one concrete generic specialization."""
    expected = generic_instance_key(base, args)
    result = set()
    for node in _iter_ast(program):
        if not isinstance(node, CallExpr) or not isinstance(node.callee, FieldAccessExpr):
            continue
        receiver_type = node_types.get(id(node.callee.obj))
        if (
            receiver_type is not None
            and generic_instance_key(receiver_type.base, receiver_type.generic_args) == expected
        ):
            result.add(node.callee.field)
    return result


def _iter_ast(value):
    if dataclasses.is_dataclass(value):
        yield value
        for field in dataclasses.fields(value):
            yield from _iter_ast(getattr(value, field.name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_ast(item)


def is_type_incompatible(function: IRFunctionDef, element_c_type: str) -> bool:
    """Whether a generic method requires operations invalid for its element."""
    normalized = _normalize_c_type(element_c_type)
    if normalized not in {"char*", "constchar*"}:
        element_vars = _element_variables(function, normalized)
        if _uses_element_as_string_memory(function, element_vars):
            return True
    if not normalized.endswith("*"):
        return False
    element_vars = _element_variables(function, normalized)
    return any(
        isinstance(node, IRBinOp) and node.op in {"+", "+="} and _adds_element_pointers(node, element_vars)
        for node in iter_ir_nodes(function)
    )


def _normalize_c_type(c_type: str) -> str:
    return "".join(c_type.split())


def _element_variables(function: IRFunctionDef, normalized: str) -> set[str]:
    variables = {
        node.name
        for node in iter_ir_nodes(function)
        if isinstance(node, (IRParam, IRVarDecl)) and _normalize_c_type(node.c_type.text) == normalized
    }
    variables.discard("self")
    return variables


def _is_self_field(node: object) -> bool:
    return isinstance(node, IRFieldAccess) and isinstance(node.obj, IRVar) and node.obj.name == "self" and node.arrow


def _is_self_data_element(node: object) -> bool:
    return (
        isinstance(node, IRIndex)
        and isinstance(node.obj, IRFieldAccess)
        and node.obj.field == "data"
        and _is_self_field(node.obj)
    )


def _contains_element_value(root: object, element_vars: set[str]) -> bool:
    return any(
        _is_self_field(node) or (isinstance(node, IRVar) and node.name in element_vars) for node in iter_ir_nodes(root)
    )


def _uses_element_as_string_memory(
    function: IRFunctionDef,
    element_vars: set[str],
) -> bool:
    for node in iter_ir_nodes(function):
        if (
            not isinstance(node, IRCall)
            or not isinstance(node.callee, str)
            or node.callee not in {"strlen", "memcpy", "__btrc_string_length"}
        ):
            continue
        if any(_contains_element_value(arg, element_vars) for arg in node.args):
            return True
    return False


def _is_element_pointer(node: object, element_vars: set[str]) -> bool:
    return _is_self_data_element(node) or (isinstance(node, IRVar) and node.name in element_vars)


def _adds_element_pointers(node: IRBinOp, element_vars: set[str]) -> bool:
    return _is_element_pointer(node.left, element_vars) and _is_element_pointer(node.right, element_vars)
