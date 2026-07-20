"""Structured uniform, shader, pipeline, and bind-group setup."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRFieldAccess,
    IRIf,
    IRIndex,
    IRLiteral,
    IRSizeof,
    IRVar,
    IRVarDecl,
)
from .gpu_arguments import buffer_length_name
from .gpu_dispatch_model import GpuDispatchSpec
from .gpu_dispatch_setup import mark_failed_if_null
from .parameters import source_binding_c_name


def uniforms_and_pipeline(spec: GpuDispatchSpec) -> list:
    names = spec.names
    ok = IRVar(name=names.ok)
    gpu = IRVar(name=names.gpu)
    uniforms = IRVar(name=names.uniforms)
    uniform_buffer = IRVar(name=names.uniform_buffer)
    shader = IRVar(name=names.shader)
    pipeline = IRVar(name=names.pipeline)
    statements = [
        IRVarDecl(
            c_type=CType(text=f"struct {spec.uniform_struct}"),
            name=names.uniforms,
        )
    ]
    for parameter in spec.declaration.params:
        if parameter.type and parameter.type.is_array:
            continue
        statements.append(
            IRAssign(
                target=_uniform_field(
                    names,
                    source_binding_c_name(parameter.name),
                ),
                value=IRVar(name=source_binding_c_name(parameter.name, spec.analyzed)),
            )
        )
    for buffer in spec.kernel.param_buffers:
        length_name = buffer_length_name(buffer.name)
        statements.append(
            IRAssign(
                target=_uniform_field(names, length_name),
                value=IRVar(name=length_name),
            )
        )
    statements.extend(
        [
            IRAssign(
                target=_uniform_field(names, "__gpu_n"),
                value=IRVar(name=names.length),
            ),
            IRVarDecl(
                c_type=CType(text="void*"),
                name=names.uniform_buffer,
                init=IRLiteral(text="NULL"),
            ),
            IRIf(
                condition=ok,
                then_block=IRBlock(
                    stmts=[
                        IRAssign(
                            target=uniform_buffer,
                            value=IRCall(
                                callee="btrc_gpu_create_buffer",
                                args=[
                                    gpu,
                                    IRSizeof(operand=uniforms),
                                    IRBinOp(
                                        left=IRVar(name="BTRC_GPU_UNIFORM"),
                                        op="|",
                                        right=IRVar(name="BTRC_GPU_COPY_DST"),
                                    ),
                                ],
                            ),
                        )
                    ]
                ),
            ),
            mark_failed_if_null(names.uniform_buffer, names.ok),
            IRVarDecl(
                c_type=CType(text="void*"),
                name=names.shader,
                init=IRLiteral(text="NULL"),
            ),
            IRIf(
                condition=ok,
                then_block=IRBlock(
                    stmts=[
                        IRAssign(
                            target=shader,
                            value=IRCall(
                                callee="btrc_gpu_create_shader",
                                args=[
                                    gpu,
                                    IRCast(
                                        target_type=CType(text="char*"),
                                        expr=IRVar(name=f"{spec.kernel.name}_wgsl"),
                                    ),
                                ],
                            ),
                        )
                    ]
                ),
            ),
            mark_failed_if_null(names.shader, names.ok),
            IRVarDecl(
                c_type=CType(text="void*"),
                name=names.pipeline,
                init=IRLiteral(text="NULL"),
            ),
            IRIf(
                condition=ok,
                then_block=IRBlock(
                    stmts=[
                        IRAssign(
                            target=pipeline,
                            value=IRCall(
                                callee="btrc_gpu_create_compute_pipeline",
                                args=[gpu, shader, IRLiteral(text='"main"')],
                            ),
                        )
                    ]
                ),
            ),
            mark_failed_if_null(names.pipeline, names.ok),
        ]
    )
    return statements


def bind_group(spec: GpuDispatchSpec) -> list:
    names = spec.names
    bindings = IRVar(name=names.bindings)
    statements = [
        IRVarDecl(
            c_type=CType(text="void*"),
            name=names.bindings,
            array_size=IRLiteral(text=str(spec.total_bindings)),
        )
    ]
    binding_index = 0
    for buffer in spec.kernel.param_buffers:
        statements.append(
            IRAssign(
                target=IRIndex(
                    obj=bindings,
                    index=IRLiteral(text=str(binding_index)),
                ),
                value=IRVar(name=names.buffer(buffer.name)),
            )
        )
        binding_index += 1
    if spec.has_output:
        statements.append(
            IRAssign(
                target=IRIndex(
                    obj=bindings,
                    index=IRLiteral(text=str(binding_index)),
                ),
                value=IRVar(name=names.output_buffer),
            )
        )
        binding_index += 1
    statements.extend(
        [
            IRAssign(
                target=IRIndex(
                    obj=bindings,
                    index=IRLiteral(text=str(binding_index)),
                ),
                value=IRVar(name=names.uniform_buffer),
            ),
            IRAssign(
                target=IRIndex(
                    obj=bindings,
                    index=IRLiteral(text=str(binding_index + 1)),
                ),
                value=IRVar(name=names.status_buffer),
            ),
            IRVarDecl(
                c_type=CType(text="void*"),
                name=names.bind_group,
                init=IRLiteral(text="NULL"),
            ),
            IRIf(
                condition=IRVar(name=names.ok),
                then_block=IRBlock(
                    stmts=[
                        IRAssign(
                            target=IRVar(name=names.bind_group),
                            value=IRCall(
                                callee="btrc_gpu_create_bind_group",
                                args=[
                                    IRVar(name=names.gpu),
                                    IRVar(name=names.pipeline),
                                    bindings,
                                    IRLiteral(text=str(spec.total_bindings)),
                                ],
                            ),
                        )
                    ]
                ),
            ),
            mark_failed_if_null(names.bind_group, names.ok),
        ]
    )
    return statements


def _uniform_field(names, field):
    return IRFieldAccess(
        obj=IRVar(name=names.uniforms),
        field=field,
    )
