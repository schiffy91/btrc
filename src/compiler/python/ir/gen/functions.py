"""Function lowering: FunctionDecl → IRFunctionDef."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import FunctionDecl
from ..nodes import CType, IRFunctionDecl, IRFunctionDef
from .parameters import lower_source_param
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
    if decl.name == "main" and ret_type == "void":
        ret_type = "int"
    params = [lower_source_param(parameter) for parameter in decl.params]
    is_static = bool(decl.return_type and decl.return_type.is_static)

    # A source declaration without a body remains a typed prototype.
    if decl.body is None:
        gen.module.function_decls.append(
            IRFunctionDecl(
                name=decl.name,
                return_type=CType(text=ret_type),
                params=params,
                is_static=is_static,
            )
        )
        return

    name = decl.name

    from .statements import lower_block

    gen._func_var_decls = []
    previous_return_type = gen.current_return_type
    previous_return_c_type = gen.current_return_c_type
    previous_return_owned = gen.current_return_owned
    previous_void_main = gen._normalizing_void_main
    gen.current_return_c_type = ret_type
    gen.current_return_type = decl.return_type
    gen.current_return_owned = True
    gen._normalizing_void_main = bool(name == "main" and decl.return_type.base == "void")
    body = lower_block(
        gen,
        decl.body,
        local_bindings=[parameter.name for parameter in decl.params],
        callable_bindings=decl.params,
    )
    gen._normalizing_void_main = previous_void_main
    gen.current_return_type = previous_return_type
    gen.current_return_c_type = previous_return_c_type
    gen.current_return_owned = previous_return_owned

    gen.module.function_defs.append(
        IRFunctionDef(
            name=name,
            return_type=CType(text=ret_type),
            params=params,
            body=body,
            is_static=is_static,
        )
    )
