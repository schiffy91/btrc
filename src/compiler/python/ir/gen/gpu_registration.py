"""Early GPU declaration registration for call-site lowering."""

from __future__ import annotations

from ...ast_nodes import FunctionDecl
from .types import CTypeRenderer


def emit_gpu_functions(
    gen,
    type_renderer: CTypeRenderer,
    default_arguments,
) -> None:
    """Register kernels and fallbacks before generic bodies use them."""

    from .functions import emit_function_decl

    for declaration in gen.analyzed.program.declarations:
        if isinstance(declaration, FunctionDecl) and declaration.is_gpu:
            emit_function_decl(
                gen,
                declaration,
                type_renderer,
                default_arguments,
            )


__all__ = ["emit_gpu_functions"]
