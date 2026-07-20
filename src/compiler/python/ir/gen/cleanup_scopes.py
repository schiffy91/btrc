"""Exception-cleanup registration lifetime markers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..nodes import CType, IRCall, IRExprStmt, IRStmt, IRVar, IRVarDecl

if TYPE_CHECKING:
    from .generator import IRGenerator


def cleanup_scope_entry(gen: IRGenerator, marker: str | None) -> list[IRStmt]:
    if marker is None:
        return []
    gen.use_helper("__btrc_cleanup_mark")
    return [
        IRVarDecl(
            c_type=CType(text="int"),
            name=marker,
            init=IRCall(
                callee="__btrc_cleanup_mark",
                args=[],
                helper_ref="__btrc_cleanup_mark",
            ),
        )
    ]


def cleanup_scope_exit(gen: IRGenerator, marker: str | None) -> list[IRStmt]:
    if marker is None:
        return []
    gen.use_helper("__btrc_discard_cleanups_to")
    return [
        IRExprStmt(
            expr=IRCall(
                callee="__btrc_discard_cleanups_to",
                args=[IRVar(name=marker)],
                helper_ref="__btrc_discard_cleanups_to",
            )
        )
    ]


def control_cleanup_exit(gen: IRGenerator, targets: set[str]) -> list[IRStmt]:
    return cleanup_scope_exit(gen, gen.get_control_cleanup_marker(targets))
