"""Exception cleanup guards for allocating constructor wrappers."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRAddressOf,
    IRCall,
    IRCast,
    IRExprStmt,
    IRLiteral,
    IRVar,
    IRVarDecl,
)
from .feature_scan import uses_trycatch


def constructor_cleanup_guard(
    gen,
    self_name: str,
    target_destroy_name: str,
    visit_name: str | None = None,
):
    """Return registration/discard statements around a throwing init call."""
    if not _program_uses_exceptions(gen):
        return [], []
    gen.use_helper("__btrc_cleanup_mark")
    gen.use_helper("__btrc_register_cleanup")
    gen.use_helper("__btrc_discard_cleanups_to")
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
            expr=IRCall(
                callee="__btrc_register_cleanup",
                args=[
                    IRCast(
                        target_type=CType(text="void**"),
                        expr=IRAddressOf(expr=IRVar(name=self_name)),
                    ),
                    IRVar(name=target_destroy_name),
                    IRVar(name=visit_name) if visit_name is not None else IRLiteral(text="NULL"),
                ],
                helper_ref="__btrc_register_cleanup",
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


def _program_uses_exceptions(gen) -> bool:
    # A freestanding translation unit cannot assume a TLS runtime. Explicit
    # try/catch lowering remains authoritative when the source requests it;
    # constructor wrappers must not pull hosted cleanup state merely because
    # the appended stdlib contains exception syntax elsewhere.
    if gen.freestanding:
        return False
    cached = getattr(gen, "_program_uses_exceptions", None)
    if cached is None:
        cached = any(uses_trycatch(declaration) for declaration in gen.analyzed.program.declarations)
        gen._program_uses_exceptions = cached
    return cached


__all__ = ["constructor_cleanup_guard"]
