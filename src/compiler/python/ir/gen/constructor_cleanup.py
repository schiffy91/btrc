"""Exception cleanup guards for allocating constructor wrappers."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRCall,
    IRExprStmt,
    IRFunctionRef,
    IRVar,
    IRVarDecl,
)
from .feature_scan import program_uses_trycatch


def constructor_cleanup_guard(
    gen,
    self_declaration: IRVarDecl,
):
    """Return registration/discard statements around a throwing init call."""
    if not program_uses_exceptions(gen):
        return [], []
    gen.helpers.use("__btrc_cleanup_mark")
    gen.helpers.use("__btrc_discard_cleanups_to")
    gen.helpers.use("__btrc_arc_abandon")
    from .cleanup_slots import register_cleanup_slot

    mark = gen.fresh_temp("__btrc_constructor_cleanup")
    before = [
        IRVarDecl(
            c_type=CType(text="int"),
            name=mark,
            init=IRCall(
                callee="__btrc_cleanup_mark",
                args=[],
                helper_ref="__btrc_cleanup_mark",
            ),
        ),
        IRExprStmt(
            expr=register_cleanup_slot(
                gen,
                self_declaration,
                IRFunctionRef(name="__btrc_arc_abandon"),
                direct=True,
            )
        ),
    ]
    after = [
        IRExprStmt(
            expr=IRCall(
                callee="__btrc_discard_cleanups_to",
                args=[IRVar(name=mark)],
                helper_ref="__btrc_discard_cleanups_to",
            )
        )
    ]
    return before, after


def program_uses_exceptions(gen) -> bool:
    """Return the module-wide ownership contract for throwing constructors."""
    cached = getattr(gen, "program_has_exceptions", None)
    if cached is not None:
        return bool(cached)
    return program_uses_trycatch(gen.analyzed.program)


__all__ = ["constructor_cleanup_guard", "program_uses_exceptions"]
