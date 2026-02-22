"""Lambda lowering: LambdaExpr → static function + capture struct."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    LambdaBlock,
    LambdaExpr,
    LambdaExprBody,
)
from ..nodes import (
    CType,
    IRBlock,
    IRCast,
    IRFieldAccess,
    IRFunctionDef,
    IRParam,
    IRRawExpr,
    IRReturn,
    IRStructDef,
    IRStructField,
    IRVar,
    IRVarDecl,
)
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_lambda(gen: IRGenerator, node: LambdaExpr) -> IRRawExpr:
    """Lower a lambda expression to a static function + capture struct.

    Returns an IRRawExpr referencing the function name, since lambdas
    are used as function pointer values.
    """
    lambda_id = gen.fresh_lambda_id()
    fn_name = f"__btrc_lambda_{lambda_id}"
    env_name = f"__btrc_lambda_{lambda_id}_env"

    has_captures = bool(node.captures)

    # Build capture struct if needed
    if has_captures:
        cap_fields = []
        for cap in node.captures:
            c_type = type_to_c(cap.type) if cap.type else "int"
            cap_fields.append(IRStructField(
                c_type=CType(text=c_type), name=cap.name))
        gen.module.struct_defs.append(IRStructDef(
            name=env_name, fields=cap_fields))

    # Build function params
    params = []
    for p in node.params:
        params.append(IRParam(c_type=CType(text=type_to_c(p.type)), name=p.name))
    # Add void* env parameter only when there are captures.
    # The typedef doesn't include void*, so captured lambdas are called
    # directly by name (bypassing the function pointer) with the env arg.
    if has_captures:
        params.append(IRParam(c_type=CType(text="void*"), name="__btrc_env"))

    # Return type: use explicit annotation, or infer from node_types (__fn_ptr)
    if node.return_type:
        ret_type = type_to_c(node.return_type)
    else:
        # Analyzer stores lambda type as __fn_ptr(ret, param1, param2, ...)
        fn_type = gen.analyzed.node_types.get(id(node))
        if fn_type and fn_type.base == "__fn_ptr" and fn_type.generic_args:
            ret_type = type_to_c(fn_type.generic_args[0])
        elif isinstance(node.body, LambdaExprBody) and node.body.expression:
            # Fallback: infer from body expression type
            body_type = gen.analyzed.node_types.get(id(node.body.expression))
            ret_type = type_to_c(body_type) if body_type else "int"
        else:
            ret_type = "void"

    # Build body
    body_stmts = []

    # Unpack captures from env (use struct keyword for C compatibility)
    if has_captures:
        body_stmts.append(IRVarDecl(
            c_type=CType(text=f"struct {env_name}*"), name="__env",
            init=IRCast(target_type=f"struct {env_name}*",
                        expr=IRVar(name="__btrc_env")),
        ))
        for cap in node.captures:
            c_type = type_to_c(cap.type) if cap.type else "int"
            body_stmts.append(IRVarDecl(
                c_type=CType(text=c_type), name=cap.name,
                init=IRFieldAccess(obj=IRVar(name="__env"),
                                   field=cap.name, arrow=True),
            ))

    # Lambda body — isolate managed scope since the lambda is a separate
    # C function and must not inherit the parent's ARC-managed variables.
    saved_managed = gen._managed_vars_stack
    saved_try_depth = gen.in_try_depth
    saved_func_var_decls = gen._func_var_decls
    gen._managed_vars_stack = []
    gen.in_try_depth = 0
    gen._func_var_decls = []
    if isinstance(node.body, LambdaBlock) and node.body.body:
        from .statements import lower_block
        block = lower_block(gen, node.body.body)
        body_stmts.extend(block.stmts)
    elif isinstance(node.body, LambdaExprBody) and node.body.expression:
        from .expressions import lower_expr
        expr = lower_expr(gen, node.body.expression)
        body_stmts.append(IRReturn(value=expr))
    gen._managed_vars_stack = saved_managed
    gen.in_try_depth = saved_try_depth
    gen._func_var_decls = saved_func_var_decls

    gen.module.function_defs.append(IRFunctionDef(
        name=fn_name,
        return_type=CType(text=ret_type),
        params=params,
        body=IRBlock(stmts=body_stmts),
        is_static=True,
    ))

    # Track lambda ID for capture struct allocation in _lower_var_decl
    gen._last_lambda_id = lambda_id

    # Return reference to the function
    return IRRawExpr(text=fn_name)
