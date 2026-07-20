"""Managed-return ABI lowering for monomorphized generic methods."""

from __future__ import annotations

from ...nodes import CType, IRCall, IRCast, IRExprStmt, IRReturn, IRVar, IRVarDecl
from ..managed_values import retain_value
from .user_emitter_scopes import (
    emit_return_cleanup_discard,
    emit_return_release,
    emit_try_pop,
    managed_local_type,
)


def lower_generic_return(emitter, statement):
    """Return a caller-owned managed value from one generic specialization."""
    if statement.value is None:
        pop = emit_try_pop(emitter, emitter._try_depth)
        cleanup_discard = emit_return_cleanup_discard(emitter)
        return emit_return_release(emitter, None) + pop + cleanup_discard + [IRReturn(value=None)]

    from ..callable_boundaries import reject_persistent_callable_escape
    from .user_callable_provenance import generic_callable_return_abi

    reject_persistent_callable_escape(
        emitter._gen,
        emitter._return_type,
        statement.value,
        "a function return",
        callable_abi=lambda value: generic_callable_return_abi(
            emitter,
            value,
        ),
    )

    from ..prepared_values import prepare_generic_value

    prepared = prepare_generic_value(
        emitter,
        statement.value,
        emitter._return_type,
    )
    value = prepared.value
    from ..upcast import upcast_class_pointer

    value = upcast_class_pointer(
        emitter._gen,
        emitter._return_type,
        prepared.effective_type,
        value,
    )

    managed_return = bool(emitter._return_owned and emitter._is_managed_type(emitter._return_type))
    returned_local = None
    local_owned = False
    from ....ast_nodes import Identifier

    if isinstance(statement.value, Identifier):
        local_owned = managed_local_type(emitter, statement.value.name) is not None
        if managed_return and local_owned and not prepared.converted:
            returned_local = statement.value.name
    expression_owned = bool(managed_return and (prepared.owned or (local_owned and not prepared.converted)))
    promote_borrowed = bool(managed_return and not expression_owned)
    releases = emit_return_release(emitter, returned_local)
    pop = emit_try_pop(emitter, emitter._try_depth)
    cleanup_discard = emit_return_cleanup_discard(emitter)
    if not releases and not pop and not cleanup_discard and not promote_borrowed:
        return [IRReturn(value=_maybe_launder(emitter, value, managed_return))]

    temporary = IRVarDecl(
        c_type=CType(text=emitter._return_c_type),
        name=emitter._fresh_temp("__btrc_ret"),
        init=value,
    )
    emitter._func_var_decls.append(temporary)
    result = IRVar(name=temporary.name)
    promote = [IRExprStmt(expr=retain_value(emitter._gen, result, emitter._return_type))] if promote_borrowed else []
    prefix = [temporary, *promote]
    if managed_return and returned_local is None:
        from ..temporary_cleanup import cleanup_registration

        declarations, registrations = cleanup_registration(
            emitter._gen,
            temporary,
            emitter._return_type,
            "__btrc_return_cleanup",
            active=emitter._exception_cleanup_active(),
            fresh_temp=emitter._fresh_temp,
            activate_cleanup=emitter._activate_cleanup_registration,
        )
        prefix.extend(declarations)
        prefix.extend(IRExprStmt(expr=registration) for registration in registrations)
        cleanup_discard = emit_return_cleanup_discard(emitter)
    return [
        *prefix,
        *releases,
        *pop,
        *cleanup_discard,
        IRReturn(value=_maybe_launder(emitter, result, managed_return)),
    ]


def _maybe_launder(emitter, value, managed_return):
    if not managed_return or emitter._trycatch_depth <= 0 or emitter._gen is None:
        return value
    emitter._gen.use_helper("__btrc_launder")
    return IRCast(
        target_type=CType(text=emitter._return_c_type),
        expr=IRCall(
            callee="__btrc_launder",
            args=[value],
            helper_ref="__btrc_launder",
        ),
    )


__all__ = ["lower_generic_return"]
