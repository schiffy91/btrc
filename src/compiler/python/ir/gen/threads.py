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
    CType, IRAssign, IRBlock, IRCall, IRCast, IRExprStmt, IRFieldAccess,
    IRFunctionDef, IRIf, IRLiteral, IRParam, IRRawExpr, IRReturn,
    IRSpawnThread, IRStmtExpr, IRStructDef, IRStructField, IRUnaryOp,
    IRVar, IRVarDecl,
)
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


_PRIMITIVE_TYPES = {"int", "float", "double", "char", "bool", "short", "long"}


def lower_spawn(gen: IRGenerator, node):
    """Lower a SpawnExpr to IR that spawns a thread.

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
        return IRSpawnThread(fn_ptr=fn_text, capture_arg=None)

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
        # Use IRStmtExpr to allocate + populate capture struct
        se_var = f"__se{spawn_id}"
        stmts = [
            # env_name* __seN = (env_name*)malloc(sizeof(env_name))
            IRVarDecl(
                c_type=CType(text=f"{env_name}*"), name=se_var,
                init=IRCast(
                    target_type=CType(text=f"{env_name}*"),
                    expr=IRCall(callee="malloc", args=[
                        IRCall(callee="sizeof", args=[IRLiteral(text=env_name)]),
                    ]),
                ),
            ),
        ]
        for cap in fn.captures:
            # __seN->cap_name = cap_name
            stmts.append(IRAssign(
                target=IRFieldAccess(
                    obj=IRVar(name=se_var), field=cap.name, arrow=True),
                value=IRVar(name=cap.name),
            ))
            # ARC: increment rc for captured class instances so they survive
            # until the thread completes (paired with rc-- in wrapper cleanup)
            if cap.type and cap.type.base in gen.analyzed.class_table:
                stmts.append(IRIf(
                    condition=IRVar(name=cap.name),
                    then_block=IRBlock(stmts=[IRExprStmt(
                        expr=IRUnaryOp(
                            op="++",
                            operand=IRFieldAccess(
                                obj=IRVar(name=cap.name),
                                field="__rc", arrow=True),
                            prefix=False,
                        ),
                    )]),
                ))

        spawn_call = IRSpawnThread(
            fn_ptr=wrapper_name,
            capture_arg=IRCast(
                target_type=CType(text="void*"),
                expr=IRVar(name=se_var),
            ),
        )
        return IRStmtExpr(stmts=stmts, result=spawn_call)
    else:
        return IRSpawnThread(fn_ptr=wrapper_name, capture_arg=None)


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
    from ..nodes import IRCall, IRExprStmt, IRIf, IRBinOp, IRUnaryOp
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

    # Build cleanup stmts for captures (ARC release + free env)
    cleanup_stmts = _build_capture_cleanup(gen, fn, has_captures)

    # Lambda body — isolate managed scope so captures from outer scope
    # don't get released inside the wrapper function
    saved_managed = gen._managed_vars_stack
    gen._managed_vars_stack = []
    if isinstance(fn.body, LambdaBlock) and fn.body.body:
        from .statements import lower_block
        block = lower_block(gen, fn.body.body)
        # Rewrite body: box returns, insert cleanup before final return
        lowered = [_rewrite_return(s, ret_c_type) for s in block.stmts]
        if cleanup_stmts and lowered and isinstance(lowered[-1], IRReturn):
            final_ret = lowered.pop()
            body_stmts.extend(lowered)
            # Save result, cleanup, return
            body_stmts.append(IRVarDecl(
                c_type=CType(text="void*"), name="__result",
                init=final_ret.value or IRLiteral(text="NULL")))
            body_stmts.extend(cleanup_stmts)
            body_stmts.append(IRReturn(value=IRVar(name="__result")))
        else:
            body_stmts.extend(lowered)
    elif isinstance(fn.body, LambdaExprBody) and fn.body.expression:
        from .expressions import lower_expr
        expr = lower_expr(gen, fn.body.expression)
        if cleanup_stmts:
            body_stmts.append(IRVarDecl(
                c_type=CType(text="void*"), name="__result",
                init=_box_result(expr, ret_c_type)))
            body_stmts.extend(cleanup_stmts)
            body_stmts.append(IRReturn(value=IRVar(name="__result")))
        else:
            body_stmts.append(IRReturn(value=_box_result(expr, ret_c_type)))

    gen._managed_vars_stack = saved_managed

    # Ensure void wrappers return NULL (with cleanup first)
    if ret_c_type == "void":
        body_stmts.extend(cleanup_stmts)
        body_stmts.append(IRReturn(value=IRLiteral(text="NULL")))

    return body_stmts


def _build_capture_cleanup(gen, fn, has_captures):
    """Build cleanup stmts: ARC release for class captures + free env struct."""
    from ..nodes import IRCall, IRExprStmt, IRIf, IRBinOp, IRUnaryOp
    if not has_captures:
        return []
    stmts = []
    for cap in fn.captures:
        if cap.type and cap.type.base in gen.analyzed.class_table:
            destroy_fn = f"{cap.type.base}_destroy"
            # if (cap != NULL) { if (--cap->__rc <= 0) destroy(cap); }
            stmts.append(IRIf(
                condition=IRBinOp(left=IRVar(name=cap.name), op="!=",
                                  right=IRLiteral(text="NULL")),
                then_block=IRBlock(stmts=[IRIf(
                    condition=IRBinOp(
                        left=IRUnaryOp(op="--", operand=IRFieldAccess(
                            obj=IRVar(name=cap.name), field="__rc", arrow=True),
                            prefix=True),
                        op="<=", right=IRLiteral(text="0")),
                    then_block=IRBlock(stmts=[IRExprStmt(
                        expr=IRCall(callee=destroy_fn,
                                    args=[IRVar(name=cap.name)]))]),
                )]),
            ))
    stmts.append(IRExprStmt(expr=IRCall(callee="free",
                                         args=[IRVar(name="__env")])))
    return stmts


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
