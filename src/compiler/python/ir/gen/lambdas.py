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
    IRAddressOf,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRExpr,
    IRFieldAccess,
    IRFunctionDef,
    IRParam,
    IRReturn,
    IRStmtExpr,
    IRStructDef,
    IRStructField,
    IRVar,
    IRVarDecl,
)
from .parameters import lower_source_param
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_lambda(gen: IRGenerator, node: LambdaExpr) -> IRVar:
    """Lower a lambda expression to a static function + capture struct.

    Returns a structured function-name reference for function-pointer use.
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
            cap_fields.append(IRStructField(c_type=CType(text=c_type), name=cap.name))
        gen.module.struct_defs.append(IRStructDef(name=env_name, fields=cap_fields))

    # Build function params
    params = []
    for p in node.params:
        params.append(lower_source_param(p))
    # Add void* env parameter only when there are captures.
    # The typedef doesn't include void*, so captured lambdas are called
    # directly by name (bypassing the function pointer) with the env arg.
    if has_captures:
        params.append(IRParam(c_type=CType(text="void*"), name="__btrc_env"))

    # Keep the semantic return type as well as its C spelling. The isolated
    # body needs both for return coercion/ARC; passing only node.return_type
    # loses inferred lambda returns because that annotation remains None.
    return_type = resolved_lambda_return_type(gen, node)
    ret_type = type_to_c(return_type) if return_type else "void"

    # Build body
    body_stmts = []

    # Unpack captures from env (use struct keyword for C compatibility)
    if has_captures:
        body_stmts.append(
            IRVarDecl(
                c_type=CType(text=f"struct {env_name}*"),
                name="__env",
                init=IRCast(target_type=CType(text=f"struct {env_name}*"), expr=IRVar(name="__btrc_env")),
            )
        )
        for cap in node.captures:
            c_type = type_to_c(cap.type) if cap.type else "int"
            body_stmts.append(
                IRVarDecl(
                    c_type=CType(text=c_type),
                    name=cap.name,
                    init=IRFieldAccess(obj=IRVar(name="__env"), field=cap.name, arrow=True),
                )
            )

    # Lambda body — isolate managed scope since the lambda is a separate
    # C function and must not inherit the parent's ARC-managed variables.
    from .isolated_context import isolated_function_context

    with isolated_function_context(gen, ret_type, return_type):
        if isinstance(node.body, LambdaBlock) and node.body.body:
            from .statements import lower_block

            block = lower_block(gen, node.body.body)
            body_stmts.extend(block.stmts)
        elif isinstance(node.body, LambdaExprBody) and node.body.expression:
            from .expressions import lower_expr
            from .stringable import coerce_value_to_string

            expr = lower_expr(gen, node.body.expression)
            expr_type = gen.analyzed.node_types.get(id(node.body.expression))
            expr = coerce_value_to_string(gen, return_type, expr_type, expr)
            body_stmts.append(IRReturn(value=expr))

    gen.module.function_defs.append(
        IRFunctionDef(
            name=fn_name,
            return_type=CType(text=ret_type),
            params=params,
            body=IRBlock(stmts=body_stmts),
            is_static=True,
        )
    )

    # Track lambda ID for capture struct allocation in _lower_var_decl
    gen._last_lambda_id = lambda_id

    # Return reference to the function
    return IRVar(name=fn_name)


def resolved_lambda_return_type(gen: IRGenerator, node: LambdaExpr):
    """Return the analyzer-resolved lambda result type, if one is known."""
    if node.return_type:
        return node.return_type
    fn_type = gen.analyzed.node_types.get(id(node))
    if fn_type and fn_type.base == "__fn_ptr" and fn_type.generic_args:
        return fn_type.generic_args[0]
    if isinstance(node.body, LambdaExprBody) and node.body.expression:
        return gen.analyzed.node_types.get(id(node.body.expression))
    return None


def lower_immediate_lambda_call(gen: IRGenerator, node: LambdaExpr, ast_args, arg_names) -> IRExpr:
    """Lift and immediately invoke ``node``, preserving its capture env."""
    lower_lambda(gen, node)
    lambda_id = gen._last_lambda_id
    fn_name = f"__btrc_lambda_{lambda_id}"

    from .arguments import lower_arg_values, order_args_for_params

    args = lower_arg_values(gen, ast_args)
    args = order_args_for_params(gen, node.params, ast_args, arg_names, args)
    if not node.captures:
        return IRCall(callee=fn_name, args=args)

    env_struct = f"__btrc_lambda_{lambda_id}_env"
    env_var = f"__btrc_lambda_{lambda_id}_call_env"
    declarations = [
        IRVarDecl(
            c_type=CType(text=f"struct {env_struct}"),
            name=env_var,
        )
    ]
    sequence = [
        IRBinOp(
            left=IRFieldAccess(obj=IRVar(name=env_var), field=capture.name, arrow=False),
            op="=",
            right=IRVar(name=capture.name),
        )
        for capture in node.captures
    ]
    args.append(
        IRCast(
            target_type=CType(text="void*"),
            expr=IRAddressOf(expr=IRVar(name=env_var)),
        )
    )
    sequence.append(IRCall(callee=fn_name, args=args))
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=sequence),
    )
