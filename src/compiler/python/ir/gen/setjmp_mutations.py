"""Storage-identity write queries for C11 setjmp qualification."""

from __future__ import annotations

import dataclasses

from ..nodes import (
    IRBlock,
    IRDoWhile,
    IRFor,
    IRIf,
    IRSizeof,
    IRStmtExpr,
    IRSwitch,
    IRVarDecl,
    IRWhile,
)


def contains_setjmp(value: object) -> bool:
    from ..nodes import IRCall

    if isinstance(value, IRCall):
        return value.callee == "setjmp"
    if dataclasses.is_dataclass(value):
        return any(contains_setjmp(getattr(value, field.name)) for field in dataclasses.fields(value))
    if isinstance(value, (list, tuple)):
        return any(contains_setjmp(item) for item in value)
    return False


class _MutationCollector:
    def __init__(self, effects):
        self.flow = effects.flow
        self.storages = set()

    def block(self, block: IRBlock | None, bound=None) -> None:
        if block is None:
            return
        local = set(bound or ())
        for statement in block.stmts:
            self._statement(statement, local)

    def _record(self, value, bound) -> None:
        for origin in self.flow.writes.get(id(value), ()):
            if origin.depth == 0 and origin.storage.identity not in bound:
                self.storages.add(origin.storage)

    def _expression(self, value, bound) -> None:
        if value is None:
            return
        self._record(value, bound)
        if isinstance(value, IRSizeof):
            return
        if isinstance(value, IRStmtExpr):
            local = set(bound)
            for statement in value.stmts:
                self._statement(statement, local)
            self._expression(value.result, local)
            return
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                child = getattr(value, field.name)
                items = child if isinstance(child, (list, tuple)) else (child,)
                for item in items:
                    self._expression(item, bound)

    def _declaration(self, declaration, bound) -> None:
        self._expression(declaration.array_size, bound)
        storage = self.flow.storages.get(id(declaration))
        if storage is not None:
            bound.add(storage.identity)
        self._expression(declaration.init, bound)

    def _statement(self, statement, bound) -> None:
        self._record(statement, bound)
        if isinstance(statement, IRVarDecl):
            self._declaration(statement, bound)
        elif isinstance(statement, IRIf):
            self._expression(statement.condition, bound)
            self.block(statement.then_block, bound)
            self.block(statement.else_block, bound)
        elif isinstance(statement, (IRWhile, IRDoWhile)):
            self._expression(statement.condition, bound)
            self.block(statement.body, bound)
        elif isinstance(statement, IRFor):
            local = set(bound)
            if isinstance(statement.init, IRVarDecl):
                self._declaration(statement.init, local)
            else:
                self._expression(statement.init, local)
            self._expression(statement.condition, local)
            self._expression(statement.update, local)
            self.block(statement.body, local)
        elif isinstance(statement, IRSwitch):
            self._expression(statement.value, bound)
            for case in statement.cases:
                local = set(bound)
                self._expression(case.value, local)
                for child in case.body:
                    self._statement(child, local)
        elif isinstance(statement, IRBlock):
            self.block(statement, bound)
        else:
            self._expression(statement, bound)


def mutated_names(block: IRBlock | None, *, effects, summarize: bool = False):
    """Return exact storage identities modified outside ``block`` declarations."""

    del summarize
    collector = _MutationCollector(effects)
    collector.block(block)
    return collector.storages


def loop_mutated_names(statement: IRFor | IRWhile | IRDoWhile, *, effects):
    statements = []
    if statement.condition is not None:
        from ..nodes import IRExprStmt

        statements.append(IRExprStmt(expr=statement.condition))
    update = getattr(statement, "update", None)
    if update is not None:
        from ..nodes import IRExprStmt

        statements.append(IRExprStmt(expr=update))
    if statement.body is not None:
        statements.append(statement.body)
    return mutated_names(IRBlock(stmts=statements), effects=effects)


def switch_fallthrough_mutated_names(statement: IRSwitch, index: int, *, effects):
    modified = set()
    while index + 1 < len(statement.cases) and statement.cases[index].falls_through:
        index += 1
        modified.update(mutated_names(IRBlock(stmts=statement.cases[index].body), effects=effects))
    return modified
