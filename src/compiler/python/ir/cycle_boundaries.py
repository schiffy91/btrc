"""Install deterministic drains at observable cycle-ownership boundaries."""

from __future__ import annotations

from .completion import StatementSequence
from .expr_nodes import IRCall, IRVar
from .nodes import (
    IRBlock,
    IRCase,
    IRDoWhile,
    IRExprStmt,
    IRFor,
    IRFunctionDef,
    IRIf,
    IRReturn,
    IRSwitch,
    IRVarDecl,
    IRWhile,
)
from .optimizer_walk import IRTree

PUBLIC_COLLECTION_BASES = frozenset({"Array", "List", "Map", "Set", "Vector"})
_PROGRAM_ENTRIES = frozenset({"btrc_main", "main"})
_CYCLABLE_RELEASE_HELPERS = frozenset(
    {
        "__btrc_arc_release",
        "__btrc_arc_release_edge",
        "__btrc_arc_replace_edge",
    }
)


class FunctionCycleBoundary:
    """Own cycle-drain installation for one function definition."""

    def __init__(self, function: IRFunctionDef):
        self._function = function
        self._has_cyclable_release = self._contains_cyclable_release(function.body)
        self._counter = 0
        self._local_names = {parameter.name for parameter in function.params}
        self._local_names.update(node.name for node in IRTree(function.body) if isinstance(node, IRVarDecl))

    @property
    def has_cyclable_release(self) -> bool:
        return self._has_cyclable_release

    @property
    def is_program_entry(self) -> bool:
        return self._function.name in _PROGRAM_ENTRIES

    def install(self, *, force: bool = False) -> bool:
        """Install a boundary when this function releases or ``force`` is set."""

        body = self._function.body
        if body is None or (not force and not self._has_cyclable_release):
            return False
        self._rewrite_block(body)
        if StatementSequence(body.stmts).may_fall_through() and not self._ends_with_flush(body.stmts):
            body.stmts.append(self._flush_statement())
        return True

    def _rewrite_block(self, block: IRBlock) -> None:
        rewritten = []
        for statement in block.stmts:
            self._rewrite_nested(statement)
            if isinstance(statement, IRReturn):
                materialized = self._is_materialized_flush_return(
                    rewritten,
                    statement,
                )
                if statement.value is not None and not materialized:
                    result = self._next_return_name()
                    rewritten.append(
                        IRVarDecl(
                            c_type=self._function.return_type,
                            name=result,
                            init=statement.value,
                            is_cycle_return_temp=True,
                        )
                    )
                    statement.value = IRVar(name=result)
                if not self._ends_with_flush(rewritten):
                    rewritten.append(self._flush_statement())
            rewritten.append(statement)
        block.stmts = rewritten

    def _rewrite_nested(self, statement) -> None:
        if isinstance(statement, IRBlock):
            self._rewrite_block(statement)
        elif isinstance(statement, IRIf):
            self._rewrite_block(statement.then_block)
            if statement.else_block is not None:
                self._rewrite_block(statement.else_block)
        elif isinstance(statement, (IRWhile, IRDoWhile, IRFor)):
            self._rewrite_block(statement.body)
        elif isinstance(statement, IRSwitch):
            for case in statement.cases:
                self._rewrite_case(case)

    def _rewrite_case(self, case: IRCase) -> None:
        block = IRBlock(stmts=case.body)
        self._rewrite_block(block)
        case.body = block.stmts

    def _next_return_name(self) -> str:
        while True:
            self._counter += 1
            name = f"__btrc_cycle_return_{self._counter}"
            if name not in self._local_names:
                self._local_names.add(name)
                return name

    @classmethod
    def _contains_cyclable_release(cls, value: object) -> bool:
        return any(
            isinstance(node, IRCall)
            and (
                node.helper_ref in _CYCLABLE_RELEASE_HELPERS
                or (isinstance(node.callee, str) and node.callee in _CYCLABLE_RELEASE_HELPERS)
            )
            for node in IRTree(value)
        )

    @classmethod
    def _is_materialized_flush_return(
        cls,
        statements,
        statement: IRReturn,
    ) -> bool:
        if len(statements) < 2 or not cls._ends_with_flush(statements):
            return False
        declaration = statements[-2]
        return bool(
            isinstance(declaration, IRVarDecl)
            and declaration.is_cycle_return_temp
            and isinstance(statement.value, IRVar)
            and declaration.name == statement.value.name
        )

    @staticmethod
    def _flush_statement() -> IRExprStmt:
        return IRExprStmt(
            expr=IRCall(
                callee="__btrc_flush_cycles",
                helper_ref="__btrc_flush_cycles",
                args=[],
            )
        )

    @staticmethod
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
    "FunctionCycleBoundary",
]
