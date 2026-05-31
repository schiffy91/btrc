"""Function lowering: FunctionDecl → IRFunctionDef."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import FunctionDecl
from ..nodes import CType, IRFunctionDef, IRParam
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def emit_function_decl(gen: IRGenerator, decl: FunctionDecl):
    """Lower a top-level FunctionDecl to an IRFunctionDef or forward decl."""
    # @gpu functions are lowered to WGSL kernels, plus a CPU-loop fallback so
    # they run on the CPU when no GPU is available.
    if decl.is_gpu:
        from .gpu import emit_gpu_cpu_fallback, emit_gpu_kernel
        emit_gpu_kernel(gen, decl)
        emit_gpu_cpu_fallback(gen, decl)
        return

    ret_type = type_to_c(decl.return_type) if decl.return_type else "void"
    params = []
    for p in decl.params:
        params.append(IRParam(c_type=CType(text=type_to_c(p.type)), name=p.name))

    # Forward declaration (no body) → emit as forward decl string
    if decl.body is None:
        param_str = ", ".join(f"{p.c_type} {p.name}" for p in params)
        if not param_str:
            param_str = "void"
        gen.module.forward_decls.append(f"{ret_type} {decl.name}({param_str});")
        return

    # Special handling for main: ensure it returns int. Done BEFORE lowering so
    # the return-type context (used to type the ARC return temp) is correct.
    name = decl.name
    if name == "main" and ret_type == "void":
        ret_type = "int"

    from .statements import lower_block
    gen._func_var_decls = []
    gen.current_return_c_type = ret_type
    body = lower_block(gen, decl.body)

    gen.module.function_defs.append(IRFunctionDef(
        name=name,
        return_type=CType(text=ret_type),
        params=params,
        body=body,
    ))
