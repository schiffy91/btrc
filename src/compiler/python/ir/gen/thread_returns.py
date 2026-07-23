"""Return-path rewriting for lifted pthread wrapper functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..nodes import (
    IRBlock,
    IRDoWhile,
    IRFor,
    IRIf,
    IRLiteral,
    IRReturn,
    IRSwitch,
    IRWhile,
)
from .thread_values import box_thread_result

if TYPE_CHECKING:
    from ...ast_nodes import TypeExpr
    from .lowerer import IRLowerer
    from .types import CTypeRenderer


def rewrite_thread_returns(
    gen: IRLowerer,
    block: IRBlock,
    return_type: TypeExpr | None,
    type_renderer: CTypeRenderer,
) -> IRBlock:
    """Box every structured return; the runtime owns capture cleanup."""
    block.stmts = _rewrite_statements(
        gen,
        block.stmts,
        return_type,
        type_renderer,
    )
    return block


def _rewrite_statements(gen, statements, return_type, type_renderer):
    rewritten = []
    for statement in statements:
        if isinstance(statement, IRReturn):
            rewritten.extend(
                _rewrite_return(
                    gen,
                    statement,
                    return_type,
                    type_renderer,
                )
            )
            continue
        if isinstance(statement, IRIf):
            _rewrite_block(gen, statement.then_block, return_type, type_renderer)
            _rewrite_block(gen, statement.else_block, return_type, type_renderer)
        elif isinstance(statement, (IRWhile, IRDoWhile, IRFor)):
            _rewrite_block(gen, statement.body, return_type, type_renderer)
        elif isinstance(statement, IRSwitch):
            for case in statement.cases:
                case.body = _rewrite_statements(
                    gen,
                    case.body,
                    return_type,
                    type_renderer,
                )
        elif isinstance(statement, IRBlock):
            _rewrite_block(gen, statement, return_type, type_renderer)
        rewritten.append(statement)
    return rewritten


def _rewrite_block(gen, block, return_type, type_renderer):
    if block is not None:
        rewrite_thread_returns(gen, block, return_type, type_renderer)


def _rewrite_return(gen, statement, return_type, type_renderer):
    value = statement.value or IRLiteral(text="NULL")
    boxed = box_thread_result(gen, value, return_type, type_renderer)
    return [IRReturn(value=boxed)]
