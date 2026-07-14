"""Return-path rewriting for lifted pthread wrapper functions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ..nodes import (
    CType,
    IRBlock,
    IRDoWhile,
    IRFor,
    IRIf,
    IRLiteral,
    IRReturn,
    IRStmt,
    IRSwitch,
    IRVar,
    IRVarDecl,
    IRWhile,
)
from .thread_values import box_thread_result

if TYPE_CHECKING:
    from ...ast_nodes import TypeExpr
    from .generator import IRGenerator


def rewrite_thread_returns(
    gen: IRGenerator,
    block: IRBlock,
    return_type: TypeExpr | None,
    cleanup_factory: Callable[[], list[IRStmt]],
) -> IRBlock:
    """Box every structured return and run capture cleanup after evaluation."""
    block.stmts = _rewrite_statements(gen, block.stmts, return_type, cleanup_factory)
    return block


def _rewrite_statements(gen, statements, return_type, cleanup_factory):
    rewritten = []
    for statement in statements:
        if isinstance(statement, IRReturn):
            rewritten.extend(_rewrite_return(gen, statement, return_type, cleanup_factory))
            continue
        if isinstance(statement, IRIf):
            _rewrite_block(gen, statement.then_block, return_type, cleanup_factory)
            _rewrite_block(gen, statement.else_block, return_type, cleanup_factory)
        elif isinstance(statement, (IRWhile, IRDoWhile, IRFor)):
            _rewrite_block(gen, statement.body, return_type, cleanup_factory)
        elif isinstance(statement, IRSwitch):
            for case in statement.cases:
                case.body = _rewrite_statements(gen, case.body, return_type, cleanup_factory)
        elif isinstance(statement, IRBlock):
            _rewrite_block(gen, statement, return_type, cleanup_factory)
        rewritten.append(statement)
    return rewritten


def _rewrite_block(gen, block, return_type, cleanup_factory):
    if block is not None:
        rewrite_thread_returns(gen, block, return_type, cleanup_factory)


def _rewrite_return(gen, statement, return_type, cleanup_factory):
    value = statement.value or IRLiteral(text="NULL")
    boxed = box_thread_result(gen, value, return_type)
    cleanup = cleanup_factory()
    if not cleanup:
        return [IRReturn(value=boxed)]

    result_name = gen.fresh_temp("__btrc_thread_result")
    return [
        IRVarDecl(
            c_type=CType(text="void*"),
            name=result_name,
            init=boxed,
        ),
        *cleanup,
        IRReturn(value=IRVar(name=result_name)),
    ]
