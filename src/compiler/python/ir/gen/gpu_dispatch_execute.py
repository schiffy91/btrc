"""Structured execution, readback, cleanup, and recovery for GPU helpers."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRIf,
    IRLiteral,
    IRSizeof,
    IRVar,
    IRVarDecl,
)
from .gpu_arguments import buffer_length_name
from .gpu_dispatch_model import OUTPUT_PARAM, GpuDispatchSpec, wgsl_to_c
from .gpu_dispatch_status import (
    checked_failure_policy,
    checked_readback,
    post_dispatch_failure_policy,
    pre_dispatch_failure_policy,
    read_status,
    status_is_clear,
)
from .parameters import source_binding_c_name

_MAX_CHUNK_WORKGROUPS = 65535


def execution_and_recovery(spec: GpuDispatchSpec) -> list:
    names = spec.names
    statements = [
        IRVarDecl(
            c_type=CType(text="int"),
            name=names.chunk,
            init=IRLiteral(text=str(_MAX_CHUNK_WORKGROUPS * spec.kernel.workgroup_size)),
        ),
        IRIf(
            condition=IRVar(name=names.ok),
            then_block=IRBlock(
                stmts=[
                    _dispatch_loop(spec),
                    IRIf(
                        condition=IRVar(name=names.ok),
                        then_block=IRBlock(
                            stmts=[
                                read_status(spec),
                                IRIf(
                                    condition=IRBinOp(
                                        left=IRVar(name=names.ok),
                                        op="&&",
                                        right=status_is_clear(spec),
                                    ),
                                    then_block=IRBlock(stmts=_readback(spec)),
                                ),
                            ]
                        ),
                    ),
                ]
            ),
        ),
        *_cleanup(spec),
        checked_failure_policy(spec),
        post_dispatch_failure_policy(spec),
        pre_dispatch_failure_policy(spec),
    ]
    return statements


def _dispatch_loop(spec: GpuDispatchSpec) -> IRFor:
    names = spec.names
    offset = IRVar(name=names.offset)
    work_items = IRVar(name=names.work_items)
    chunk = IRVar(name=names.chunk)
    workgroup_size = spec.kernel.workgroup_size
    loop_body = IRBlock(
        stmts=[
            IRAssign(
                target=IRFieldAccess(
                    obj=IRVar(name=names.uniforms),
                    field="__gpu_off",
                ),
                value=offset,
            ),
            _call_stmt(
                "btrc_gpu_write_buffer",
                IRVar(name=names.gpu),
                IRVar(name=names.uniform_buffer),
                IRAddressOf(expr=IRVar(name=names.uniforms)),
                IRSizeof(operand=IRVar(name=names.uniforms)),
            ),
            IRVarDecl(
                c_type=CType(text="int"),
                name=names.work_items,
                init=IRBinOp(
                    left=IRVar(name=names.length),
                    op="-",
                    right=offset,
                ),
            ),
            IRIf(
                condition=IRBinOp(left=work_items, op=">", right=chunk),
                then_block=IRBlock(stmts=[IRAssign(target=work_items, value=chunk)]),
            ),
            IRVarDecl(
                c_type=CType(text="int"),
                name=names.workgroups,
                init=IRBinOp(
                    left=IRBinOp(
                        left=work_items,
                        op="+",
                        right=IRLiteral(text=str(workgroup_size - 1)),
                    ),
                    op="/",
                    right=IRLiteral(text=str(workgroup_size)),
                ),
            ),
            IRIf(
                condition=IRCall(
                    callee="btrc_gpu_dispatch",
                    args=[
                        IRVar(name=names.gpu),
                        IRVar(name=names.pipeline),
                        IRVar(name=names.bind_group),
                        IRVar(name=names.workgroups),
                    ],
                ),
                then_block=IRBlock(
                    stmts=[
                        IRAssign(
                            target=IRVar(name=names.dispatch_started),
                            value=IRLiteral(text="true"),
                        )
                    ]
                ),
                else_block=IRBlock(
                    stmts=[
                        IRAssign(
                            target=IRVar(name=names.ok),
                            value=IRLiteral(text="false"),
                        )
                    ]
                ),
            ),
        ]
    )
    return IRFor(
        init=IRVarDecl(
            c_type=CType(text="int"),
            name=names.offset,
            init=IRLiteral(text="0"),
        ),
        condition=IRBinOp(
            left=IRVar(name=names.ok),
            op="&&",
            right=IRBinOp(
                left=offset,
                op="<",
                right=IRVar(name=names.length),
            ),
        ),
        update=IRBinOp(left=offset, op="+=", right=chunk),
        body=loop_body,
    )


def _readback(spec: GpuDispatchSpec) -> list:
    names = spec.names
    if spec.has_output:
        element_type = spec.result_elem_type
        return [
            checked_readback(
                spec,
                IRVar(name=names.gpu),
                IRVar(name=names.output_buffer),
                IRVar(name=OUTPUT_PARAM),
                _buffer_size(IRVar(name=names.length), element_type),
            )
        ]

    statements = []
    for parameter in spec.declaration.params:
        if not (parameter.type and parameter.type.is_array):
            continue
        buffer = spec.buffer(parameter.name)
        if buffer.access != "read_write":
            continue
        statements.append(
            checked_readback(
                spec,
                IRVar(name=names.gpu),
                IRVar(name=names.buffer(buffer.name)),
                IRVar(name=source_binding_c_name(parameter.name, spec.analyzed)),
                _buffer_size(
                    IRVar(name=buffer_length_name(parameter.name)),
                    wgsl_to_c(buffer.elem_type),
                ),
            )
        )
    return statements


def _cleanup(spec: GpuDispatchSpec) -> list:
    names = spec.names
    statements = [
        _call_stmt(
            "btrc_gpu_buffer_destroy",
            IRVar(name=names.buffer(buffer.name)),
        )
        for buffer in spec.kernel.param_buffers
    ]
    if spec.has_output:
        statements.append(
            _call_stmt(
                "btrc_gpu_buffer_destroy",
                IRVar(name=names.output_buffer),
            )
        )
    statements.extend(
        [
            _call_stmt(
                "btrc_gpu_buffer_destroy",
                IRVar(name=names.status_buffer),
            ),
            _call_stmt(
                "btrc_gpu_buffer_destroy",
                IRVar(name=names.uniform_buffer),
            ),
            _call_stmt(
                "btrc_gpu_bind_group_destroy",
                IRVar(name=names.bind_group),
            ),
            _call_stmt(
                "btrc_gpu_compute_pipeline_destroy",
                IRVar(name=names.pipeline),
            ),
            _call_stmt(
                "btrc_gpu_shader_destroy",
                IRVar(name=names.shader),
            ),
        ]
    )
    return statements


def _buffer_size(length, element_type):
    return IRBinOp(
        left=length,
        op="*",
        right=IRSizeof(operand=CType(text=element_type)),
    )


def _call_stmt(callee, *args):
    return IRExprStmt(expr=IRCall(callee=callee, args=list(args)))
