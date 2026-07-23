"""Collection-topology mutation analysis over structured IR."""

from __future__ import annotations

import dataclasses

from .expr_nodes import (
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRCast,
    IRDeref,
    IRFieldAccess,
    IRIndex,
    IRUnaryOp,
    IRVar,
)
from .nodes import (
    IRAssign,
    IRVarDecl,
)

_ASSIGNMENT_OPERATORS = frozenset({"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="})
_MUTATING_CALL_SLOT = {
    "__btrc_arc_replace_edge": 0,
    "__btrc_safe_realloc": 0,
    "free": 0,
    "memcpy": 0,
    "memmove": 0,
    "memset": 0,
    "qsort": 0,
    "realloc": 0,
}


class CollectionTopologyMutation:
    """Determine whether one IR tree mutates storage rooted in ``self``."""

    def __init__(self, root: object):
        self._root = root
        self._aliases: set[str] = set()

    def exists(self) -> bool:
        while self._collect_aliases(self._root):
            pass
        return self._contains_mutation(self._root)

    def _collect_aliases(self, value: object) -> bool:
        changed = False
        if isinstance(value, IRVarDecl) and value.init is not None:
            changed |= self._add_alias(value.name, value.init)
        elif isinstance(value, IRAssign) and isinstance(value.target, IRVar):
            changed |= self._add_alias(value.target.name, value.value)
        elif isinstance(value, IRBinOp) and value.op == "=" and isinstance(value.left, IRVar):
            changed |= self._add_alias(value.left.name, value.right)
        for child in self._children(value):
            changed |= self._collect_aliases(child)
        return changed

    def _add_alias(self, name: str, source: object) -> bool:
        if name in self._aliases or not self._is_rooted_in_self(source):
            return False
        self._aliases.add(name)
        return True

    def _contains_mutation(self, value: object) -> bool:
        if isinstance(value, IRAssign) and self._is_self_storage(value.target):
            return True
        if isinstance(value, IRBinOp) and value.op in _ASSIGNMENT_OPERATORS and self._is_self_storage(value.left):
            return True
        if isinstance(value, IRUnaryOp) and value.op in {"++", "--"} and self._is_self_storage(value.operand):
            return True
        if isinstance(value, IRCall) and isinstance(value.callee, str):
            slot = _MUTATING_CALL_SLOT.get(value.callee)
            if slot is not None and slot < len(value.args) and self._is_rooted_in_self(value.args[slot]):
                return True
        return any(self._contains_mutation(child) for child in self._children(value))

    def _is_self_storage(self, value: object) -> bool:
        if isinstance(value, (IRFieldAccess, IRIndex)):
            return self._is_rooted_in_self(value.obj)
        if isinstance(value, IRDeref):
            return self._is_rooted_in_self(value.expr)
        if isinstance(value, IRUnaryOp) and value.op == "*":
            return self._is_rooted_in_self(value.operand)
        return False

    def _is_rooted_in_self(self, value: object) -> bool:
        if isinstance(value, IRVar):
            return value.name == "self" or value.name in self._aliases
        if isinstance(value, (IRFieldAccess, IRIndex)):
            return self._is_rooted_in_self(value.obj)
        if isinstance(value, (IRAddressOf, IRCast, IRDeref)):
            return self._is_rooted_in_self(value.expr)
        if isinstance(value, IRUnaryOp):
            return self._is_rooted_in_self(value.operand)
        if isinstance(value, IRBinOp) and value.op in {"+", "-"}:
            return self._is_rooted_in_self(value.left) or self._is_rooted_in_self(value.right)
        return False

    @staticmethod
    def _children(value: object) -> tuple:
        if isinstance(value, dict):
            return tuple(value.values())
        if isinstance(value, (list, tuple)):
            return value
        if not dataclasses.is_dataclass(value):
            return ()
        return tuple(
            item
            for field in dataclasses.fields(value)
            if not isinstance(
                (item := getattr(value, field.name)),
                str,
            )
        )


__all__ = ["CollectionTopologyMutation"]
