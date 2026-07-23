"""GPU kernel IR generation: @gpu functions → WGSL and dispatch helpers.

Walks the btrc AST for @gpu-annotated functions and:
1. Generates WGSL compute shader source (via gpu_wgsl.py)
2. Produces IRGpuKernel nodes (stored as global WGSL string constants)
3. At call sites, produces ordinary calls to structured dispatch helpers
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import FunctionDecl
from ..nodes import (
    IRGpuBuffer,
    IRGpuKernel,
)
from .gpu_kernel_wgsl import generate_kernel_wgsl, kernel_status_binding
from .gpu_wgsl import btrc_type_to_wgsl_elem

if TYPE_CHECKING:
    from .lowerer import IRLowerer

_WORKGROUP_SIZE = 64


def emit_gpu_kernel(gen: IRLowerer, decl: FunctionDecl) -> None:
    """Generate an IRGpuKernel for a @gpu function declaration.

    Translates the function body to WGSL and stores it as an IRGpuKernel.
    """
    name = decl.name
    param_buffers: list[IRGpuBuffer] = []
    uniform_params: list[tuple[str, str]] = []
    bool_uniform_params: list[str] = []
    binding = 0

    # Classify parameters into buffers (arrays) and uniforms (scalars)
    for param in decl.params:
        if param.type and param.type.is_array:
            elem_type = btrc_type_to_wgsl_elem(param.type)
            param_buffers.append(
                IRGpuBuffer(
                    name=param.name,
                    elem_type=elem_type,
                    # A kernel may update an input and then return that
                    # element through its dedicated output buffer. Declaring
                    # all source arrays read_write keeps the shader contract
                    # honest for both void and array-returning kernels.
                    access="read_write",
                    binding=binding,
                )
            )
            binding += 1
        else:
            wgsl_type = btrc_type_to_wgsl_elem(param.type) if param.type else "i32"
            if param.type and param.type.base == "bool":
                # WGSL bool values are not host-shareable. Store them as u32 in
                # the uniform buffer and reconstruct boolean semantics at use
                # sites in WgslEmitter.
                wgsl_type = "u32"
                bool_uniform_params.append(param.name)
            uniform_params.append((param.name, wgsl_type))

    # Determine output buffer
    output_buffer = None
    has_output = False
    ret = decl.return_type
    if ret and ret.base != "void" and ret.is_array:
        has_output = True
        elem_type = btrc_type_to_wgsl_elem(ret)
        output_buffer = IRGpuBuffer(
            name="_output",
            elem_type=elem_type,
            access="read_write",
            binding=binding,
        )

    # Generate WGSL source
    wgsl = generate_kernel_wgsl(
        param_buffers,
        uniform_params,
        bool_uniform_params,
        output_buffer,
        decl.body,
        has_output,
        gen.analyzed.node_types,
        ret,
        _WORKGROUP_SIZE,
    )

    kernel = IRGpuKernel(
        name=name,
        wgsl_source=wgsl,
        workgroup_size=_WORKGROUP_SIZE,
        param_buffers=param_buffers,
        output_buffer=output_buffer,
        uniform_params=uniform_params,
        status_binding=kernel_status_binding(param_buffers, output_buffer),
    )

    # Store kernel metadata on the generator for call-site lookup
    gen._gpu_kernels[name] = kernel

    # Store kernel as structured IR node — the emitter will emit the
    # WGSL string constant (no raw C text generated in IR gen)
    if not hasattr(gen.module, "gpu_kernels"):
        gen.module.gpu_kernels = []
    gen.module.gpu_kernels.append(kernel)


def emit_gpu_cpu_fallback(gen: IRLowerer, decl: FunctionDecl) -> None:
    """Emit per-invocation and loop-wrapper CPU fallbacks."""

    from .gpu_cpu_fallback import emit_gpu_cpu_fallback as emit_fallback

    emit_fallback(gen, decl)


def lower_gpu_call(
    gen: IRLowerer,
    func_name: str,
    ast_args: list,
    arg_names: list[str],
    ir_args: list | None,
    *,
    call=None,
):
    """Lower a call through the structured dispatch-helper pipeline."""

    from .gpu_dispatch import lower_gpu_call as lower_dispatch_call

    return lower_dispatch_call(
        gen,
        func_name,
        ast_args,
        arg_names,
        ir_args,
        call=call,
    )


def is_direct_gpu_call(gen: IRLowerer, node) -> bool:
    """Whether an identifier kernel call is not shadowed lexically."""

    from ...ast_nodes import Identifier

    if not isinstance(node.callee, Identifier):
        return False
    name = node.callee.name
    return bool(
        name in getattr(gen, "_gpu_kernels", {})
        and not gen.local_ownership_declared(name)
        and name not in gen.analyzed.global_var_types
        and name not in gen.context.callable_environments
    )


def lower_direct_gpu_call(gen: IRLowerer, node):
    """Lower one unshadowed kernel call without eager outer argument replay."""

    if not is_direct_gpu_call(gen, node):
        return None
    from .arguments import arg_names_for

    return lower_gpu_call(
        gen,
        node.callee.name,
        node.args,
        arg_names_for(node, len(node.args)),
        None,
        call=node,
    )


def is_gpu_function(gen: IRLowerer, name: str) -> bool:
    """Check if a function name refers to a @gpu kernel."""
    return hasattr(gen, "_gpu_kernels") and name in gen._gpu_kernels
