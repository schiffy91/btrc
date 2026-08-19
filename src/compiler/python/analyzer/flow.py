"""Control-flow, termination, and nullable-flow analysis."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from src.compiler.python.analyzer.program import AnalysisSession, SymbolInfo
from src.compiler.python.analyzer.types import TypeSystem
from src.compiler.python.syntax.ast.generated import (
    AssignExpr,
    BinaryExpr,
    Block,
    BoolLiteral,
    BreakStmt,
    CallExpr,
    CForStmt,
    ContinueStmt,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    FieldAccessExpr,
    ForInStmt,
    Identifier,
    IfStmt,
    LambdaExpr,
    NullLiteral,
    ParallelForStmt,
    ReturnStmt,
    SelfExpr,
    SwitchStmt,
    ThrowStmt,
    TryCatchStmt,
    UnaryExpr,
    WhileStmt,
)


@dataclass(frozen=True, eq=False)
class AccessPath:
    """A stable local binding followed by zero or more named fields."""

    root: SymbolInfo
    fields: tuple[str, ...] = ()

    def __hash__(self) -> int:
        return hash((id(self.root), self.fields))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, AccessPath) and self.root is other.root and (self.fields == other.fields)

    def contains(self, other: AccessPath) -> bool:
        """Whether assigning this path can change *other*."""
        return self.root is other.root and other.fields[: len(self.fields)] == self.fields


class ControlFlowAnalyzer:
    """Control-flow, termination, and nullable-flow analysis."""

    def __init__(self, session: AnalysisSession, types: TypeSystem) -> None:
        self.session = session
        self.types = types

    def is_range_call(self, expr) -> bool:
        return isinstance(expr, CallExpr) and isinstance(expr.callee, Identifier) and (expr.callee.name == "range")

    def block_stops_fallthrough(self, block) -> bool:
        if block is None:
            return False
        return any(self.statement_stops_fallthrough(statement) for statement in block.statements)

    def statement_stops_fallthrough(self, statement) -> bool:
        if isinstance(statement, (ReturnStmt, ThrowStmt, BreakStmt, ContinueStmt)):
            return True
        if isinstance(statement, Block):
            return self.block_stops_fallthrough(statement)
        if not isinstance(statement, IfStmt):
            return False
        if not self.block_stops_fallthrough(statement.then_block):
            return False
        if isinstance(statement.else_block, ElseBlock):
            return self.block_stops_fallthrough(statement.else_block.body)
        if isinstance(statement.else_block, ElseIf):
            return self.statement_stops_fallthrough(statement.else_block.if_stmt)
        return False

    def access_path(self, expression) -> AccessPath | None:
        if isinstance(expression, Identifier):
            symbol = self.session.scope.lookup(expression.name)
            return AccessPath(symbol) if symbol is not None else None
        if isinstance(expression, SelfExpr):
            symbol = self.session.scope.lookup("self")
            return AccessPath(symbol) if symbol is not None else None
        if isinstance(expression, FieldAccessExpr):
            parent = self.access_path(expression.obj)
            if parent is not None:
                return AccessPath(parent.root, (*parent.fields, expression.field))
        return None

    def _is_known_nonnull(self, expression) -> bool:
        path = self.access_path(expression)
        return path is not None and path in self.session.nonnull_paths

    def nonnull_facts_for_outcome(self, expression, truth: bool) -> set[AccessPath]:
        if isinstance(expression, UnaryExpr) and expression.op == "!":
            return self.nonnull_facts_for_outcome(expression.operand, not truth)
        if not isinstance(expression, BinaryExpr):
            return set()
        if expression.op in ("==", "!="):
            path = self._null_comparison_path(expression)
            proves_nonnull = (expression.op == "!=" and truth) or (expression.op == "==" and (not truth))
            return {path} if path is not None and proves_nonnull else set()
        if expression.op == "&&":
            left = self.nonnull_facts_for_outcome(expression.left, truth)
            right = self.nonnull_facts_for_outcome(expression.right, truth)
            if truth:
                return self._facts_surviving(left, expression.right) | right
            return left & right
        if expression.op == "||":
            left = self.nonnull_facts_for_outcome(expression.left, truth)
            right = self.nonnull_facts_for_outcome(expression.right, truth)
            if not truth:
                return self._facts_surviving(left, expression.right) | right
            return left & right
        return set()

    def _null_comparison_path(self, expression: BinaryExpr) -> AccessPath | None:
        if self._is_null_literal(expression.left):
            return self.access_path(expression.right)
        if self._is_null_literal(expression.right):
            return self.access_path(expression.left)
        return None

    @staticmethod
    def _is_null_literal(expression) -> bool:
        return isinstance(expression, NullLiteral) or (isinstance(expression, Identifier) and expression.name == "NULL")

    @staticmethod
    def join_nonnull_flows(flows: list[set[AccessPath]]) -> set[AccessPath]:
        if not flows:
            return set()
        joined = set(flows[0])
        for flow in flows[1:]:
            joined.intersection_update(flow)
        return joined

    def invalidate_nonnull_target(self, target) -> None:
        assigned = self.access_path(target)
        if assigned is None:
            self.session.replace_nonnull_paths(())
            return
        if assigned.fields:
            self.session.replace_nonnull_paths(fact for fact in self.session.nonnull_paths if not fact.fields)
            return
        self.session.replace_nonnull_paths(fact for fact in self.session.nonnull_paths if not assigned.contains(fact))

    def invalidate_nonnull_call(self, call: CallExpr) -> None:
        surviving = self._facts_surviving(set(self.session.nonnull_paths), call)
        self.session.replace_nonnull_paths(fact for fact in surviving if not self.session.address_escaped(fact.root))

    def record_nullable_address_escape(self, expression) -> None:
        path = self.access_path(expression)
        if path is not None and (not path.fields):
            self.session.mark_address_escaped(path.root)

    def _facts_surviving(self, facts: set[AccessPath], expression) -> set[AccessPath]:
        surviving = set(facts)
        assignments: list[AccessPath] = []
        has_unknown_assignment = False
        address_escapes: list[AccessPath] = []
        has_call = False
        for node in self._walk_effect_nodes(expression):
            if isinstance(node, AssignExpr):
                path = self.access_path(node.target)
                if path is not None:
                    assignments.append(path)
                else:
                    has_unknown_assignment = True
            elif isinstance(node, CallExpr):
                has_call = True
                for argument in node.args:
                    if isinstance(argument, UnaryExpr) and argument.op == "&":
                        path = self.access_path(argument.operand)
                        if path is not None:
                            address_escapes.append(path)
        if has_unknown_assignment:
            surviving.clear()
        else:
            if any(path.fields for path in assignments):
                surviving = {fact for fact in surviving if not fact.fields}
            surviving = {
                fact
                for fact in surviving
                if not any(path.contains(fact) for path in assignments)
                and (not any(path.contains(fact) for path in address_escapes))
            }
        if has_call:
            surviving = {fact for fact in surviving if not fact.fields and (not self._is_global_symbol(fact.root))}
        return surviving

    def _walk_effect_nodes(self, expression):
        stack = [expression]
        while stack:
            node = stack.pop()
            if node is None or isinstance(node, LambdaExpr):
                continue
            if not dataclasses.is_dataclass(node):
                continue
            yield node
            for field in dataclasses.fields(node):
                child = getattr(node, field.name)
                if isinstance(child, (list, tuple)):
                    stack.extend(child)
                elif dataclasses.is_dataclass(child):
                    stack.append(child)

    def _is_global_symbol(self, symbol: SymbolInfo) -> bool:
        return any(candidate is symbol for candidate in self.session.global_scope.symbols.values())

    def _forget_nonnull_symbols(self, symbols) -> None:
        forgotten = tuple(symbols)
        self.session.forget_address_escaped(forgotten)
        self.session.replace_nonnull_paths(
            fact for fact in self.session.nonnull_paths if not any(fact.root is symbol for symbol in forgotten)
        )

    @staticmethod
    def block_must_terminate(block) -> bool:
        """Whether every path through a block returns or throws."""
        return block is not None and any(
            ControlFlowAnalyzer.statement_must_terminate(statement) for statement in block.statements
        )

    @staticmethod
    def statement_must_terminate(statement) -> bool:
        if isinstance(statement, (ReturnStmt, ThrowStmt)):
            return True
        if isinstance(statement, Block):
            return ControlFlowAnalyzer.block_must_terminate(statement)
        if isinstance(statement, IfStmt):
            if not ControlFlowAnalyzer.block_must_terminate(statement.then_block):
                return False
            if isinstance(statement.else_block, ElseBlock):
                return ControlFlowAnalyzer.block_must_terminate(statement.else_block.body)
            if isinstance(statement.else_block, ElseIf):
                return ControlFlowAnalyzer.statement_must_terminate(statement.else_block.if_stmt)
            return False
        if isinstance(statement, SwitchStmt):
            return (
                bool(statement.cases)
                and any(case.value is None for case in statement.cases)
                and all(ControlFlowAnalyzer.statement_sequence_must_terminate(case.body) for case in statement.cases)
            )
        if isinstance(statement, TryCatchStmt):
            if ControlFlowAnalyzer.block_must_terminate(statement.finally_block):
                return True
            try_terminates = ControlFlowAnalyzer.block_must_terminate(statement.try_block)
            return (
                try_terminates
                if statement.catch_block is None
                else try_terminates and ControlFlowAnalyzer.block_must_terminate(statement.catch_block)
            )
        if isinstance(statement, WhileStmt):
            return (
                isinstance(statement.condition, BoolLiteral)
                and statement.condition.value
                and (not ControlFlowAnalyzer.contains_loop_break(statement.body))
                and ControlFlowAnalyzer.block_must_terminate(statement.body)
            )
        if isinstance(statement, DoWhileStmt):
            return not ControlFlowAnalyzer.contains_loop_break(
                statement.body
            ) and ControlFlowAnalyzer.block_must_terminate(statement.body)
        if isinstance(statement, CForStmt):
            return (
                statement.condition is None
                and (not ControlFlowAnalyzer.contains_loop_break(statement.body))
                and ControlFlowAnalyzer.block_must_terminate(statement.body)
            )
        return False

    @staticmethod
    def statement_sequence_must_terminate(statements) -> bool:
        return any(ControlFlowAnalyzer.statement_must_terminate(statement) for statement in statements)

    @staticmethod
    def contains_loop_break(node) -> bool:
        """Find a break targeting this loop, ignoring nested loop/switch scopes."""
        if node is None:
            return False
        if isinstance(node, BreakStmt):
            return True
        if isinstance(node, (WhileStmt, DoWhileStmt, CForStmt, ForInStmt, ParallelForStmt, SwitchStmt)):
            return False
        if isinstance(node, Block):
            return any(ControlFlowAnalyzer.contains_loop_break(statement) for statement in node.statements)
        if isinstance(node, IfStmt):
            if ControlFlowAnalyzer.contains_loop_break(node.then_block):
                return True
            if isinstance(node.else_block, ElseBlock):
                return ControlFlowAnalyzer.contains_loop_break(node.else_block.body)
            if isinstance(node.else_block, ElseIf):
                return ControlFlowAnalyzer.contains_loop_break(node.else_block.if_stmt)
        if isinstance(node, TryCatchStmt):
            return any(
                ControlFlowAnalyzer.contains_loop_break(child)
                for child in (node.try_block, node.catch_block, node.finally_block)
            )
        return False


__all__ = ["AccessPath", "ControlFlowAnalyzer"]
