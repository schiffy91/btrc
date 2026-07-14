"""Exclude collection shape mutations from ARC collector snapshots."""

from __future__ import annotations

from .completion import sequence_may_fall_through
from .nodes import (
    CType,
    IRAddressOf,
    IRBlock,
    IRCall,
    IRCase,
    IRCast,
    IRDoWhile,
    IRExprStmt,
    IRFor,
    IRFunctionDef,
    IRIf,
    IRReturn,
    IRSwitch,
    IRVar,
    IRVarDecl,
    IRWhile,
)
from .topology_queries import contains_self_storage_mutation


def install_collection_topology_boundary(gen, function: IRFunctionDef) -> bool:
    """Protect one directly mutating collection method as an atomic shape edit."""
    if function.body is None or not contains_self_storage_mutation(function.body):
        return False

    token = gen.fresh_temp("__btrc_topology_scope")
    cleanup_enabled = bool(getattr(gen, "cross_function_cleanup_enabled", False))
    marker = gen.fresh_temp("__btrc_topology_cleanup") if cleanup_enabled else None
    gen.use_helper("__btrc_arc_topology_begin")
    gen.use_helper("__btrc_arc_topology_complete")
    if cleanup_enabled:
        gen.use_helper("__btrc_cleanup_mark")
        gen.use_helper("__btrc_arc_topology_cleanup")
        gen.use_helper("__btrc_discard_cleanups_to")

    _rewrite_block(gen, function, function.body, token, marker)
    if sequence_may_fall_through(function.body.stmts):
        function.body.stmts.extend(_epilogue(token, marker))
    function.body.stmts[0:0] = _prologue(gen, token, marker)
    return True


def _prologue(gen, token: str, marker: str | None) -> list:
    statements = []
    if marker is not None:
        statements.append(
            IRVarDecl(
                c_type=CType(text="int"),
                name=marker,
                init=IRCall(
                    callee="__btrc_cleanup_mark",
                    args=[],
                    helper_ref="__btrc_cleanup_mark",
                ),
            )
        )
    token_declaration = IRVarDecl(
        c_type=CType(text="void*"),
        name=token,
        init=IRCall(
            callee="__btrc_arc_topology_begin",
            args=[],
            helper_ref="__btrc_arc_topology_begin",
        ),
    )
    statements.append(token_declaration)
    if marker is not None:
        from .gen.cleanup_slots import register_cleanup_slot

        statements.append(
            IRExprStmt(
                expr=register_cleanup_slot(
                    gen,
                    token_declaration,
                    IRVar(name="__btrc_arc_topology_cleanup"),
                    direct=True,
                )
            )
        )
    return statements


def _epilogue(token: str, marker: str | None) -> list:
    statements = [
        IRExprStmt(
            expr=IRCall(
                callee="__btrc_arc_topology_complete",
                args=[
                    IRCast(
                        target_type=CType(text="void* volatile*"),
                        expr=IRAddressOf(expr=IRVar(name=token)),
                    )
                ],
                helper_ref="__btrc_arc_topology_complete",
            )
        )
    ]
    if marker is not None:
        statements.append(
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_discard_cleanups_to",
                    args=[IRVar(name=marker)],
                    helper_ref="__btrc_discard_cleanups_to",
                )
            )
        )
    return statements


def _rewrite_block(
    gen,
    function: IRFunctionDef,
    block: IRBlock,
    token: str,
    marker: str | None,
) -> None:
    rewritten = []
    for statement in block.stmts:
        _rewrite_nested(gen, function, statement, token, marker)
        if isinstance(statement, IRReturn):
            if statement.value is not None:
                result = gen.fresh_temp("__btrc_topology_return")
                rewritten.append(
                    IRVarDecl(
                        c_type=function.return_type,
                        name=result,
                        init=statement.value,
                    )
                )
                statement.value = IRVar(name=result)
            rewritten.extend(_epilogue(token, marker))
        rewritten.append(statement)
    block.stmts = rewritten


def _rewrite_nested(
    gen,
    function: IRFunctionDef,
    statement,
    token: str,
    marker: str | None,
) -> None:
    if isinstance(statement, IRBlock):
        _rewrite_block(gen, function, statement, token, marker)
    elif isinstance(statement, IRIf):
        _rewrite_block(gen, function, statement.then_block, token, marker)
        if statement.else_block is not None:
            _rewrite_block(gen, function, statement.else_block, token, marker)
    elif isinstance(statement, (IRWhile, IRDoWhile, IRFor)):
        _rewrite_block(gen, function, statement.body, token, marker)
    elif isinstance(statement, IRSwitch):
        for case in statement.cases:
            _rewrite_case(gen, function, case, token, marker)


def _rewrite_case(
    gen,
    function: IRFunctionDef,
    case: IRCase,
    token: str,
    marker: str | None,
) -> None:
    block = IRBlock(stmts=case.body)
    _rewrite_block(gen, function, block, token, marker)
    case.body = block.stmts


__all__ = [
    "install_collection_topology_boundary",
]
