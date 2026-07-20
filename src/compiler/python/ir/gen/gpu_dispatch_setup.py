"""Structured context and storage-buffer setup for GPU dispatch helpers."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRIf,
    IRLiteral,
    IRSizeof,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .gpu_arguments import buffer_length_name
from .gpu_dispatch_model import (
    OUTPUT_CAPACITY,
    OUTPUT_PARAM,
    GpuDispatchSpec,
    wgsl_to_c,
)
from .gpu_dispatch_status import create_status_buffer, status_declaration
from .parameters import source_binding_c_name


def initial_state(spec: GpuDispatchSpec) -> list:
    names = spec.names
    ok = IRVar(name=names.ok)
    gpu = IRVar(name=names.gpu)
    statements = [
        IRVarDecl(
            c_type=CType(text="void*"),
            name=names.gpu,
            init=IRLiteral(text="NULL"),
        ),
        IRVarDecl(
            c_type=CType(text="int"),
            name=names.length,
            init=spec.dispatch_length(),
        ),
        status_declaration(spec),
        IRVarDecl(
            c_type=CType(text="bool"),
            name=names.dispatch_started,
            init=IRLiteral(text="false"),
        ),
    ]
    if spec.has_output:
        statements.append(_capacity_guard(names.length))
    statements.extend(
        [
            IRVarDecl(
                c_type=CType(text="bool"),
                name=names.ok,
                init=IRBinOp(
                    left=IRVar(name=names.length),
                    op=">",
                    right=IRLiteral(text="0"),
                ),
            ),
            IRIf(
                condition=ok,
                then_block=IRBlock(
                    stmts=[
                        IRAssign(
                            target=gpu,
                            value=IRCall(callee="btrc_gpu_acquire_compute"),
                        )
                    ]
                ),
            ),
            mark_failed_if_null(names.gpu, names.ok),
        ]
    )
    return statements


def _capacity_guard(length_name: str) -> IRIf:
    invalid_target = IRBinOp(
        left=IRUnaryOp(op="!", operand=IRVar(name=OUTPUT_PARAM)),
        op="||",
        right=IRBinOp(
            left=IRVar(name=OUTPUT_CAPACITY),
            op="<",
            right=IRVar(name=length_name),
        ),
    )
    return IRIf(
        condition=IRBinOp(
            left=IRBinOp(
                left=IRVar(name=length_name),
                op=">",
                right=IRLiteral(text="0"),
            ),
            op="&&",
            right=invalid_target,
        ),
        then_block=IRBlock(
            stmts=[
                call_stmt(
                    "fputs",
                    IRLiteral(text=('"[btrc-gpu] output capacity is smaller than dispatch length\\n"')),
                    IRVar(name="stderr"),
                ),
                call_stmt("abort"),
            ]
        ),
    )


def storage_buffers(spec: GpuDispatchSpec) -> list:
    names = spec.names
    statements = []
    for parameter in spec.declaration.params:
        if not (parameter.type and parameter.type.is_array):
            continue
        buffer = spec.buffer(parameter.name)
        statements.extend(
            _create_storage_buffer(
                spec,
                names.buffer(buffer.name),
                IRVar(name=source_binding_c_name(parameter.name, spec.analyzed)),
                IRVar(name=buffer_length_name(parameter.name)),
                wgsl_to_c(buffer.elem_type),
                read_write=buffer.access == "read_write",
            )
        )

    if spec.has_output:
        statements.extend(
            _create_output_buffer(
                spec,
                wgsl_to_c(spec.kernel.output_buffer.elem_type),
            )
        )
    statements.extend(create_status_buffer(spec))
    return statements


def _create_storage_buffer(
    spec,
    handle_name,
    source,
    length,
    element_type,
    *,
    read_write,
):
    names = spec.names
    handle = IRVar(name=handle_name)
    size = buffer_size(length, element_type)
    usage = IRBinOp(
        left=IRVar(name="BTRC_GPU_STORAGE"),
        op="|",
        right=IRVar(name="BTRC_GPU_COPY_DST"),
    )
    if read_write:
        usage = IRBinOp(
            left=usage,
            op="|",
            right=IRVar(name="BTRC_GPU_COPY_SRC"),
        )
    return [
        IRVarDecl(
            c_type=CType(text="void*"),
            name=handle_name,
            init=IRLiteral(text="NULL"),
        ),
        IRIf(
            condition=IRVar(name=names.ok),
            then_block=IRBlock(
                stmts=[
                    IRAssign(
                        target=handle,
                        value=IRCall(
                            callee="btrc_gpu_create_buffer",
                            args=[IRVar(name=names.gpu), size, usage],
                        ),
                    )
                ]
            ),
        ),
        mark_failed_if_null(handle_name, names.ok),
        IRIf(
            condition=IRVar(name=names.ok),
            then_block=IRBlock(
                stmts=[
                    call_stmt(
                        "btrc_gpu_write_buffer",
                        IRVar(name=names.gpu),
                        handle,
                        source,
                        size,
                    )
                ]
            ),
        ),
    ]


def _create_output_buffer(spec, element_type):
    names = spec.names
    usage = IRBinOp(
        left=IRBinOp(
            left=IRVar(name="BTRC_GPU_STORAGE"),
            op="|",
            right=IRVar(name="BTRC_GPU_COPY_DST"),
        ),
        op="|",
        right=IRVar(name="BTRC_GPU_COPY_SRC"),
    )
    return [
        IRVarDecl(
            c_type=CType(text="void*"),
            name=names.output_buffer,
            init=IRLiteral(text="NULL"),
        ),
        IRIf(
            condition=IRVar(name=names.ok),
            then_block=IRBlock(
                stmts=[
                    IRAssign(
                        target=IRVar(name=names.output_buffer),
                        value=IRCall(
                            callee="btrc_gpu_create_buffer",
                            args=[
                                IRVar(name=names.gpu),
                                buffer_size(
                                    IRVar(name=names.length),
                                    element_type,
                                ),
                                usage,
                            ],
                        ),
                    )
                ]
            ),
        ),
        mark_failed_if_null(names.output_buffer, names.ok),
    ]


def buffer_size(length, element_type):
    return IRBinOp(
        left=length,
        op="*",
        right=IRSizeof(operand=CType(text=element_type)),
    )


def mark_failed_if_null(handle_name, ok_name):
    return IRIf(
        condition=IRUnaryOp(op="!", operand=IRVar(name=handle_name)),
        then_block=IRBlock(
            stmts=[
                IRAssign(
                    target=IRVar(name=ok_name),
                    value=IRLiteral(text="false"),
                )
            ]
        ),
    )


def call_stmt(callee, *args):
    return IRExprStmt(expr=IRCall(callee=callee, args=list(args)))
