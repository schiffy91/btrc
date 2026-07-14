"""Exception registration for expression-local owned pointer slots."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRLiteral,
    IRTernary,
    IRVar,
    IRVarDecl,
)
from .managed_values import (
    STRING_RUNTIME_NAME,
    cleanup_destroy_symbol,
    is_string_type,
    runtime_name,
)


def cleanup_registration(
    gen,
    slot: IRVar,
    type_expr,
    prefix: str,
    *,
    active: bool | None = None,
    fresh_temp=None,
    activate_cleanup=None,
):
    """Return hoisted state plus a one-time cleanup-registration expression."""
    if active is None:
        active = gen.exception_cleanup_active()
    if not active:
        return [], []
    (activate_cleanup or gen.mark_cleanup_registration)()
    string_cleanup = is_string_type(gen, type_expr)
    register_helper = "__btrc_register_direct_cleanup" if string_cleanup else "__btrc_register_cleanup"
    gen.use_helper(register_helper)
    fresh_temp = fresh_temp or gen.fresh_temp
    flag_decl = IRVarDecl(
        c_type=CType(text="bool"),
        name=fresh_temp(prefix),
        init=IRLiteral(text="false"),
    )
    gen._func_var_decls.append(flag_decl)
    flag = IRVar(name=flag_decl.name)
    emitted_name = runtime_name(gen, type_expr)
    destroy = cleanup_destroy_symbol(emitted_name)
    if emitted_name == STRING_RUNTIME_NAME:
        gen.use_helper(destroy)
    args = [
        IRCast(
            target_type=CType(text="void**"),
            expr=IRAddressOf(expr=slot),
        ),
        IRVar(name=destroy),
    ]
    if not string_cleanup:
        args.append(_visit_value(gen, type_expr))
    register = IRCall(
        callee=register_helper,
        args=args,
        helper_ref=register_helper,
    )
    register_once = IRTernary(
        condition=flag,
        true_expr=IRLiteral(text="0"),
        false_expr=IRCommaExpr(
            expressions=[
                register,
                IRBinOp(left=flag, op="=", right=IRLiteral(text="true")),
                IRLiteral(text="0"),
            ]
        ),
    )
    return [flag_decl], [register_once]


def _visit_value(gen, type_expr):
    if is_string_type(gen, type_expr):
        return IRLiteral(text="NULL")
    from .cycle_metadata import visitor_for_type

    visitor = visitor_for_type(gen, type_expr)
    return IRVar(name=visitor) if visitor else IRLiteral(text="NULL")


__all__ = ["cleanup_registration"]
