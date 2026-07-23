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

from ...ast_nodes import Block, LambdaBlock, LambdaExpr, LambdaExprBody, ReturnStmt
from ...qualifier_provenance import effective_outer_volatile
from ..nodes import (
    CType,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRExpr,
    IRFieldAccess,
    IRFunctionDef,
    IRFunctionRef,
    IRLiteral,
    IRParam,
    IRReturn,
    IRSizeof,
    IRStmtExpr,
    IRStructDef,
    IRStructField,
    IRStructForward,
    IRVar,
    IRVarDecl,
)
from .parameters import source_binding_c_name
from .thread_captures import emit_capture_disposer, managed_capture_type
from .thread_returns import rewrite_thread_returns
from .thread_values import thread_result_disposal_args
from .types import CTypeRenderer

if TYPE_CHECKING:
    from .lowerer import IRLowerer


def lower_spawn(
    gen: IRLowerer,
    node,
    type_renderer: CTypeRenderer,
    default_arguments=None,
):
    """Lower a SpawnExpr to IR that spawns a thread.

    Returns __btrc_thread_t* — the opaque thread handle.
    """
    fn = node.fn

    # Registering the helper also pulls in its required runtime headers.
    gen.helpers.use("__btrc_thread_spawn")

    if not isinstance(fn, LambdaExpr):
        # Non-lambda spawn — treat as function pointer
        from .expressions import lower_expr

        spawn_type = gen.analyzed.node_types.get(id(node))
        result_type = spawn_type.generic_args[0] if spawn_type and spawn_type.generic_args else None
        return _spawn_call(
            gen,
            lower_expr(
                gen,
                fn,
                type_renderer,
                default_arguments,
            ),
            result_type,
        )

    # Determine return type of the lambda
    from .lambdas import resolved_lambda_return_type

    return_type = resolved_lambda_return_type(gen, fn)
    ret_c_type = type_renderer.render(return_type) if return_type else "void"

    spawn_id = gen.fresh_lambda_id()
    wrapper_name = f"__btrc_spawn_wrapper_{spawn_id}"
    env_name = f"__btrc_spawn_env_{spawn_id}"
    has_captures = bool(fn.captures)

    # Build capture struct if needed
    if has_captures:
        cap_fields = []
        for cap in fn.captures:
            c_type = type_renderer.render(cap.type) if cap.type else "int"
            cap_fields.append(
                IRStructField(
                    c_type=CType(text=c_type),
                    name=source_binding_c_name(cap.name),
                    is_volatile=bool(cap.type and cap.type.is_volatile),
                    effective_is_volatile=effective_outer_volatile(
                        cap.type,
                        gen.analyzed.typedef_table,
                    ),
                )
            )
        gen.module.struct_forwards.append(IRStructForward(name=env_name))
        gen.module.struct_defs.append(IRStructDef(name=env_name, fields=cap_fields))

    arg_disposer = emit_capture_disposer(
        gen,
        fn,
        env_name,
        spawn_id,
        type_renderer,
    )

    # Build wrapper function: void* wrapper(void* __arg)
    body_stmts = _build_wrapper_body(
        gen,
        fn,
        env_name,
        has_captures,
        ret_c_type,
        return_type,
        type_renderer,
        default_arguments,
    )

    gen.module.function_defs.append(
        IRFunctionDef(
            name=wrapper_name,
            return_type=CType(text="void*"),
            params=[IRParam(c_type=CType(text="void*"), name="__arg")],
            body=IRBlock(stmts=body_stmts),
            is_static=True,
        )
    )

    # Build the spawn expression
    if has_captures:
        gen.helpers.use("__btrc_safe_realloc")
        # Hoist only an inert declaration. Allocation, field initialization,
        # retains, and spawn remain expression-local so a short-circuited or
        # unchosen branch cannot perform them.
        se_var = f"__se{spawn_id}"
        stmts = [
            IRVarDecl(
                c_type=CType(text=f"{env_name}*"),
                name=se_var,
                init=None,
            ),
        ]
        sequence = [
            IRBinOp(
                left=IRVar(name=se_var),
                op="=",
                right=IRCast(
                    target_type=CType(text=f"{env_name}*"),
                    expr=IRCall(
                        callee="__btrc_safe_realloc",
                        args=[
                            IRLiteral(text="NULL"),
                            IRSizeof(operand=CType(text=env_name)),
                        ],
                        helper_ref="__btrc_safe_realloc",
                    ),
                ),
            )
        ]
        for cap in fn.captures:
            sequence.append(
                IRBinOp(
                    left=IRFieldAccess(
                        obj=IRVar(name=se_var),
                        field=source_binding_c_name(cap.name),
                        arrow=True,
                    ),
                    op="=",
                    right=IRVar(name=gen.source_binding_c_name(cap.name)),
                )
            )
            # Keep each direct managed capture alive until worker cleanup.
            capture_type = managed_capture_type(gen, cap)
            if capture_type is not None:
                from .managed_values import retain_value

                sequence.append(
                    retain_value(
                        gen,
                        IRVar(name=gen.source_binding_c_name(cap.name)),
                        capture_type,
                    )
                )

        spawn_call = _spawn_call(
            gen,
            IRFunctionRef(name=wrapper_name),
            return_type,
            IRCast(
                target_type=CType(text="void*"),
                expr=IRVar(name=se_var),
            ),
            IRFunctionRef(name=arg_disposer),
        )
        sequence.append(spawn_call)
        return IRStmtExpr(
            stmts=stmts,
            result=IRCommaExpr(expressions=sequence),
        )
    else:
        return _spawn_call(gen, IRFunctionRef(name=wrapper_name), return_type)


def _spawn_call(
    gen: IRLowerer,
    fn_expr: IRExpr,
    result_type,
    capture_arg: IRExpr | None = None,
    arg_disposer: IRExpr | None = None,
) -> IRCall:
    """Build an ordinary helper call for the pthread entry ABI."""

    return IRCall(
        callee="__btrc_thread_spawn",
        args=[
            IRCast(
                target_type=CType(text="void*(*)(void*)"),
                expr=fn_expr,
            ),
            capture_arg if capture_arg is not None else IRLiteral(text="NULL"),
            arg_disposer if arg_disposer is not None else IRLiteral(text="NULL"),
            *thread_result_disposal_args(gen, result_type),
        ],
        helper_ref="__btrc_thread_spawn",
    )


def _build_wrapper_body(
    gen,
    fn,
    env_name,
    has_captures,
    ret_c_type,
    return_type,
    type_renderer: CTypeRenderer,
    default_arguments=None,
):
    """Build the body of the pthread wrapper function."""
    body_stmts = []

    # Unpack captures
    if has_captures:
        body_stmts.append(
            IRVarDecl(
                c_type=CType(text=f"{env_name}*"),
                name="__env",
                init=IRCast(
                    target_type=CType(text=f"{env_name}*"),
                    expr=IRVar(name="__arg"),
                ),
            )
        )
        for cap in fn.captures:
            c_type = type_renderer.render(cap.type) if cap.type else "int"
            body_stmts.append(
                IRVarDecl(
                    c_type=CType(text=c_type),
                    name=source_binding_c_name(cap.name, gen.analyzed),
                    is_volatile=bool(cap.type and cap.type.is_volatile),
                    effective_is_volatile=effective_outer_volatile(
                        cap.type,
                        gen.analyzed.typedef_table,
                    ),
                    init=IRFieldAccess(
                        obj=IRVar(name="__env"),
                        field=source_binding_c_name(cap.name),
                        arrow=True,
                    ),
                )
            )

    # Lambda body — isolate managed scope so captures from outer scope
    # don't get released inside the wrapper function
    from .callable_provenance import BORROWED_RETURN
    from .isolated_context import isolated_function_context
    from .statements import lower_block

    local_bindings = [parameter.name for parameter in fn.params]
    local_bindings.extend(capture.name for capture in fn.captures)
    capture_abis = [
        (
            capture,
            gen.context.callable_return_abis.get(capture.name, BORROWED_RETURN),
        )
        for capture in fn.captures
    ]

    with isolated_function_context(gen, ret_c_type, return_type):
        if isinstance(fn.body, LambdaBlock) and fn.body.body:
            body = fn.body.body
        elif isinstance(fn.body, LambdaExprBody) and fn.body.expression:
            body = Block(
                statements=[
                    ReturnStmt(
                        value=fn.body.expression,
                        line=fn.body.expression.line,
                        col=fn.body.expression.col,
                    )
                ]
            )
        else:
            body = None
        if body is not None:
            block = lower_block(
                gen,
                body,
                local_bindings=local_bindings,
                callable_bindings=fn.params,
                callable_abis=capture_abis,
                type_renderer=type_renderer,
                default_arguments=default_arguments,
            )
            rewritten = rewrite_thread_returns(
                gen,
                block,
                return_type,
                type_renderer,
            )
            body_stmts.extend(rewritten.stmts)

    # A structured final statement may not cover every path. Keep the C wrapper
    # total; the runtime owns and disposes the capture environment afterward.
    if not body_stmts or not isinstance(body_stmts[-1], IRReturn):
        body_stmts.append(IRReturn(value=IRLiteral(text="NULL")))

    return body_stmts
