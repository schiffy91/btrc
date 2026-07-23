"""Owned capture-environment disposal for lifted thread entries."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDef,
    IRFunctionRef,
    IRIf,
    IRLiteral,
    IRParam,
    IRSizeof,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .parameters import source_binding_c_name
from .types import CTypeRenderer


def managed_capture_type(gen, capture):
    """Return a direct managed capture type, excluding arrays/raw pointers."""
    capture_type = capture.type
    if capture_type is None or capture_type.is_array:
        return None
    from .managed_values import is_managed_type

    return capture_type if is_managed_type(gen, capture_type) else None


def emit_capture_disposer(
    gen,
    fn,
    env_name: str,
    spawn_id: int,
    type_renderer: CTypeRenderer,
) -> str | None:
    """Emit one completion-safe owner for a captured lambda environment."""
    if not fn.captures:
        return None

    adapters: list[str] = []
    for capture in fn.captures:
        capture_type = managed_capture_type(gen, capture)
        if capture_type is None:
            continue
        name = f"__btrc_spawn_capture_release_{spawn_id}_{capture.name}"
        gen.module.function_defs.append(
            _capture_release_adapter(
                gen,
                name,
                env_name,
                capture.name,
                capture_type,
                type_renderer,
            )
        )
        adapters.append(name)

    disposer_name = f"__btrc_spawn_env_dispose_{spawn_id}"
    gen.module.function_defs.append(_capture_disposer(gen, disposer_name, env_name, adapters))
    return disposer_name


def _capture_release_adapter(
    gen,
    name: str,
    env_name: str,
    field_name: str,
    capture_type,
    type_renderer: CTypeRenderer,
) -> IRFunctionDef:
    from .managed_values import release_value

    env = IRVar(name="__env")
    field = IRFieldAccess(
        obj=env,
        field=source_binding_c_name(field_name),
        arrow=True,
    )
    value = IRVar(name="__value")
    return IRFunctionDef(
        name=name,
        return_type=CType(text="void"),
        params=[IRParam(c_type=CType(text="void*"), name="__raw")],
        body=IRBlock(
            stmts=[
                IRVarDecl(
                    c_type=CType(text=f"{env_name}*"),
                    name=env.name,
                    init=IRCast(
                        target_type=CType(text=f"{env_name}*"),
                        expr=IRVar(name="__raw"),
                    ),
                ),
                IRVarDecl(
                    c_type=CType(text=type_renderer.render(capture_type)),
                    name=value.name,
                    init=field,
                ),
                IRAssign(target=field, value=IRLiteral(text="NULL")),
                IRExprStmt(expr=release_value(gen, value, capture_type)),
            ]
        ),
        is_static=True,
    )


def _capture_disposer(
    gen,
    name: str,
    env_name: str,
    adapters: list[str],
) -> IRFunctionDef:
    env = IRVar(name="__env")
    has_error = IRVar(name="__has_error")
    first_error = IRVar(name="__first_error")
    error = IRVar(name="__error")
    body = [
        IRVarDecl(
            c_type=CType(text=f"{env_name}*"),
            name=env.name,
            init=IRCast(
                target_type=CType(text=f"{env_name}*"),
                expr=IRVar(name="__raw"),
            ),
        )
    ]
    if adapters:
        gen.helpers.use("__btrc_arc_guard_hook")
        gen.helpers.use("__btrc_raise_captured")
        gen.helpers.use("__btrc_throw")
        body.extend(
            [
                IRVarDecl(
                    c_type=CType(text="int"),
                    name=has_error.name,
                    init=IRLiteral(text="0"),
                ),
                _error_buffer(first_error.name),
                _error_buffer(error.name),
            ]
        )
        body.extend(_guard_capture(adapter, env, has_error, first_error, error) for adapter in adapters)
    body.append(IRExprStmt(expr=IRCall(callee="free", args=[env])))
    if adapters:
        body.append(
            IRIf(
                condition=has_error,
                then_block=IRBlock(
                    stmts=[
                        IRExprStmt(
                            expr=IRCall(
                                callee="__btrc_raise_captured",
                                args=[IRFunctionRef(name="__btrc_throw"), first_error],
                                helper_ref="__btrc_raise_captured",
                            )
                        )
                    ]
                ),
            )
        )
    return IRFunctionDef(
        name=name,
        return_type=CType(text="void"),
        params=[IRParam(c_type=CType(text="void*"), name="__raw")],
        body=IRBlock(stmts=body),
        is_static=True,
    )


def _error_buffer(name: str) -> IRVarDecl:
    return IRVarDecl(
        c_type=CType(text="char"),
        name=name,
        array_size=IRLiteral(text="1024"),
        init=IRLiteral(text='""'),
    )


def _guard_capture(adapter, env, has_error, first_error, error):
    guarded = IRCall(
        callee="__btrc_arc_guard_hook",
        args=[
            IRFunctionRef(name=adapter),
            env,
            error,
            IRSizeof(operand=error),
        ],
        helper_ref="__btrc_arc_guard_hook",
    )
    return IRIf(
        condition=IRBinOp(
            left=guarded,
            op="&&",
            right=IRUnaryOp(op="!", operand=has_error),
        ),
        then_block=IRBlock(
            stmts=[
                IRExprStmt(
                    expr=IRCall(
                        callee="memcpy",
                        args=[
                            first_error,
                            error,
                            IRSizeof(operand=first_error),
                        ],
                    )
                ),
                IRAssign(target=has_error, value=IRLiteral(text="1")),
            ]
        ),
    )


__all__ = ["emit_capture_disposer", "managed_capture_type"]
