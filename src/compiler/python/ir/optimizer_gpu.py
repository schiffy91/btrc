"""Reachability pruning for generated GPU shader constants."""

from __future__ import annotations

from .nodes import IRModule, IRVar
from .optimizer_walk import iter_ir_nodes


def eliminate_dead_gpu_kernels(module: IRModule) -> None:
    """Keep WGSL constants referenced by surviving structured helper IR."""

    if not module.gpu_kernels:
        return
    kernel_by_symbol = {f"{kernel.name}_wgsl": kernel for kernel in module.gpu_kernels}
    live_symbols = {
        node.name
        for function in module.function_defs
        for node in iter_ir_nodes(function.body)
        if isinstance(node, IRVar) and node.name in kernel_by_symbol
    }
    module.gpu_kernels = [kernel for kernel in module.gpu_kernels if f"{kernel.name}_wgsl" in live_symbols]
