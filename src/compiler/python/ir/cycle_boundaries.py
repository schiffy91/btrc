"""Install deterministic drains at observable cycle-ownership boundaries."""

from __future__ import annotations

import dataclasses

from .completion import sequence_may_fall_through
from .nodes import (
    IRBlock,
    IRCall,
    IRCase,
    IRDoWhile,
    IRExprStmt,
    IRFor,
    IRFunctionDef,
    IRIf,
    IRModule,
    IRReturn,
    IRSwitch,
    IRWhile,
)

PUBLIC_COLLECTION_BASES = frozenset({"Array", "List", "Map", "Set", "Vector"})
_PROGRAM_ENTRIES = frozenset({"btrc_main", "main"})


def install_function_cycle_boundary(function: IRFunctionDef) -> bool:
    """Force-drain a release-bearing externally observable function."""
    if function.body is None or not contains_cyclable_release(function.body):
        return False
    _rewrite_block(function.body)
    if sequence_may_fall_through(function.body.stmts) and not _ends_with_flush(function.body.stmts):
        function.body.stmts.append(_flush_stmt())
    return True


def install_program_cycle_boundary(module: IRModule) -> bool:
    """Drain deferred suspects before a live executable entry point exits."""
    if not any(
        contains_cyclable_release(function.body) for function in module.function_defs if function.body is not None
    ):
        return False
    installed = False
    for function in module.function_defs:
        if function.name in _PROGRAM_ENTRIES:
            _rewrite_block(function.body)
            if sequence_may_fall_through(function.body.stmts) and not _ends_with_flush(function.body.stmts):
                function.body.stmts.append(_flush_stmt())
            installed = True
    return installed


def contains_cyclable_release(value) -> bool:
    """Whether structured IR can enqueue a graph-bearing release suspect."""
    if isinstance(value, IRCall):
        return value.helper_ref == "__btrc_arc_release" or value.callee == "__btrc_arc_release"
    if isinstance(value, (list, tuple)):
        return any(contains_cyclable_release(item) for item in value)
    if not dataclasses.is_dataclass(value):
        return False
    return any(
        contains_cyclable_release(item)
        for field in dataclasses.fields(value)
        if not isinstance((item := getattr(value, field.name)), str)
    )


def _rewrite_block(block: IRBlock) -> None:
    rewritten = []
    for statement in block.stmts:
        _rewrite_nested(statement)
        if isinstance(statement, IRReturn) and not _ends_with_flush(rewritten):
            rewritten.append(_flush_stmt())
        rewritten.append(statement)
    block.stmts = rewritten


def _rewrite_nested(statement) -> None:
    if isinstance(statement, IRBlock):
        _rewrite_block(statement)
    elif isinstance(statement, IRIf):
        _rewrite_block(statement.then_block)
        if statement.else_block is not None:
            _rewrite_block(statement.else_block)
    elif isinstance(statement, (IRWhile, IRDoWhile, IRFor)):
        _rewrite_block(statement.body)
    elif isinstance(statement, IRSwitch):
        for case in statement.cases:
            _rewrite_case(case)


def _rewrite_case(case: IRCase) -> None:
    block = IRBlock(stmts=case.body)
    _rewrite_block(block)
    case.body = block.stmts


def _flush_stmt() -> IRExprStmt:
    return IRExprStmt(
        expr=IRCall(
            callee="__btrc_flush_cycles",
            helper_ref="__btrc_flush_cycles",
            args=[],
        )
    )


def _ends_with_flush(statements) -> bool:
    if not statements:
        return False
    statement = statements[-1]
    return bool(
        isinstance(statement, IRExprStmt)
        and isinstance(statement.expr, IRCall)
        and (statement.expr.helper_ref == "__btrc_flush_cycles" or statement.expr.callee == "__btrc_flush_cycles")
    )


__all__ = [
    "PUBLIC_COLLECTION_BASES",
    "contains_cyclable_release",
    "install_function_cycle_boundary",
    "install_program_cycle_boundary",
]
