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
from .gpu_arguments import backed_global_array, backed_static_field, bare_array_length, is_heap_collection
from .types import type_to_c

if TYPE_CHECKING:
    from .lowerer import IRLowerer


@dataclass
class GpuOutputTarget:
    declarations: list[IRVarDecl]
    assignments: list[IRExpr]
    cleanup: list[IRExpr]
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
    gen: IRLowerer,
    ast_target,
    ir_target: IRExpr,
) -> GpuOutputTarget:
    """Resolve writable data and a proven capacity for a direct assignment."""

    target_type = gen.analyzed.node_types.get(id(ast_target))
    if is_heap_collection(target_type):
        return collection_assignment_target(
            gen,
            ast_target,
            target_type,
            ir_target,
            render_type=type_to_c,
            fresh_temp=gen.fresh_temp,
            record_declaration=gen.context.function_declarations.append,
            cleanup_active=gen.exception_cleanup_active,
            activate_cleanup=gen.mark_cleanup_registration,
            owned=bool(id(ast_target) not in gen.context.owning_overrides and gen.ownership.owns_result(ast_target)),
        )

    if target_type is None or target_type.pointer_depth > 0:
        raise _unknown_capacity(ast_target)
    if not target_type.is_array:
        raise CodegenError("array-returning @gpu assignment requires an array or collection target")
    if isinstance(ast_target, Identifier):
        local_status = _local_c_array_status(gen, ast_target.name)
        if local_status is False:
            # Every array parameter uses pointer ABI, including source `T p[N]`.
            raise _unknown_capacity(ast_target)
        if local_status is None and not backed_global_array(gen, ast_target.name):
            raise _unknown_capacity(ast_target)
    elif target_type.array_size is None and not backed_static_field(gen, ast_target):
        raise _unknown_capacity(ast_target)
    if not isinstance(ast_target, Identifier):
        from .expressions import lower_expr

        return array_projection_assignment_target(
            ir_target,
            target_type,
            capacity=(
                lower_expr(gen, target_type.array_size)
                if target_type.array_size is not None
                else bare_array_length(ir_target)
            ),
            render_type=type_to_c,
            fresh_temp=gen.fresh_temp,
            record_declaration=gen.context.function_declarations.append,
        )
    return GpuOutputTarget(
        declarations=[],
        assignments=[],
        cleanup=[],
        data=ir_target,
        capacity=bare_array_length(ir_target),
    )


def array_projection_assignment_target(
    ir_target,
    target_type,
    *,
    capacity,
    render_type,
    fresh_temp,
    record_declaration,
) -> GpuOutputTarget:
    """Snapshot a nontrivial fixed-array LHS before RHS evaluation."""

    data_name = fresh_temp("__gpu_output_data")
    length_name = fresh_temp("__gpu_output_len")
    data_declaration = IRVarDecl(
        c_type=CType(text=render_type(target_type)),
        name=data_name,
    )
    length_declaration = IRVarDecl(
        c_type=CType(text="int"),
        name=length_name,
    )
    record_declaration(data_declaration)
    record_declaration(length_declaration)
    data = IRVar(name=data_name)
    length = IRVar(name=length_name)
    return GpuOutputTarget(
        declarations=[data_declaration, length_declaration],
        assignments=[
            IRBinOp(left=data, op="=", right=ir_target),
            IRBinOp(
                left=length,
                op="=",
                right=capacity,
            ),
        ],
        cleanup=[],
        data=data,
        capacity=length,
    )


def collection_assignment_target(
    gen,
    ast_target,
    target_type,
    ir_target,
    *,
    render_type,
    fresh_temp,
    record_declaration,
    cleanup_active,
    activate_cleanup,
    owned,
) -> GpuOutputTarget:
    """Pin the collection denoted by the LHS before lowering RHS effects."""

    temp_name = fresh_temp("__gpu_output_target")
    declaration = IRVarDecl(
        c_type=CType(text=render_type(target_type)),
        name=temp_name,
    )
    record_declaration(declaration)
    stable = IRVar(name=temp_name)
    declarations = [declaration]
    assignments = [IRBinOp(left=stable, op="=", right=ir_target)]
    if not owned:
        assignments.append(gen.lifetime.retain_value(stable, target_type))
    gen.lifetime.protect_temporary(
        declaration,
        target_type,
        declarations,
        assignments,
        "__btrc_gpu_output_cleanup",
        active=cleanup_active(),
        fresh_temp=fresh_temp,
        activate_cleanup=activate_cleanup,
    )
    cleanup = gen.lifetime.release_and_clear(
        stable,
        target_type,
        declarations,
        render_type(target_type),
        fresh_temp=fresh_temp,
        record_declaration=record_declaration,
    )
    from ...type_composition import add_outer_pointer

    data_name = fresh_temp("__gpu_output_data")
    length_name = fresh_temp("__gpu_output_len")
    data_declaration = IRVarDecl(
        c_type=CType(text=render_type(add_outer_pointer(target_type.generic_args[0]))),
        name=data_name,
    )
    length_declaration = IRVarDecl(
        c_type=CType(text="int"),
        name=length_name,
    )
    declarations.extend((data_declaration, length_declaration))
    record_declaration(data_declaration)
    record_declaration(length_declaration)
    data = IRVar(name=data_name)
    length = IRVar(name=length_name)
    assignments.extend(
        (
            IRBinOp(
                left=data,
                op="=",
                right=IRFieldAccess(obj=stable, field="data", arrow=True),
            ),
            IRBinOp(
                left=length,
                op="=",
                right=IRFieldAccess(obj=stable, field="len", arrow=True),
            ),
        )
    )
    return GpuOutputTarget(
        declarations=declarations,
        assignments=assignments,
        cleanup=cleanup,
        data=data,
        capacity=length,
    )


def _local_c_array_status(gen: IRLowerer, name: str) -> bool | None:
    from .c_array_scopes import local_c_array_status

    return local_c_array_status(gen, name)


def _unknown_capacity(ast_target) -> CodegenError:
    name = ast_target.name if isinstance(ast_target, Identifier) else "expression"
    return CodegenError(f"array-returning @gpu assignment target '{name}' has no provable writable capacity")
