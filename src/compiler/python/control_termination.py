"""Pure source-AST all-path termination analysis."""

from .ast_nodes import (
    Block,
    BoolLiteral,
    BreakStmt,
    CForStmt,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    ForInStmt,
    IfStmt,
    ParallelForStmt,
    ReturnStmt,
    SwitchStmt,
    ThrowStmt,
    TryCatchStmt,
    WhileStmt,
)


def block_must_terminate(block) -> bool:
    """Whether every path through a block returns or throws."""
    return block is not None and any(statement_must_terminate(statement) for statement in block.statements)


def statement_must_terminate(statement) -> bool:
    if isinstance(statement, (ReturnStmt, ThrowStmt)):
        return True
    if isinstance(statement, Block):
        return block_must_terminate(statement)
    if isinstance(statement, IfStmt):
        if not block_must_terminate(statement.then_block):
            return False
        if isinstance(statement.else_block, ElseBlock):
            return block_must_terminate(statement.else_block.body)
        if isinstance(statement.else_block, ElseIf):
            return statement_must_terminate(statement.else_block.if_stmt)
        return False
    if isinstance(statement, SwitchStmt):
        return (
            bool(statement.cases)
            and any(case.value is None for case in statement.cases)
            and all(statement_sequence_must_terminate(case.body) for case in statement.cases)
        )
    if isinstance(statement, TryCatchStmt):
        if block_must_terminate(statement.finally_block):
            return True
        try_terminates = block_must_terminate(statement.try_block)
        return (
            try_terminates
            if statement.catch_block is None
            else try_terminates and block_must_terminate(statement.catch_block)
        )
    if isinstance(statement, WhileStmt):
        return (
            isinstance(statement.condition, BoolLiteral)
            and statement.condition.value
            and not contains_loop_break(statement.body)
            and block_must_terminate(statement.body)
        )
    if isinstance(statement, DoWhileStmt):
        return not contains_loop_break(statement.body) and block_must_terminate(statement.body)
    if isinstance(statement, CForStmt):
        return (
            statement.condition is None
            and not contains_loop_break(statement.body)
            and block_must_terminate(statement.body)
        )
    return False


def statement_sequence_must_terminate(statements) -> bool:
    return any(statement_must_terminate(statement) for statement in statements)


def contains_loop_break(node) -> bool:
    """Find a break targeting this loop, ignoring nested loop/switch scopes."""
    if node is None:
        return False
    if isinstance(node, BreakStmt):
        return True
    if isinstance(node, (WhileStmt, DoWhileStmt, CForStmt, ForInStmt, ParallelForStmt, SwitchStmt)):
        return False
    if isinstance(node, Block):
        return any(contains_loop_break(statement) for statement in node.statements)
    if isinstance(node, IfStmt):
        if contains_loop_break(node.then_block):
            return True
        if isinstance(node.else_block, ElseBlock):
            return contains_loop_break(node.else_block.body)
        if isinstance(node.else_block, ElseIf):
            return contains_loop_break(node.else_block.if_stmt)
    if isinstance(node, TryCatchStmt):
        return any(contains_loop_break(child) for child in (node.try_block, node.catch_block, node.finally_block))
    return False


__all__ = [
    "block_must_terminate",
    "contains_loop_break",
    "statement_must_terminate",
    "statement_sequence_must_terminate",
]
