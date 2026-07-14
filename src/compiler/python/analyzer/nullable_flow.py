"""Path-sensitive facts for safe access to nullable references."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from ..ast_nodes import (
    AssignExpr,
    BinaryExpr,
    CallExpr,
    FieldAccessExpr,
    Identifier,
    LambdaExpr,
    NullLiteral,
    SelfExpr,
    UnaryExpr,
)
from .core import SymbolInfo


@dataclass(frozen=True, eq=False)
class AccessPath:
    """A stable local binding followed by zero or more named fields."""

    root: SymbolInfo
    fields: tuple[str, ...] = ()

    def __hash__(self) -> int:
        return hash((id(self.root), self.fields))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, AccessPath) and self.root is other.root and self.fields == other.fields

    def contains(self, other: AccessPath) -> bool:
        """Whether assigning this path can change *other*."""

        return self.root is other.root and other.fields[: len(self.fields)] == self.fields


class NullableFlowMixin:
    """Conservative flow refinement for identity and member access paths."""

    def _access_path(self, expression) -> AccessPath | None:
        if isinstance(expression, Identifier):
            symbol = self.scope.lookup(expression.name)
            return AccessPath(symbol) if symbol is not None else None
        if isinstance(expression, SelfExpr):
            symbol = self.scope.lookup("self")
            return AccessPath(symbol) if symbol is not None else None
        if isinstance(expression, FieldAccessExpr):
            parent = self._access_path(expression.obj)
            if parent is not None:
                return AccessPath(parent.root, (*parent.fields, expression.field))
        return None

    def _is_known_nonnull(self, expression) -> bool:
        path = self._access_path(expression)
        return path is not None and path in self._nonnull_paths

    def _nonnull_facts_for_outcome(
        self,
        expression,
        truth: bool,
    ) -> set[AccessPath]:
        if isinstance(expression, UnaryExpr) and expression.op == "!":
            return self._nonnull_facts_for_outcome(
                expression.operand,
                not truth,
            )
        if not isinstance(expression, BinaryExpr):
            return set()
        if expression.op in ("==", "!="):
            path = self._null_comparison_path(expression)
            proves_nonnull = (expression.op == "!=" and truth) or (expression.op == "==" and not truth)
            return {path} if path is not None and proves_nonnull else set()

        if expression.op == "&&":
            left = self._nonnull_facts_for_outcome(expression.left, truth)
            right = self._nonnull_facts_for_outcome(expression.right, truth)
            if truth:
                return self._facts_surviving(left, expression.right) | right
            return left & right
        if expression.op == "||":
            left = self._nonnull_facts_for_outcome(expression.left, truth)
            right = self._nonnull_facts_for_outcome(expression.right, truth)
            if not truth:
                return self._facts_surviving(left, expression.right) | right
            return left & right
        return set()

    def _null_comparison_path(self, expression: BinaryExpr) -> AccessPath | None:
        if self._is_null_literal(expression.left):
            return self._access_path(expression.right)
        if self._is_null_literal(expression.right):
            return self._access_path(expression.left)
        return None

    @staticmethod
    def _is_null_literal(expression) -> bool:
        return isinstance(expression, NullLiteral) or (isinstance(expression, Identifier) and expression.name == "NULL")

    def _analyze_flow_branch(self, facts, analyze) -> set[AccessPath]:
        previous = self._nonnull_paths
        self._nonnull_paths = set(previous) | set(facts)
        try:
            analyze()
            return set(self._nonnull_paths)
        finally:
            self._nonnull_paths = previous

    @staticmethod
    def _join_nonnull_flows(
        flows: list[set[AccessPath]],
    ) -> set[AccessPath]:
        if not flows:
            return set()
        joined = set(flows[0])
        for flow in flows[1:]:
            joined.intersection_update(flow)
        return joined

    def _invalidate_nonnull_target(self, target) -> None:
        assigned = self._access_path(target)
        if assigned is None:
            # An indirect/indexed store can alias any tracked path.  Without
            # whole-program points-to information, retaining a fact here would
            # turn a diagnostic refinement into an unsoundness.
            self._nonnull_paths.clear()
            return
        if assigned.fields:
            # Object references are freely aliasable: ``alias.item = null``
            # can invalidate a fact learned through ``owner.item``.  Root-local
            # facts remain stable because a field store cannot rebind them.
            self._nonnull_paths = {fact for fact in self._nonnull_paths if not fact.fields}
            return
        self._nonnull_paths = {fact for fact in self._nonnull_paths if not assigned.contains(fact)}

    def _invalidate_nonnull_call(self, call: CallExpr) -> None:
        self._nonnull_paths = self._facts_surviving(
            self._nonnull_paths,
            call,
        )
        self._nonnull_paths = {
            fact for fact in self._nonnull_paths if id(fact.root) not in self._address_escaped_symbol_ids
        }

    def _record_nullable_address_escape(self, expression) -> None:
        path = self._access_path(expression)
        if path is not None and not path.fields:
            self._address_escaped_symbol_ids.add(id(path.root))

    def _facts_surviving(
        self,
        facts: set[AccessPath],
        expression,
    ) -> set[AccessPath]:
        surviving = set(facts)
        assignments: list[AccessPath] = []
        has_unknown_assignment = False
        address_escapes: list[AccessPath] = []
        has_call = False
        for node in self._walk_effect_nodes(expression):
            if isinstance(node, AssignExpr):
                path = self._access_path(node.target)
                if path is not None:
                    assignments.append(path)
                else:
                    has_unknown_assignment = True
            elif isinstance(node, CallExpr):
                has_call = True
                for argument in node.args:
                    if isinstance(argument, UnaryExpr) and argument.op == "&":
                        path = self._access_path(argument.operand)
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
                and not any(path.contains(fact) for path in address_escapes)
            }
        if has_call:
            surviving = {fact for fact in surviving if not fact.fields and not self._is_global_symbol(fact.root)}
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
        return any(candidate is symbol for candidate in self.global_scope.symbols.values())

    def _forget_nonnull_symbols(self, symbols) -> None:
        forgotten = tuple(symbols)
        self._address_escaped_symbol_ids.difference_update(id(symbol) for symbol in forgotten)
        self._nonnull_paths = {
            fact for fact in self._nonnull_paths if not any(fact.root is symbol for symbol in forgotten)
        }
