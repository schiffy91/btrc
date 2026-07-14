"""Direct-write analysis for C11 setjmp qualification."""

from __future__ import annotations

import dataclasses

from ..nodes import (
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRDoWhile,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRIf,
    IRIndex,
    IRReturn,
    IRStmtExpr,
    IRSwitch,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
)

_ASSIGNMENT_OPS = frozenset(
    (
        "=",
        "+=",
        "-=",
        "*=",
        "/=",
        "%=",
        "&=",
        "|=",
        "^=",
        "<<=",
        ">>=",
    )
)


def contains_setjmp(value: object) -> bool:
    if isinstance(value, IRCall):
        return value.callee == "setjmp"
    if dataclasses.is_dataclass(value):
        return any(contains_setjmp(getattr(value, field.name)) for field in dataclasses.fields(value))
    if isinstance(value, (list, tuple)):
        return any(contains_setjmp(item) for item in value)
    return False


def _storage_root(value: object) -> str | None:
    """Return the directly modified automatic object, excluding pointees."""

    if isinstance(value, IRVar):
        return value.name
    if isinstance(value, IRFieldAccess) and not value.arrow:
        return _storage_root(value.obj)
    if isinstance(value, IRIndex):
        return _storage_root(value.obj)
    return None


class _MutationCollector:
    """Collect writes to names declared before a setjmp invocation."""

    def __init__(self):
        self.names: set[str] = set()

    def block(self, block: IRBlock | None, bound=None) -> None:
        if block is None:
            return
        local = set(bound or ())
        for statement in block.stmts:
            self._statement(statement, local)

    def _write(self, target, bound) -> None:
        name = _storage_root(target)
        if name is not None and name not in bound:
            self.names.add(name)

    def _expression(self, value: object, bound) -> None:
        if isinstance(value, IRBinOp) and value.op in _ASSIGNMENT_OPS:
            self._write(value.left, bound)
        elif isinstance(value, IRUnaryOp) and value.op in ("++", "--"):
            self._write(value.operand, bound)
        if isinstance(value, IRStmtExpr):
            for statement in value.stmts:
                self._statement(statement, bound)
            self._expression(value.result, bound)
            return
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                self._expression(getattr(value, field.name), bound)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._expression(item, bound)

    def _statement(self, statement, bound) -> None:
        if isinstance(statement, IRVarDecl):
            # C block scope starts after the declarator.  A VLA bound can
            # therefore still name (and mutate) an outer declaration with the
            # same spelling, while the initializer resolves to the new object.
            self._expression(statement.array_size, bound)
            bound.add(statement.name)
            self._expression(statement.init, bound)
        elif isinstance(statement, IRAssign):
            self._write(statement.target, bound)
            self._expression(statement.target, bound)
            self._expression(statement.value, bound)
        elif isinstance(statement, (IRReturn, IRExprStmt)):
            value = statement.value if isinstance(statement, IRReturn) else statement.expr
            self._expression(value, bound)
        elif isinstance(statement, IRIf):
            self._expression(statement.condition, bound)
            self.block(statement.then_block, bound)
            self.block(statement.else_block, bound)
        elif isinstance(statement, (IRWhile, IRDoWhile)):
            self._expression(statement.condition, bound)
            self.block(statement.body, bound)
        elif isinstance(statement, IRFor):
            loop_bound = set(bound)
            if statement.init is not None:
                self._statement(statement.init, loop_bound)
            self._expression(statement.condition, loop_bound)
            self._expression(statement.update, loop_bound)
            self.block(statement.body, loop_bound)
        elif isinstance(statement, IRSwitch):
            self._expression(statement.value, bound)
            for case in statement.cases:
                case_bound = set(bound)
                self._expression(case.value, case_bound)
                for child in case.body:
                    self._statement(child, case_bound)
        elif isinstance(statement, IRBlock):
            self.block(statement, bound)


def mutated_names(block: IRBlock | None) -> set[str]:
    """Return direct writes to storage declared outside ``block``."""

    collector = _MutationCollector()
    collector.block(block)
    return collector.names
