"""Exception-safe replacement of persistent managed value slots."""

from __future__ import annotations

from ..nodes import CType, IRBinOp, IRCommaExpr, IRLiteral, IRStmtExpr, IRVar, IRVarDecl


def lower_managed_slot_replacement(
    lifetime,
    *,
    target,
    target_type,
    value,
    value_owned,
    c_type,
    fresh_temp,
    record_decl,
    cleanup_active,
    activate_cleanup=None,
):
    """Commit a new +1 to ``target`` before releasing its prior value."""
    replacement_decl = _temporary(
        target_type,
        "__btrc_slot_new",
        c_type,
        fresh_temp,
        record_decl,
    )
    old_decl = _temporary(
        target_type,
        "__btrc_slot_old",
        c_type,
        fresh_temp,
        record_decl,
    )
    declarations = [replacement_decl, old_decl]
    replacement = IRVar(name=replacement_decl.name)
    old = IRVar(name=old_decl.name)
    sequence = [IRBinOp(left=replacement, op="=", right=value)]
    if not value_owned:
        sequence.append(lifetime.retain_value(replacement, target_type))
    cleanup_decls, cleanup_exprs = lifetime.cleanup_registration(
        replacement_decl,
        target_type,
        "__btrc_slot_cleanup",
        active=cleanup_active,
        fresh_temp=fresh_temp,
        activate_cleanup=activate_cleanup,
    )
    declarations.extend(cleanup_decls)
    sequence.extend(cleanup_exprs)
    sequence.extend(
        [
            IRBinOp(left=old, op="=", right=target),
            IRBinOp(left=target, op="=", right=replacement),
            IRBinOp(
                left=replacement,
                op="=",
                right=IRLiteral(text="NULL"),
            ),
            lifetime.release_value(old, target_type),
        ]
    )
    flush = lifetime.poll_released_values(target_type)
    if flush is not None:
        sequence.append(flush)
    sequence.append(target)
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=sequence),
    )


def _temporary(type_expr, prefix, render, fresh_temp, record_decl):
    declaration = IRVarDecl(
        c_type=CType(text=render(type_expr)),
        name=fresh_temp(prefix),
        init=IRLiteral(text="NULL"),
    )
    record_decl(declaration)
    return declaration


__all__ = ["lower_managed_slot_replacement"]
