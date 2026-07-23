"""ARC bookkeeping specific to returns across try/catch boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCast,
    IRExprStmt,
    IRLiteral,
    IRReturn,
    IRStmt,
    IRVar,
    IRVarDecl,
)
from .try_stack import pop_try_frames

if TYPE_CHECKING:
    from ...ast_nodes import ReturnStmt
    from .lowerer import IRLowerer
    from .types import CTypeRenderer


def lower_return(
    gen: IRLowerer,
    node: ReturnStmt,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> list[IRStmt]:
    """Lower one return while enforcing the managed-value return ABI.

    A btrc function or method returning a class value always gives its caller
    one owned reference. Already-owned expressions transfer that reference;
    borrowed parameters, ``self``, fields, and aliases are retained before
    any local owners are released.
    """
    from ...ast_nodes import Identifier
    from .arc import _emit_return_release
    from .managed_values import is_managed_type, retain_value
    from .prepared_values import prepare_normal_value
    from .type_resolution import canonical_type

    if node.value is None:
        try_pop = _emit_return_try_pop(gen)
        cleanup_discard = _emit_return_cleanup_discard(gen)
        value = IRLiteral(text="0") if gen._normalizing_void_main else None
        return _emit_return_release(gen, None) + try_pop + cleanup_discard + [IRReturn(value=value)]

    from .callable_boundaries import reject_persistent_callable_escape

    reject_persistent_callable_escape(
        gen,
        gen.current_return_type,
        node.value,
        "a function return",
    )
    prepared = prepare_normal_value(
        gen,
        node.value,
        gen.current_return_type,
        type_renderer,
        default_arguments=default_arguments,
    )
    value = prepared.value
    value_type = prepared.effective_type
    from .upcast import upcast_class_pointer

    value = upcast_class_pointer(
        gen,
        gen.current_return_type,
        value_type,
        value,
        type_renderer,
    )
    managed_value_type = is_managed_type(gen, gen.current_return_type)
    managed_return = managed_value_type and gen.current_return_owned
    expression_owned = bool(managed_value_type and prepared.owned)
    owned_value = bool(managed_return and expression_owned)
    returned_local = None
    if managed_value_type and isinstance(node.value, Identifier):
        if gen.managed_local_type(node.value.name) is not None:
            if managed_return and not prepared.converted:
                owned_value = True
                returned_local = node.value.name

    return_type = canonical_type(
        gen.current_return_type,
        gen.analyzed.typedef_table,
    )
    if (
        isinstance(node.value, Identifier)
        and return_type is not None
        and return_type.base == "Thread"
        and gen.local_cleanup_kind(node.value.name) == "thread"
    ):
        returned_local = node.value.name

    release_stmts = _emit_return_release(gen, returned_local)
    promote_borrowed = managed_return and not owned_value
    # Lowering the value can register temporary exception cleanups. Query the
    # active marker only after that lowering, and query it again after a return
    # temporary is registered below.
    try_pop = _emit_return_try_pop(gen)
    cleanup_discard = _emit_return_cleanup_discard(gen)
    if not release_stmts and not try_pop and not cleanup_discard and not promote_borrowed:
        return [IRReturn(value=_maybe_launder_return(gen, value))]

    temporary = IRVarDecl(
        c_type=CType(text=gen.current_return_c_type),
        name=gen.fresh_temp("__btrc_ret"),
        init=value,
    )
    result = IRVar(name=temporary.name)
    promote = []
    if promote_borrowed:
        promote.append(IRExprStmt(expr=retain_value(gen, result, gen.current_return_type)))
    prefix = [temporary, *promote]
    if managed_return and returned_local is None:
        # A later local destructor may throw across this return path. Give the
        # in-flight caller-owned result its own cleanup slot so that longjmp
        # cannot strand a fresh result. A returned managed local already has a
        # registered source slot and must not be registered twice.
        from .cleanup_registration import maybe_register_cleanup
        from .managed_values import runtime_name

        runtime_type = runtime_name(gen, gen.current_return_type)
        maybe_register_cleanup(
            gen,
            temporary.name,
            runtime_type,
            prefix,
        )
        cleanup_discard = _emit_return_cleanup_discard(gen)
    return [
        *prefix,
        *release_stmts,
        *try_pop,
        *cleanup_discard,
        IRReturn(value=_maybe_launder_return(gen, result)),
    ]


def _emit_return_try_pop(gen: IRLowerer) -> list[IRStmt]:
    """Discard cleanups and pop try levels bypassed by a return."""
    return _emit_try_pop(gen, gen.in_try_depth)


def _emit_return_cleanup_discard(gen: IRLowerer) -> list[IRStmt]:
    """Forget this function's registered slots after ordinary ARC release."""
    from .cleanup_scopes import cleanup_scope_exit

    return cleanup_scope_exit(gen, gen.get_return_cleanup_marker())


def _emit_try_pop(gen: IRLowerer, depth: int) -> list[IRStmt]:
    """Discard cleanup registrations and pop ``depth`` active try frames."""
    if depth <= 0:
        return []
    stmts: list[IRStmt] = []
    # A try without managed locals has no registered cleanup level to discard.
    if gen.helpers.roots & {
        "__btrc_register_cleanup",
        "__btrc_register_direct_cleanup",
    }:
        gen.helpers.use("__btrc_discard_cleanups")
        level = IRVar(name="__btrc_try_top")
        if depth > 1:
            level = IRBinOp(
                left=level,
                op="-",
                right=IRLiteral(text=str(depth - 1)),
            )
        stmts.append(
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_discard_cleanups",
                    args=[level],
                    helper_ref="__btrc_discard_cleanups",
                )
            )
        )
    stmts.extend(pop_try_frames(depth))
    return stmts


def _maybe_launder_return(gen: IRLowerer, value):
    """Prevent setjmp branch folding for managed returns inside try/catch."""
    if gen.in_trycatch_depth <= 0:
        return value
    return_type = gen.current_return_type
    from .managed_values import is_managed_type

    if not is_managed_type(gen, return_type):
        return value
    gen.helpers.use("__btrc_launder")
    laundered = IRCall(
        callee="__btrc_launder",
        args=[value],
        helper_ref="__btrc_launder",
    )
    return IRCast(
        target_type=CType(text=gen.current_return_c_type),
        expr=laundered,
    )
