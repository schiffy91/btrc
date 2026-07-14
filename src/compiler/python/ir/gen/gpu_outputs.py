"""Safe C storage targets for array-returning GPU dispatches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...ast_nodes import Identifier
from ..nodes import (
    CType,
    IRBinOp,
    IRExpr,
    IRFieldAccess,
    IRLiteral,
    IRTernary,
    IRVar,
    IRVarDecl,
)
from .errors import CodegenError
from .gpu_arguments import bare_array_length, is_heap_collection
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


@dataclass
class GpuOutputTarget:
    declarations: list[IRVarDecl]
    assignments: list[IRExpr]
    data: IRExpr
    capacity: IRExpr


def declaration_capacity(target: IRExpr) -> IRExpr:
    """Capacity of a C array after its declaration has fixed its extent."""

    return bare_array_length(target)


def safe_array_size(logical_length: IRExpr) -> IRExpr:
    """Allocate one element for an empty logical result; C11 forbids zero VLAs."""

    return IRTernary(
        condition=IRBinOp(
            left=logical_length,
            op=">",
            right=IRLiteral(text="0"),
        ),
        true_expr=logical_length,
        false_expr=IRLiteral(text="1"),
    )


def assignment_target(
    gen: IRGenerator,
    ast_target,
    ir_target: IRExpr,
) -> GpuOutputTarget:
    """Resolve writable data and a proven capacity for a direct assignment."""

    target_type = gen.analyzed.node_types.get(id(ast_target))
    if is_heap_collection(target_type):
        temp_name = gen.fresh_temp("__gpu_output_target")
        stable = IRVar(name=temp_name)
        return GpuOutputTarget(
            declarations=[
                IRVarDecl(
                    c_type=CType(text=type_to_c(target_type)),
                    name=temp_name,
                )
            ],
            assignments=[IRBinOp(left=stable, op="=", right=ir_target)],
            data=IRFieldAccess(obj=stable, field="data", arrow=True),
            capacity=IRFieldAccess(obj=stable, field="len", arrow=True),
        )

    if target_type is None or target_type.pointer_depth > 0:
        raise _unknown_capacity(ast_target)
    if not target_type.is_array:
        raise CodegenError("array-returning @gpu assignment requires an array or collection target")
    if (
        isinstance(ast_target, Identifier)
        and target_type.array_size is None
        and not _is_local_c_array(gen, ast_target.name)
    ):
        # An unsized array parameter is a C pointer at runtime. sizeof(param)
        # would report pointer width, not writable element capacity.
        raise _unknown_capacity(ast_target)
    if not isinstance(ast_target, Identifier) and target_type.array_size is None:
        raise _unknown_capacity(ast_target)
    return GpuOutputTarget(
        declarations=[],
        assignments=[],
        data=ir_target,
        capacity=bare_array_length(ir_target),
    )


def _is_local_c_array(gen: IRGenerator, name: str) -> bool:
    return any(name in scope for scope in reversed(gen._c_array_scopes))


def _unknown_capacity(ast_target) -> CodegenError:
    name = ast_target.name if isinstance(ast_target, Identifier) else "expression"
    return CodegenError(f"array-returning @gpu assignment target '{name}' has no provable writable capacity")
