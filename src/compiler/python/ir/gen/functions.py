"""Function lowering: FunctionDecl → IRFunctionDef."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import FunctionDecl, TypeExpr
from ..nodes import CType, IRBlock, IRFunctionDef, IRParam
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def emit_function_decl(gen: IRGenerator, decl: FunctionDecl):
    """Lower a top-level FunctionDecl to an IRFunctionDef or forward decl."""
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

    from .statements import lower_block
    gen._func_var_decls = []
    body = lower_block(gen, decl.body)

    # Special handling for main: ensure it returns int
    name = decl.name
    if name == "main" and ret_type == "void":
        ret_type = "int"

    gen.module.function_defs.append(IRFunctionDef(
        name=name,
        return_type=CType(text=ret_type),
        params=params,
        body=body,
    ))
