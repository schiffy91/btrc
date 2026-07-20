"""Lambda lowering: LambdaExpr → static function + capture struct."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    LambdaBlock,
    LambdaExpr,
    LambdaExprBody,
    ReturnStmt,
)
from ..nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRExpr,
    IRFieldAccess,
    IRFunctionDef,
    IRFunctionRef,
    IRParam,
    IRStmt,
    IRStmtExpr,
    IRStructDef,
    IRStructField,
    IRVar,
    IRVarDecl,
)
from .parameters import lower_source_param, source_binding_c_name
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_lambda(gen: IRGenerator, node: LambdaExpr) -> IRFunctionRef:
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
            cap_fields.append(
                IRStructField(
                    c_type=CType(text=c_type),
                    name=source_binding_c_name(cap.name),
                )
            )
        gen.module.struct_defs.append(IRStructDef(name=env_name, fields=cap_fields))

    # Build function params
    params = []
    for p in node.params:
        params.append(lower_source_param(p, analyzed=gen.analyzed))
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
                    name=source_binding_c_name(cap.name, gen.analyzed),
                    init=IRFieldAccess(
                        obj=IRVar(name="__env"),
                        field=source_binding_c_name(cap.name),
                        arrow=True,
                    ),
                )
            )

    # Lambda body — isolate managed scope since the lambda is a separate
    # C function and must not inherit the parent's ARC-managed variables.
    from .isolated_context import isolated_function_context

    local_bindings = [param.name for param in node.params]
    local_bindings.extend(capture.name for capture in node.captures)
    from .callable_provenance import BORROWED_RETURN

    capture_abis = [
        (capture, gen._callable_return_abis.get(capture.name, BORROWED_RETURN)) for capture in node.captures
    ]
    with isolated_function_context(gen, ret_type, return_type):
        if isinstance(node.body, LambdaBlock) and node.body.body:
            from .statements import lower_block

            block = lower_block(
                gen,
                node.body.body,
                local_bindings=local_bindings,
                callable_bindings=node.params,
                callable_abis=capture_abis,
            )
            body_stmts.extend(block.stmts)
        elif isinstance(node.body, LambdaExprBody) and node.body.expression:
            from .arc_returns import lower_return
            from .callable_provenance import (
                begin_callable_scope,
                bind_borrowed_callable,
                bind_callable_abi,
                declare_callable_shadow,
                finish_callable_scope,
            )

            gen.push_local_ownership_scope()
            enclosing_callables = begin_callable_scope(gen)
            try:
                for name in local_bindings:
                    gen.declare_local_ownership(name)
                    declare_callable_shadow(gen, name)
                for parameter in node.params:
                    bind_borrowed_callable(gen, parameter.name, parameter.type)
                for capture, return_abi in capture_abis:
                    bind_callable_abi(gen, capture.name, capture.type, return_abi)
                body_stmts.extend(
                    lower_return(
                        gen,
                        ReturnStmt(
                            value=node.body.expression,
                            line=node.body.expression.line,
                            col=node.body.expression.col,
                        ),
                    )
                )
            finally:
                finish_callable_scope(gen, enclosing_callables)
                gen.pop_local_ownership_scope()

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
    return IRFunctionRef(name=fn_name)


def lower_captured_lambda_local(
    gen: IRGenerator,
    name: str,
    initializer: LambdaExpr | None,
    statements: list[IRStmt],
) -> None:
    """Replace a captured-lambda pointer local with its stack environment.

    Captured lambda implementations take an extra environment parameter and
    cannot inhabit the plain function-pointer typedef. Semantic analysis keeps
    these closure-only bindings from escaping.
    """
    if not isinstance(initializer, LambdaExpr) or not initializer.captures:
        return
    lambda_id = gen._last_lambda_id
    fn_name = f"__btrc_lambda_{lambda_id}"
    env_var = f"__{name}_env"
    env_decl = IRVarDecl(
        c_type=CType(text=f"struct __btrc_lambda_{lambda_id}_env"),
        name=env_var,
    )
    statements.pop()
    gen._func_var_decls.pop()
    gen._func_var_decls.append(env_decl)
    statements.append(env_decl)
    for capture in initializer.captures:
        field_name = source_binding_c_name(capture.name)
        binding_name = gen.source_binding_c_name(capture.name)
        statements.append(
            IRAssign(
                target=IRFieldAccess(obj=IRVar(name=env_var), field=field_name, arrow=False),
                value=IRVar(name=binding_name),
            )
        )
    gen._fn_ptr_envs[name] = (fn_name, env_var)


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
            left=IRFieldAccess(
                obj=IRVar(name=env_var),
                field=source_binding_c_name(capture.name),
                arrow=False,
            ),
            op="=",
            right=IRVar(name=gen.source_binding_c_name(capture.name)),
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
