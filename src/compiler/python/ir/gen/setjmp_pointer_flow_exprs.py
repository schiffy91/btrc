"""Expression transfer functions for setjmp pointer provenance."""

from __future__ import annotations

import dataclasses

from ..nodes import (
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRCompoundLiteral,
    IRDeref,
    IRFieldAccess,
    IRIndex,
    IRInitializerList,
    IRSizeof,
    IRStmtExpr,
    IRTernary,
    IRUnaryOp,
    IRVar,
)
from ..storage_provenance import direct_storage_root
from .setjmp_effect_model import PointerOrigin

_ASSIGNMENT_OPS = frozenset({"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="})


class PointerExpressionFlowMixin:
    def _expression(self, value, state):
        if value is None:
            return set(), state
        if isinstance(value, IRVar):
            storage = self._resolve(value.name)
            if value.array_storage_known and value.array_storage_root:
                storage = self._resolve(value.array_storage_root)
                origins = {PointerOrigin(storage, source_exposed=True)} if storage else set()
            elif storage is not None and storage.is_array:
                origins = {PointerOrigin(storage, source_exposed=True)}
            else:
                origins = set(state.get(storage, ())) if storage is not None and storage.is_pointer else set()
            return self.result.record_origins(value, origins), state
        if isinstance(value, IRAddressOf):
            _, current = self._expression(value.expr, state)
            origins = {
                PointerOrigin(
                    origin.storage,
                    origin.depth,
                    origin.source_exposed or value.source_expression,
                )
                for origin in self._locations(value.expr, current)
            }
            return self.result.record_origins(value, origins), current
        if isinstance(value, IRDeref):
            child, current = self._expression(value.expr, state)
            return self.result.record_origins(value, self._load(child, current)), current
        if isinstance(value, IRCast):
            origins, current = self._expression(value.expr, state)
            target_depth = self.type_facts.pointer_depth(value.target_type)
            if target_depth == 0:
                if origins and not self._is_void_cast(value.target_type):
                    # Pointer/integer casts are the finite fail-closed boundary
                    # for arbitrary scalar laundering (bitwise ops, hosted
                    # calls, and inverse transforms cannot recover precision).
                    self.result.captures.update(origins)
                origins = set()
            else:
                origins = {
                    origin.saturated() if self._cast_widens(origin, target_depth) else origin for origin in origins
                }
            return self.result.record_origins(value, origins), current
        if isinstance(value, IRCommaExpr):
            origins: set[PointerOrigin] = set()
            current = state
            for expression in value.expressions:
                origins, current = self._expression(expression, current)
            return self.result.record_origins(value, origins), current
        if isinstance(value, IRStmtExpr):
            current = state
            for statement in value.stmts:
                current = self._statement(statement, current)
            origins, current = self._expression(value.result, current)
            return self.result.record_origins(value, origins), current
        if isinstance(value, IRTernary):
            _, current = self._expression(value.condition, state)
            left, left_state = self._expression(value.true_expr, self._copy(current))
            right, right_state = self._expression(value.false_expr, self._copy(current))
            return self.result.record_origins(value, left | right), self._join(left_state, right_state)
        if isinstance(value, IRCall):
            return self._call(value, state)
        if isinstance(value, IRBinOp):
            if value.op in _ASSIGNMENT_OPS:
                current = self._assignment(value, value.left, value.right, state, op=value.op)
                origins = self.result.origins.get(id(value.right), set()) if value.op == "=" else set()
                return self.result.record_origins(value, origins), current
            if value.op in {"&&", "||", "??"}:
                left, current = self._expression(value.left, state)
                right, right_state = self._expression(value.right, self._copy(current))
                origins = left | right if value.op == "??" else set()
                return self.result.record_origins(value, origins), self._join(current, right_state)
            left, current = self._expression(value.left, state)
            right, current = self._expression(value.right, current)
            origins = left | right if value.op in {"+", "-"} else set()
            return self.result.record_origins(value, origins), current
        if isinstance(value, IRUnaryOp):
            origins, current = self._expression(value.operand, state)
            if value.op in {"++", "--"}:
                self.result.record_write(value, self._locations(value.operand, current))
            if value.op == "!":
                origins = set()
            return self.result.record_origins(value, origins), current
        if isinstance(value, IRSizeof):
            return self.result.record_origins(value, ()), state
        if isinstance(value, IRFieldAccess):
            _, current = self._expression(value.obj, state)
            if value.array_storage_known and value.array_storage_root:
                storage = self._resolve(value.array_storage_root)
                origins = {PointerOrigin(storage, source_exposed=True)} if storage else set()
            else:
                origins = set()
            return self.result.record_origins(value, origins), current
        if isinstance(value, IRIndex):
            _, current = self._expression(value.obj, state)
            _, current = self._expression(value.index, current)
            return self.result.record_origins(value, ()), current
        if isinstance(value, (IRInitializerList, IRCompoundLiteral)):
            origins: set[PointerOrigin] = set()
            current = state
            children = value.elements if isinstance(value, IRInitializerList) else [item for _, item in value.fields]
            for child in children:
                child_origins, current = self._expression(child, current)
                origins.update(child_origins)
            return self.result.record_origins(value, origins), current
        current = state
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                child = getattr(value, field.name)
                items = child if isinstance(child, (list, tuple)) else (child,)
                for item in items:
                    _, current = self._expression(item, current)
        return self.result.record_origins(value, ()), current

    def _assignment(self, node, target, value, state, *, op="="):
        _, current = self._expression(target, state)
        origins, current = self._expression(value, current)
        locations = self._locations(target, current)
        self.result.record_write(node, locations)
        if op != "=":
            return current
        local_pointers = {
            origin.storage
            for origin in locations
            if (origin.depth == 0 and origin.storage.is_pointer and not origin.storage.is_array)
        }
        exact_local = len(locations) == 1 and len(local_pointers) == 1
        if exact_local:
            destination = next(iter(local_pointers))
            current[destination] = set(origins)
            if not destination.automatic:
                self.result.captures.update(origins)
        elif local_pointers and len(local_pointers) == len(locations):
            for storage in local_pointers:
                current.setdefault(storage, set()).update(origins)
        elif origins:
            self.result.captures.update(origins)
        return current

    def _call(self, call: IRCall, state):
        current = state
        if not isinstance(call.callee, str):
            _, current = self._expression(call.callee, current)
        for argument in call.args:
            _, current = self._expression(argument, current)
        effect = self.effect_lookup(call.callee, len(call.args))
        writes = set()
        for item in effect.writes:
            if item.index < len(call.args):
                writes.update(self._argument_targets(call.args[item.index], item.depth, current))
        self.result.record_write(call, writes)
        for origin in writes:
            storage = origin.storage
            if origin.depth == 0 and storage.is_pointer and not storage.is_array:
                current[storage] = set()
                if origin.source_exposed and not storage.compiler_owned:
                    self.result.unknown_pointer_values.add(storage)
        for item in effect.captures:
            if item.index < len(call.args):
                self.result.captures.update(self._argument_targets(call.args[item.index], item.depth, current))
        origins = set()
        for item in effect.returns:
            if item.index < len(call.args):
                origins.update(self._argument_targets(call.args[item.index], item.depth, current))
        if effect.unknown_return:
            for argument in call.args:
                origins.update(self.result.origins.get(id(argument), ()))
        return self.result.record_origins(call, origins), current

    def _argument_targets(self, argument, depth, state):
        origins = set(self.result.origins.get(id(argument), ()))
        if depth < 0:
            saturated = set()
            frontier = origins
            while frontier:
                expandable = set()
                for origin in frontier:
                    concrete = origin.saturated() if origin.depth > 0 else origin
                    if concrete not in saturated:
                        saturated.add(concrete)
                        expandable.add(origin)
                frontier = self._load(expandable, state)
            return saturated
        for _ in range(max(0, depth - 1)):
            origins = self._load(origins, state)
        return origins

    def _locations(self, value, state):
        if isinstance(value, IRVar):
            storage = self._resolve(value.name)
            return {PointerOrigin(storage)} if storage else set()
        if isinstance(value, IRFieldAccess) and value.arrow:
            return set(self.result.origins.get(id(value.obj), ()))
        if isinstance(value, (IRIndex, IRDeref)):
            if value.storage_root_known and value.storage_root:
                storage = self._resolve(value.storage_root)
                return {PointerOrigin(storage)} if storage else set()
            if value.storage_root_known or isinstance(value, IRDeref):
                child = value.obj if isinstance(value, IRIndex) else value.expr
                return set(self.result.origins.get(id(child), ()))
        root = direct_storage_root(value)
        storage = self._resolve(root) if root else None
        return {PointerOrigin(storage)} if storage else set()

    @staticmethod
    def _copy(state):
        return {storage: set(origins) for storage, origins in state.items()}

    @staticmethod
    def _join(*states):
        result = {}
        for state in states:
            for storage, origins in state.items():
                result.setdefault(storage, set()).update(origins)
        return result

    @staticmethod
    def _load(origins, state):
        loaded = set()
        for origin in origins:
            if origin.depth < 0:
                loaded.add(origin)
            elif origin.depth > 0 and origin.storage.pointer_depth < 0:
                loaded.add(origin.saturated())
            elif 0 < origin.depth < origin.storage.pointer_depth:
                loaded.add(origin.deeper())
            elif origin.depth == 0 and origin.storage.is_pointer:
                loaded.update(state.get(origin.storage, ()))
        return loaded

    @staticmethod
    def _cast_widens(origin, target_depth):
        """Whether a cast invents pointee levels beyond an abstract origin."""

        if origin.depth <= 0:
            return False
        declared_depth = origin.storage.pointer_depth
        if target_depth < 0 or declared_depth < 0:
            return True
        remaining_depth = max(0, declared_depth - origin.depth + 1)
        return target_depth > remaining_depth

    def _is_void_cast(self, target_type):
        return self.type_facts.is_void(target_type)


__all__ = ["PointerExpressionFlowMixin"]
