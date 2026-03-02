"""GPU kernel IR generation: @gpu functions → IRGpuKernel + IRGpuDispatch.

Walks the btrc AST for @gpu-annotated functions and:
1. Generates WGSL compute shader source (via gpu_wgsl.py)
2. Produces IRGpuKernel nodes (stored as global WGSL string constants)
3. At call sites, produces IRGpuDispatch nodes (WebGPU boilerplate)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import FunctionDecl, TypeExpr
from ..nodes import (
    CType,
    IRGpuBuffer,
    IRGpuDispatch,
    IRGpuKernel,
    IRLiteral,
    IRRawExpr,
)
from .gpu_wgsl import WgslEmitter, btrc_type_to_wgsl_elem

if TYPE_CHECKING:
    from .generator import IRGenerator

_WORKGROUP_SIZE = 64


def emit_gpu_kernel(gen: IRGenerator, decl: FunctionDecl) -> None:
    """Generate an IRGpuKernel for a @gpu function declaration.

    Translates the function body to WGSL and stores it as a kernel node
    in the IR module's raw_sections.
    """
    name = decl.name
    param_buffers: list[IRGpuBuffer] = []
    uniform_params: list[tuple[str, str]] = []
    binding = 0

    # Classify parameters into buffers (arrays) and uniforms (scalars)
    for param in decl.params:
        if param.type and param.type.is_array:
            elem_type = btrc_type_to_wgsl_elem(param.type)
            param_buffers.append(IRGpuBuffer(
                name=param.name,
                elem_type=elem_type,
                access="read",
                binding=binding,
            ))
            binding += 1
        else:
            wgsl_type = btrc_type_to_wgsl_elem(param.type) if param.type else "i32"
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

    # For void-returning @gpu functions, mark array params as read_write
    # (they will be modified in-place)
    if not has_output:
        for buf in param_buffers:
            buf.access = "read_write"

    # Generate WGSL source
    wgsl = _generate_wgsl(name, param_buffers, uniform_params,
                          output_buffer, decl.body, has_output)

    kernel = IRGpuKernel(
        name=name,
        wgsl_source=wgsl,
        workgroup_size=_WORKGROUP_SIZE,
        param_buffers=param_buffers,
        output_buffer=output_buffer,
        uniform_params=uniform_params,
    )

    # Store kernel metadata on the generator for call-site lookup
    if not hasattr(gen, '_gpu_kernels'):
        gen._gpu_kernels = {}
    gen._gpu_kernels[name] = kernel

    # Store kernel as structured IR node — the emitter will emit the
    # WGSL string constant (no raw C text generated in IR gen)
    if not hasattr(gen.module, 'gpu_kernels'):
        gen.module.gpu_kernels = []
    gen.module.gpu_kernels.append(kernel)


def _generate_wgsl(name: str, param_buffers: list[IRGpuBuffer],
                   uniform_params: list[tuple[str, str]],
                   output_buffer, body, has_output: bool) -> str:
    """Generate complete WGSL compute shader source."""
    lines: list[str] = []

    # Storage buffer declarations
    for buf in param_buffers:
        access = "read_write" if buf.access == "read_write" else "read"
        lines.append(
            f"@group(0) @binding({buf.binding}) "
            f"var<storage, {access}> {buf.name}: array<{buf.elem_type}>;")

    # Output buffer declaration (if function returns an array)
    if output_buffer:
        lines.append(
            f"@group(0) @binding({output_buffer.binding}) "
            f"var<storage, read_write> _output: array<{output_buffer.elem_type}>;")

    # Uniform declarations (scalars packed into a uniform buffer)
    if uniform_params:
        lines.append("")
        lines.append("struct Uniforms {")
        for uname, utype in uniform_params:
            lines.append(f"    {uname}: {utype},")
        lines.append("}")
        uniform_binding = (output_buffer.binding + 1) if output_buffer else (
            param_buffers[-1].binding + 1 if param_buffers else 0)
        lines.append(
            f"@group(0) @binding({uniform_binding}) "
            f"var<uniform> uniforms: Uniforms;")

    lines.append("")
    lines.append(f"@compute @workgroup_size({_WORKGROUP_SIZE})")
    lines.append("fn main(@builtin(global_invocation_id) gid: vec3<u32>) {")

    # Emit function body as WGSL
    array_params = [buf.name for buf in param_buffers]
    emitter = WgslEmitter(array_params, has_output=has_output)
    body_text = emitter.emit_block(body)
    if body_text:
        lines.append(body_text)

    lines.append("}")

    return "\n".join(lines)


def lower_gpu_call(gen: IRGenerator, func_name: str,
                   ast_args: list, ir_args: list) -> IRGpuDispatch:
    """Generate an IRGpuDispatch for a call to a @gpu function.

    The dispatch node contains all metadata needed by the emitter to
    generate WebGPU buffer creation, upload, dispatch, and readback code.
    """
    kernel = gen._gpu_kernels[func_name]

    # Determine array length from first array argument
    array_len_expr = None
    for i, param in enumerate(kernel.param_buffers):
        if i < len(ir_args):
            # Use the first array param's length for dispatch size
            array_len_expr = IRRawExpr(
                text=f"(sizeof({_ir_expr_text(ir_args[i])}) / sizeof({_ir_expr_text(ir_args[i])}[0]))")
            break

    # Determine result type
    result_elem_type = ""
    result_var = ""
    if kernel.output_buffer:
        result_elem_type = _wgsl_to_c_type(kernel.output_buffer.elem_type)

    return IRGpuDispatch(
        kernel_name=func_name,
        args=ir_args,
        result_var=result_var,
        result_elem_type=result_elem_type,
        array_len_expr=array_len_expr,
        param_buffers=kernel.param_buffers,
        output_buffer=kernel.output_buffer,
        uniform_params=kernel.uniform_params,
        workgroup_size=kernel.workgroup_size,
    )


def is_gpu_function(gen: IRGenerator, name: str) -> bool:
    """Check if a function name refers to a @gpu kernel."""
    return hasattr(gen, '_gpu_kernels') and name in gen._gpu_kernels


def _wgsl_to_c_type(wgsl_type: str) -> str:
    """Map WGSL element type to C type."""
    return {"f32": "float", "i32": "int", "u32": "unsigned int",
            "bool": "bool"}.get(wgsl_type, "float")


def _ir_expr_text(expr) -> str:
    """Quick text representation of an IR expression."""
    if hasattr(expr, 'text'):
        return expr.text
    if hasattr(expr, 'name'):
        return expr.name
    return "/* expr */"
