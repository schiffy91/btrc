"""Ownership transaction for managed compound updates."""

from __future__ import annotations

from collections.abc import Callable

from ..nodes import (
    CType,
    IRBinOp,
    IRCommaExpr,
    IRExpr,
    IRLiteral,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from .managed_values import poll_released_values, release_value, retain_value
from .temporary_cleanup import cleanup_registration


def lower_managed_compound_update(
    gen,
    *,
    value_type,
    right_type,
    old_expr: IRExpr,
    current_expr: IRExpr | None,
    right_expr: IRExpr,
    compute: Callable[[IRExpr, IRExpr], IRExpr],
    commit: Callable[[IRExpr | None, IRExpr], list[IRExpr]],
    result_expr: Callable[[], IRExpr],
    old_temporary_owned: bool,
    right_owned: bool,
    right_keep: bool,
    release_replaced_old: bool,
    transfer_before_commit: bool = False,
    c_type: Callable[[object], str],
    fresh_temp: Callable[[str], str],
    record_decl: Callable[[IRVarDecl], None],
    cleanup_active: bool,
    activate_cleanup: Callable[[], None] | None = None,
) -> IRExpr:
    """Evaluate, replace, and clean one managed value exactly once."""
    if release_replaced_old != (current_expr is not None):
        raise ValueError("managed update current snapshot must match release policy")
    old_decl = _temporary(
        value_type,
        "__btrc_update_old",
        c_type,
        fresh_temp,
        record_decl,
    )
    right_decl = _temporary(
        right_type,
        "__btrc_update_rhs",
        c_type,
        fresh_temp,
        record_decl,
    )
    replacement_decl = _temporary(
        value_type,
        "__btrc_update_new",
        c_type,
        fresh_temp,
        record_decl,
    )
    current_decl = None
    if current_expr is not None:
        current_decl = _temporary(
            value_type,
            "__btrc_update_current",
            c_type,
            fresh_temp,
            record_decl,
        )
    declarations = [old_decl, right_decl, replacement_decl]
    if current_decl is not None:
        declarations.append(current_decl)
    old = IRVar(name=old_decl.name)
    right = IRVar(name=right_decl.name)
    replacement = IRVar(name=replacement_decl.name)
    current = IRVar(name=current_decl.name) if current_decl is not None else None
    sequence = [IRBinOp(left=old, op="=", right=old_expr)]
    if not old_temporary_owned:
        sequence.append(retain_value(gen, old, value_type))
    _guard(
        gen,
        old_decl,
        value_type,
        declarations,
        sequence,
        cleanup_active,
        fresh_temp,
        activate_cleanup,
    )
    sequence.append(IRBinOp(left=right, op="=", right=right_expr))
    if right_owned:
        _guard(
            gen,
            right_decl,
            right_type,
            declarations,
            sequence,
            cleanup_active,
            fresh_temp,
            activate_cleanup,
        )
    kept = None
    if right_keep:
        kept_decl = _temporary(
            right_type,
            "__btrc_update_kept_rhs",
            c_type,
            fresh_temp,
            record_decl,
        )
        declarations.append(kept_decl)
        kept = IRVar(name=kept_decl.name)
        sequence.extend(
            [
                retain_value(gen, right, right_type),
                IRBinOp(left=kept, op="=", right=right),
            ]
        )
        _guard(
            gen,
            kept_decl,
            right_type,
            declarations,
            sequence,
            cleanup_active,
            fresh_temp,
            activate_cleanup,
        )
    _guard(
        gen,
        replacement_decl,
        value_type,
        declarations,
        sequence,
        cleanup_active,
        fresh_temp,
        activate_cleanup,
    )
    sequence.append(IRBinOp(left=replacement, op="=", right=compute(old, right)))
    # The RHS may itself rebind the target.  Commit against the value that is
    # in the slot now; ``old`` is a separate +1 pin used only by the operator.
    if current is not None and current_expr is not None:
        sequence.append(IRBinOp(left=current, op="=", right=current_expr))

    commit_value = replacement
    if transfer_before_commit:
        transfer_decl = _temporary(
            value_type,
            "__btrc_update_transfer",
            c_type,
            fresh_temp,
            record_decl,
        )
        declarations.append(transfer_decl)
        commit_value = IRVar(name=transfer_decl.name)
        sequence.extend(
            [
                IRBinOp(left=commit_value, op="=", right=replacement),
                _clear(replacement),
            ]
        )
    sequence.extend(commit(current, commit_value))
    if not transfer_before_commit:
        sequence.append(_clear(replacement))
    if release_replaced_old:
        assert current is not None
        sequence.extend(
            _release_and_clear(
                gen,
                current,
                value_type,
                declarations,
                c_type,
                fresh_temp,
                record_decl,
            )
        )
    sequence.extend(
        _release_and_clear(
            gen,
            old,
            value_type,
            declarations,
            c_type,
            fresh_temp,
            record_decl,
        )
    )
    if kept is not None:
        sequence.extend(
            _release_and_clear(
                gen,
                kept,
                right_type,
                declarations,
                c_type,
                fresh_temp,
                record_decl,
            )
        )
    if right_owned:
        sequence.extend(
            _release_and_clear(
                gen,
                right,
                right_type,
                declarations,
                c_type,
                fresh_temp,
                record_decl,
            )
        )

    released_types = [value_type]
    if right_owned or right_keep:
        released_types.append(right_type)
    flush = poll_released_values(gen, *released_types)
    if flush is not None:
        sequence.append(flush)

    sequence.append(result_expr())
    return IRStmtExpr(stmts=declarations, result=IRCommaExpr(expressions=sequence))


def _guard(
    gen,
    declaration,
    type_expr,
    declarations,
    sequence,
    cleanup_active,
    fresh_temp,
    activate_cleanup,
):
    guard_decls, guard_exprs = cleanup_registration(
        gen,
        declaration,
        type_expr,
        "__btrc_update_cleanup",
        active=cleanup_active,
        fresh_temp=fresh_temp,
        activate_cleanup=activate_cleanup,
    )
    declarations.extend(guard_decls)
    sequence.extend(guard_exprs)


def _release_and_clear(
    gen,
    value,
    type_expr,
    declarations,
    render,
    fresh_temp,
    record_decl,
):
    saved_decl = _temporary(
        type_expr,
        "__btrc_update_released",
        render,
        fresh_temp,
        record_decl,
    )
    declarations.append(saved_decl)
    saved = IRVar(name=saved_decl.name)
    return [
        IRBinOp(left=saved, op="=", right=value),
        _clear(value),
        release_value(gen, saved, type_expr),
    ]


def _clear(value):
    return IRBinOp(left=value, op="=", right=IRLiteral(text="NULL"))


def _temporary(type_expr, prefix, render, fresh_temp, record_decl):
    declaration = IRVarDecl(
        c_type=CType(text=render(type_expr)),
        name=fresh_temp(prefix),
        init=IRLiteral(text="0"),
    )
    record_decl(declaration)
    return declaration


__all__ = ["lower_managed_compound_update"]
