"""Cleanup primitives for full-call ownership boundaries."""

from ..nodes import CType, IRBinOp, IRLiteral, IRVar, IRVarDecl
from .managed_values import is_arc_type, release_value


def register_temporary(
    gen,
    declaration,
    type_expr,
    declarations,
    prefix,
    fresh_temp,
    cleanup_active,
    flag_prefix,
    activate_cleanup,
):
    from .temporary_cleanup import cleanup_registration

    cleanup_decls, cleanup_exprs = cleanup_registration(
        gen,
        declaration,
        type_expr,
        flag_prefix,
        active=cleanup_active,
        fresh_temp=fresh_temp,
        activate_cleanup=activate_cleanup,
    )
    declarations.extend(cleanup_decls)
    prefix.extend(cleanup_exprs)


def release_and_clear(
    gen,
    value,
    type_expr,
    declarations,
    fresh_temp,
    record_decl,
    c_type,
):
    from .arc_ops import poll_release_batch

    saved_decl = temporary(
        fresh_temp,
        record_decl,
        "__btrc_released_operand",
        c_type,
    )
    declarations.append(saved_decl)
    saved = IRVar(name=saved_decl.name)
    expressions = [
        IRBinOp(left=saved, op="=", right=value),
        IRBinOp(left=value, op="=", right=IRLiteral(text="NULL")),
        release_value(gen, saved, type_expr),
    ]
    flush = poll_release_batch(
        gen,
        types=[type_expr] if is_arc_type(gen, type_expr) else [],
    )
    if flush is not None:
        expressions.append(flush)
    return expressions


def temporary(
    fresh_temp,
    record_decl,
    prefix: str,
    c_type: str,
    init=None,
) -> IRVarDecl:
    declaration = IRVarDecl(
        c_type=CType(text=c_type),
        name=fresh_temp(prefix),
        init=init,
    )
    record_decl(declaration)
    return declaration


__all__ = ["register_temporary", "release_and_clear", "temporary"]
