"""Structured-IR queries for collection topology mutation boundaries."""

from __future__ import annotations

import dataclasses

from .nodes import (
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRCall,
    IRCast,
    IRDeref,
    IRFieldAccess,
    IRIndex,
    IRUnaryOp,
    IRVar,
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


def contains_self_storage_mutation(value) -> bool:
    """Whether IR mutates storage reached directly or by alias from ``self``."""
    aliases: set[str] = set()
    while _collect_aliases(value, aliases):
        pass
    return _contains_mutation(value, aliases)


def _collect_aliases(value, aliases: set[str]) -> bool:
    changed = False
    if isinstance(value, IRVarDecl) and value.init is not None:
        changed |= _add_alias(value.name, value.init, aliases)
    elif isinstance(value, IRAssign) and isinstance(value.target, IRVar):
        changed |= _add_alias(value.target.name, value.value, aliases)
    elif isinstance(value, IRBinOp) and value.op == "=" and isinstance(value.left, IRVar):
        changed |= _add_alias(value.left.name, value.right, aliases)
    for child in _children(value):
        changed |= _collect_aliases(child, aliases)
    return changed


def _add_alias(name: str, source, aliases: set[str]) -> bool:
    if name in aliases or not _is_rooted_in_self(source, aliases):
        return False
    aliases.add(name)
    return True


def _contains_mutation(value, aliases: set[str]) -> bool:
    if isinstance(value, IRAssign) and _is_self_storage(value.target, aliases):
        return True
    if isinstance(value, IRBinOp) and value.op in _ASSIGNMENT_OPERATORS and _is_self_storage(value.left, aliases):
        return True
    if isinstance(value, IRUnaryOp) and value.op in {"++", "--"} and _is_self_storage(value.operand, aliases):
        return True
    if isinstance(value, IRCall) and isinstance(value.callee, str):
        slot = _MUTATING_CALL_SLOT.get(value.callee)
        if slot is not None and slot < len(value.args):
            if _is_rooted_in_self(value.args[slot], aliases):
                return True
    return any(_contains_mutation(child, aliases) for child in _children(value))


def _is_self_storage(value, aliases: set[str]) -> bool:
    if isinstance(value, (IRFieldAccess, IRIndex)):
        return _is_rooted_in_self(value.obj, aliases)
    if isinstance(value, IRDeref):
        return _is_rooted_in_self(value.expr, aliases)
    if isinstance(value, IRUnaryOp) and value.op == "*":
        return _is_rooted_in_self(value.operand, aliases)
    return False


def _is_rooted_in_self(value, aliases: set[str]) -> bool:
    if isinstance(value, IRVar):
        return value.name == "self" or value.name in aliases
    if isinstance(value, (IRFieldAccess, IRIndex)):
        return _is_rooted_in_self(value.obj, aliases)
    if isinstance(value, (IRAddressOf, IRCast, IRDeref)):
        return _is_rooted_in_self(value.expr, aliases)
    if isinstance(value, IRUnaryOp):
        return _is_rooted_in_self(value.operand, aliases)
    if isinstance(value, IRBinOp) and value.op in {"+", "-"}:
        return _is_rooted_in_self(value.left, aliases) or _is_rooted_in_self(value.right, aliases)
    return False


def _children(value):
    if isinstance(value, dict):
        return tuple(value.values())
    if isinstance(value, (list, tuple)):
        return value
    if not dataclasses.is_dataclass(value):
        return ()
    return tuple(
        item for field in dataclasses.fields(value) if not isinstance((item := getattr(value, field.name)), str)
    )


__all__ = ["contains_self_storage_mutation"]
