"""Call-site lowering into ordinary calls to structured GPU dispatch helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...ast_nodes import CallExpr, Identifier
from ..nodes import (
    CType,
    IRBlock,
    IRCall,
    IRCommaExpr,
    IRExpr,
    IRFunctionDef,
    IRStmtExpr,
    IRStructDef,
    IRStructField,
)
from .errors import CodegenError
from .gpu_arguments import (
    GpuArgumentPlan,
    buffer_length_name,
    prepare_gpu_arguments,
)
from .gpu_dispatch_execute import execution_and_recovery
from .gpu_dispatch_model import GpuDispatchSpec
from .gpu_dispatch_pipeline import (
    bind_group,
    uniforms_and_pipeline,
)
from .gpu_dispatch_setup import initial_state, storage_buffers
from .gpu_outputs import assignment_target, declaration_capacity
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


@dataclass
class GpuOutputDeclaration:
    setup: list
    array_length: IRExpr | None
    call: IRCall


def lower_gpu_call(
    gen: IRGenerator,
    function_name: str,
    ast_args: list,
    arg_names: list[str],
    ir_args: list[IRExpr],
) -> IRExpr:
    """Lower a void kernel call or reject an unsafe array-valued context."""

    kernel = gen._gpu_kernels[function_name]
    if kernel.output_buffer is not None:
        raise CodegenError(
            f"array-returning @gpu call '{function_name}' is only valid as "
            "an array declaration initializer or direct array assignment"
        )
    spec, arguments = _prepare_site(
        gen,
        function_name,
        ast_args,
        arg_names,
        ir_args,
    )
    call = IRCall(callee=spec.helper_name, args=arguments.helper_args)
    return _expression_local_call(arguments, call)


def output_gpu_call_name(gen: IRGenerator, expression) -> str | None:
    if not (isinstance(expression, CallExpr) and isinstance(expression.callee, Identifier)):
        return None
    name = expression.callee.name
    kernel = getattr(gen, "_gpu_kernels", {}).get(name)
    if kernel is None or kernel.output_buffer is None:
        return None
    return name


def lower_gpu_output_declaration(
    gen: IRGenerator,
    call: CallExpr,
    target: IRExpr,
) -> GpuOutputDeclaration:
    """Lower an output kernel used to initialize a C array declaration."""

    from .arguments import lower_arg_values

    name = output_gpu_call_name(gen, call)
    if name is None:
        raise CodegenError("expected an array-returning @gpu call")
    spec, arguments = _prepare_site(
        gen,
        name,
        call.args,
        _arg_names(call),
        lower_arg_values(gen, call.args),
    )
    helper_call = IRCall(
        callee=spec.helper_name,
        args=[
            *arguments.helper_args,
            target,
            declaration_capacity(target),
        ],
    )
    return GpuOutputDeclaration(
        setup=arguments.initialized_declarations,
        array_length=arguments.dispatch_length,
        call=helper_call,
    )


def lower_gpu_output_assignment(
    gen: IRGenerator,
    call: CallExpr,
    ast_target,
    target: IRExpr,
) -> IRExpr:
    """Lower direct output readback through an existing array lvalue."""

    from .arguments import lower_arg_values

    name = output_gpu_call_name(gen, call)
    if name is None:
        raise CodegenError("expected an array-returning @gpu call")
    spec, arguments = _prepare_site(
        gen,
        name,
        call.args,
        _arg_names(call),
        lower_arg_values(gen, call.args),
    )
    output = assignment_target(gen, ast_target, target)
    arguments.declarations.extend(output.declarations)
    arguments.assignments.extend(output.assignments)
    helper_call = IRCall(
        callee=spec.helper_name,
        args=[*arguments.helper_args, output.data, output.capacity],
    )
    return _expression_local_call(arguments, helper_call)


def _prepare_site(
    gen: IRGenerator,
    function_name: str,
    ast_args: list,
    arg_names: list[str],
    ir_args: list[IRExpr],
) -> tuple[GpuDispatchSpec, GpuArgumentPlan]:
    kernel = gen._gpu_kernels[function_name]
    declaration = gen.analyzed.function_table[function_name]
    result_elem_type = _result_element_type(declaration) if kernel.output_buffer is not None else ""
    prefix = gen.fresh_temp("__gpu_dispatch")
    spec = GpuDispatchSpec(
        kernel=kernel,
        declaration=declaration,
        prefix=prefix,
        result_elem_type=result_elem_type,
        cpu_fallback=f"{function_name}__gpucpu",
    )
    from .arguments import order_args_and_nodes_for_params

    ast_args, ir_args = order_args_and_nodes_for_params(
        gen,
        declaration.params,
        ast_args,
        arg_names,
        ir_args,
        reject_missing=True,
    )
    arguments = prepare_gpu_arguments(
        gen,
        declaration,
        ast_args,
        ir_args,
    )
    _register_dispatch_helper(gen, spec)
    return spec, arguments


def _register_dispatch_helper(gen: IRGenerator, spec: GpuDispatchSpec) -> None:
    from .gpu_dispatch_model import wgsl_to_c

    uniform_types = dict(spec.kernel.uniform_params)
    uniform_fields = [
        IRStructField(
            c_type=CType(text=wgsl_to_c(uniform_types[parameter.name])),
            name=parameter.name,
        )
        for parameter in spec.declaration.params
        if not (parameter.type and parameter.type.is_array)
    ]
    uniform_fields.extend(
        IRStructField(
            c_type=CType(text="int"),
            name=buffer_length_name(buffer.name),
        )
        for buffer in spec.kernel.param_buffers
    )
    uniform_fields.extend(
        [
            IRStructField(c_type=CType(text="int"), name="__gpu_off"),
            IRStructField(c_type=CType(text="int"), name="__gpu_n"),
        ]
    )
    gen.module.struct_defs.append(
        IRStructDef(
            name=spec.uniform_struct,
            fields=uniform_fields,
        )
    )
    body = IRBlock(
        stmts=[
            *initial_state(spec),
            *storage_buffers(spec),
            *uniforms_and_pipeline(spec),
            *bind_group(spec),
            *execution_and_recovery(spec),
        ]
    )
    gen.module.function_defs.append(
        IRFunctionDef(
            name=spec.helper_name,
            return_type=CType(text="void"),
            params=spec.helper_params(),
            body=body,
            is_static=True,
        )
    )


def _expression_local_call(
    arguments: GpuArgumentPlan,
    call: IRCall,
) -> IRExpr:
    if not arguments.declarations:
        return call
    return IRStmtExpr(
        stmts=arguments.declarations,
        result=IRCommaExpr(
            expressions=[*arguments.assignments, call],
        ),
    )


def _result_element_type(declaration) -> str:
    from dataclasses import replace

    return type_to_c(
        replace(
            declaration.return_type,
            is_array=False,
            array_size=None,
        )
    )


def _arg_names(call: CallExpr) -> list[str]:
    from .arguments import arg_names_for

    return arg_names_for(call, len(call.args))
