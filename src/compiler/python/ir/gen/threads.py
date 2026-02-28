"""Thread lowering: SpawnExpr → wrapper function + __btrc_thread_spawn call.

spawn(lambda) lowers to:
1. A static wrapper function with void*(*)(void*) signature
2. A capture struct allocation (if lambda has captures)
3. A call to __btrc_thread_spawn(wrapper, capture_ptr)

Thread<T> at the C level is just __btrc_thread_t* — no class struct.
.join() is handled in calls.py as __btrc_thread_join with result casting.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import LambdaBlock, LambdaExpr, LambdaExprBody
from ..nodes import (
    CType, IRBlock, IRCast, IRFieldAccess, IRFunctionDef, IRLiteral,
    IRParam, IRRawExpr, IRReturn, IRStructDef, IRStructField, IRVar,
    IRVarDecl,
)
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


_PRIMITIVE_TYPES = {"int", "float", "double", "char", "bool", "short", "long"}


def lower_spawn(gen: IRGenerator, node) -> IRRawExpr:
    """Lower a SpawnExpr to a GCC statement expression that spawns a thread.

    Returns __btrc_thread_t* — the opaque thread handle.
    """
    fn = node.fn

    # Add pthread.h include and register helpers
    if "pthread.h" not in gen.module.includes:
        gen.module.includes.append("pthread.h")
    gen.use_helper("__btrc_thread_spawn")

    if not isinstance(fn, LambdaExpr):
        # Non-lambda spawn — treat as function pointer
        from .expressions import lower_expr
        fn_expr = lower_expr(gen, fn)
        fn_text = fn_expr.text if hasattr(fn_expr, 'text') else fn_expr.name
        return IRRawExpr(text=f"__btrc_thread_spawn((void*(*)(void*)){fn_text}, NULL)")

    # Determine return type of the lambda
    ret_c_type = _infer_lambda_ret_type(gen, fn)

    spawn_id = gen.fresh_lambda_id()
    wrapper_name = f"__btrc_spawn_wrapper_{spawn_id}"
    env_name = f"__btrc_spawn_env_{spawn_id}"
    has_captures = bool(fn.captures)

    # Build capture struct if needed
    if has_captures:
        cap_fields = []
        for cap in fn.captures:
            c_type = type_to_c(cap.type) if cap.type else "int"
            cap_fields.append(IRStructField(c_type=CType(text=c_type), name=cap.name))
        gen.module.forward_decls.append(f"typedef struct {env_name} {env_name};")
        gen.module.struct_defs.append(IRStructDef(name=env_name, fields=cap_fields))

    # Build wrapper function: void* wrapper(void* __arg)
    body_stmts = _build_wrapper_body(gen, fn, env_name, has_captures, ret_c_type)

    gen.module.function_defs.append(IRFunctionDef(
        name=wrapper_name,
        return_type=CType(text="void*"),
        params=[IRParam(c_type=CType(text="void*"), name="__arg")],
        body=IRBlock(stmts=body_stmts),
        is_static=True,
    ))

    # Build the spawn expression
    if has_captures:
        # Use GCC statement expression to allocate + populate capture struct
        parts = [f"{env_name}* __se{spawn_id} = ({env_name}*)malloc(sizeof({env_name}))"]
        for cap in fn.captures:
            parts.append(f"__se{spawn_id}->{cap.name} = {cap.name}")
        parts.append(
            f"__btrc_thread_spawn((void*(*)(void*)){wrapper_name}, (void*)__se{spawn_id})"
        )
        return IRRawExpr(text="({ " + "; ".join(parts) + "; })")
    else:
        return IRRawExpr(
            text=f"__btrc_thread_spawn((void*(*)(void*)){wrapper_name}, NULL)"
        )


def _infer_lambda_ret_type(gen: IRGenerator, fn: LambdaExpr) -> str:
    """Infer the C return type of a lambda."""
    if fn.return_type:
        return type_to_c(fn.return_type)
    fn_type = gen.analyzed.node_types.get(id(fn))
    if fn_type and fn_type.base == "__fn_ptr" and fn_type.generic_args:
        return type_to_c(fn_type.generic_args[0])
    if isinstance(fn.body, LambdaExprBody) and fn.body.expression:
        body_type = gen.analyzed.node_types.get(id(fn.body.expression))
        return type_to_c(body_type) if body_type else "int"
    return "void"


def _build_wrapper_body(gen, fn, env_name, has_captures, ret_c_type):
    """Build the body of the pthread wrapper function."""
    body_stmts = []

    # Unpack captures
    if has_captures:
        body_stmts.append(IRVarDecl(
            c_type=CType(text=f"{env_name}*"), name="__env",
            init=IRCast(target_type=f"{env_name}*", expr=IRVar(name="__arg")),
        ))
        for cap in fn.captures:
            c_type = type_to_c(cap.type) if cap.type else "int"
            body_stmts.append(IRVarDecl(
                c_type=CType(text=c_type), name=cap.name,
                init=IRFieldAccess(obj=IRVar(name="__env"), field=cap.name, arrow=True),
            ))

    # Lambda body
    if isinstance(fn.body, LambdaBlock) and fn.body.body:
        from .statements import lower_block
        block = lower_block(gen, fn.body.body)
        for stmt in block.stmts:
            body_stmts.append(_rewrite_return(stmt, ret_c_type))
    elif isinstance(fn.body, LambdaExprBody) and fn.body.expression:
        from .expressions import lower_expr
        expr = lower_expr(gen, fn.body.expression)
        body_stmts.append(IRReturn(value=_box_result(expr, ret_c_type)))

    # Ensure void wrappers return NULL
    if ret_c_type == "void":
        body_stmts.append(IRReturn(value=IRLiteral(text="NULL")))

    return body_stmts


def _box_result(expr, ret_c_type: str):
    """Box a result value into void* for the thread wrapper return.

    Returns proper IR nodes (IRCast chains) instead of text.
    """
    if ret_c_type == "void":
        return IRLiteral(text="NULL")
    if ret_c_type.strip() in _PRIMITIVE_TYPES:
        # (void*)(intptr_t)(expr)
        return IRCast(target_type="void*",
                      expr=IRCast(target_type="intptr_t", expr=expr))
    # Pointer type: (void*)(expr)
    return IRCast(target_type="void*", expr=expr)


def _rewrite_return(stmt, ret_c_type: str):
    """Rewrite IRReturn to box the result for the void* wrapper."""
    if isinstance(stmt, IRReturn):
        if stmt.value is None:
            return IRReturn(value=IRLiteral(text="NULL"))
        return IRReturn(value=_box_result(stmt.value, ret_c_type))
    return stmt
