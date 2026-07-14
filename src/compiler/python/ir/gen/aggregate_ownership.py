"""Fail-closed ownership checks for shallow by-value aggregates."""

from __future__ import annotations

from dataclasses import replace

from ...ast_nodes import FieldAccessExpr, Identifier, IndexExpr
from .errors import CodegenError
from .ownership import owns_result


def reject_owned_elements(gen, elements, aggregate: str) -> None:
    """Reject +1 values that a shallow aggregate cannot later release."""
    for element in elements:
        if owns_result(gen, element):
            raise CodegenError(
                f"caller-owned temporary cannot be embedded in {aggregate}; "
                "aggregate class elements are shallow borrowed references, "
                "so bind the owner to a local first"
            )


def reject_shallow_initializer(gen, node, node_type=None) -> None:
    """Validate a brace/list initializer when its target is non-owning."""
    node_type = node_type or gen.analyzed.node_types.get(id(node))
    canonical = _canonical_type(node_type, gen.analyzed.typedef_table)
    if canonical is None:
        return
    struct_name = canonical.base.removeprefix("struct ")
    shallow = bool(canonical.is_array or canonical.base == "Tuple" or struct_name in gen.analyzed.struct_table)
    if shallow:
        reject_owned_elements(gen, node.elements, "a shallow aggregate")


def reject_rich_enum_owned_args(gen, call) -> None:
    """Reject owned payloads passed into a shallow tagged union variant."""
    callee = call.callee
    if not isinstance(callee, FieldAccessExpr):
        return
    if not isinstance(callee.obj, Identifier):
        return
    if callee.obj.name not in gen.analyzed.rich_enum_table:
        return
    reject_owned_elements(
        gen,
        call.args,
        f"rich-enum payload '{callee.obj.name}.{callee.field}'",
    )


def reject_shallow_store(gen, assignment) -> None:
    """Reject replacing shallow aggregate storage with a +1 temporary."""
    target = assignment.target
    if not isinstance(target, (FieldAccessExpr, IndexExpr)) or not owns_result(
        gen,
        assignment.value,
    ):
        return
    receiver_type = gen.analyzed.node_types.get(id(target.obj))
    if receiver_type is None:
        return
    canonical = _canonical_type(
        receiver_type,
        gen.analyzed.typedef_table,
    )
    if canonical is None:
        return
    struct_name = canonical.base.removeprefix("struct ")
    if canonical.is_array or canonical.base == "Tuple" or struct_name in gen.analyzed.struct_table:
        raise CodegenError(
            "caller-owned temporary cannot be stored in a shallow aggregate; "
            "bind the owner to a local and store only its borrowed reference"
        )


def _canonical_type(type_expr, typedefs):
    if type_expr is None:
        return None
    result = type_expr
    seen = set()
    while result.base in typedefs and result.base not in seen:
        seen.add(result.base)
        target = typedefs[result.base]
        result = replace(
            target,
            pointer_depth=target.pointer_depth + result.pointer_depth,
            is_array=target.is_array or result.is_array,
            array_size=result.array_size or target.array_size,
        )
    return result


__all__ = [
    "reject_owned_elements",
    "reject_rich_enum_owned_args",
    "reject_shallow_initializer",
    "reject_shallow_store",
]
