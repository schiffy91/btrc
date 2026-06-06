"""GPU kernel IR generation: @gpu functions → IRGpuKernel + IRGpuDispatch.

Walks the btrc AST for @gpu-annotated functions and:
1. Generates WGSL compute shader source (via gpu_wgsl.py)
2. Produces IRGpuKernel nodes (stored as global WGSL string constants)
3. At call sites, produces IRGpuDispatch nodes (WebGPU boilerplate)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import FunctionDecl
from ..nodes import (
    CType,
    IRBinOp,
    IRBlock,
    IRFor,
    IRFunctionDef,
    IRGpuBuffer,
    IRGpuDispatch,
    IRGpuKernel,
    IRLiteral,
    IRParam,
    IRRawExpr,
    IRVar,
    IRVarDecl,
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


def emit_gpu_cpu_fallback(gen: IRGenerator, decl: FunctionDecl) -> None:
    """Emit a CPU-loop fallback for a void @gpu kernel.

    `void f(params)` → `void f__gpucpu(params, int __gpu_n)` whose body runs the
    kernel body once per index with gpu_id() bound to the loop variable. Used by
    the dispatch site when no GPU is available. Array-returning kernels are left
    GPU-only.
    """
    ret = decl.return_type
    if ret is not None and ret.base != "void":
        return
    if decl.body is None:
        return
    from .statements import lower_block
    from .types import type_to_c

    fname = decl.name + "__gpucpu"
    params = [IRParam(c_type=CType(text=type_to_c(p.type)), name=p.name)
              for p in decl.params]
    params.append(IRParam(c_type=CType(text="int"), name="__gpu_n"))

    prev_idx = getattr(gen, "_gpu_cpu_index", None)
    prev_decls = getattr(gen, "_func_var_decls", None)
    prev_ret = gen.current_return_c_type
    prev_return_type = gen.current_return_type
    gen._gpu_cpu_index = "__gid"
    gen._func_var_decls = []
    gen.current_return_c_type = type_to_c(decl.return_type) if decl.return_type else "void"
    gen.current_return_type = decl.return_type
    body = lower_block(gen, decl.body)
    gen._gpu_cpu_index = prev_idx
    gen._func_var_decls = prev_decls
    gen.current_return_c_type = prev_ret
    gen.current_return_type = prev_return_type

    loop = IRFor(
        init=IRVarDecl(c_type=CType(text="int"), name="__gid", init=IRLiteral(text="0")),
        condition=IRBinOp(left=IRVar(name="__gid"), op="<", right=IRVar(name="__gpu_n")),
        update=IRRawExpr(text="__gid++"),
        body=body,
    )
    param_str = ", ".join(f"{p.c_type} {p.name}" for p in params)
    gen.module.forward_decls.append(f"void {fname}({param_str});")
    gen.module.function_defs.append(IRFunctionDef(
        name=fname,
        return_type=CType(text="void"),
        params=params,
        body=IRBlock(stmts=[loop]),
    ))


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

    # Uniform buffer: user scalars + dispatch offset/length. Always present so a
    # kernel can be dispatched in chunks larger than the 1D workgroup limit —
    # __gpu_off shifts the global index, __gpu_n bounds it.
    lines.append("")
    lines.append("struct Uniforms {")
    for uname, utype in uniform_params:
        lines.append(f"    {uname}: {utype},")
    lines.append("    btrc_off: i32,")
    lines.append("    btrc_n: i32,")
    lines.append("}")
    uniform_binding = (output_buffer.binding + 1) if output_buffer else (
        param_buffers[-1].binding + 1 if param_buffers else 0)
    lines.append(
        f"@group(0) @binding({uniform_binding}) "
        f"var<uniform> uniforms: Uniforms;")

    lines.append("")
    lines.append(f"@compute @workgroup_size({_WORKGROUP_SIZE})")
    lines.append("fn main(@builtin(global_invocation_id) gid: vec3<u32>) {")
    lines.append("    let btrc_gid: i32 = i32(gid.x) + uniforms.btrc_off;")
    lines.append("    if (btrc_gid >= uniforms.btrc_n) { return; }")

    # Emit function body as WGSL
    array_params = [buf.name for buf in param_buffers]
    uniform_names = [uname for uname, _ in uniform_params]
    emitter = WgslEmitter(array_params, has_output=has_output,
                          uniform_params=uniform_names)
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

    # Determine the dispatch length and per-buffer data pointers. A heap
    # collection (Array<T> / Vector<T>) carries its own length and data pointer,
    # so we use `arg->len` / `arg->data`; a bare C array uses sizeof. This lets
    # @gpu kernels operate on runtime-sized buffers, not just stack arrays.
    array_len_expr = None
    buffer_lens: list = []   # per-buffer element count (arrays may differ in size)
    for i, _param in enumerate(kernel.param_buffers):
        if i >= len(ir_args):
            buffer_lens.append(None)
            continue
        txt = _ir_expr_text(ir_args[i])
        t = gen.analyzed.node_types.get(id(ast_args[i])) if i < len(ast_args) else None
        is_coll = bool(t is not None and getattr(t, "generic_args", None)
                       and t.base in ("Array", "Vector"))
        if is_coll:
            buffer_lens.append(IRRawExpr(text=f"({txt})->len"))
            ir_args[i] = IRRawExpr(text=f"({txt})->data")
            if array_len_expr is None:
                array_len_expr = IRRawExpr(text=f"({txt})->len")
        else:
            buffer_lens.append(None)
            if array_len_expr is None:
                array_len_expr = IRRawExpr(text=f"(sizeof({txt}) / sizeof({txt}[0]))")

    # Determine result type
    result_elem_type = ""
    result_var = ""
    if kernel.output_buffer:
        result_elem_type = _wgsl_to_c_type(kernel.output_buffer.elem_type)

    # Void (in-place) kernels get a CPU-loop fallback used when no GPU is present.
    cpu_fallback = "" if kernel.output_buffer else f"{func_name}__gpucpu"
    # The reference lives only in emitted text, invisible to the dead-function
    # optimizer; the trailing "(" makes its generic string scan keep the fn.
    cpu_fallback_keep = f"{cpu_fallback}(" if cpu_fallback else ""

    return IRGpuDispatch(
        kernel_name=func_name,
        args=ir_args,
        result_var=result_var,
        result_elem_type=result_elem_type,
        array_len_expr=array_len_expr,
        buffer_lens=buffer_lens,
        param_buffers=kernel.param_buffers,
        output_buffer=kernel.output_buffer,
        uniform_params=kernel.uniform_params,
        workgroup_size=kernel.workgroup_size,
        cpu_fallback=cpu_fallback,
        cpu_fallback_keep=cpu_fallback_keep,
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
