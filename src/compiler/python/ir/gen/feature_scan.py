"""Feature-presence scans used to select runtime dependencies."""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from ...ast_nodes import ThrowStmt, TryCatchStmt


def uses_trycatch(decl) -> bool:
    """Return whether an AST declaration contains exception syntax.

    Exception capability is a module-wide ownership contract: a try frame in a
    lambda may catch a throw from an allocating constructor several calls away.
    Walk every generated AST field instead of maintaining a second, incomplete
    list of statement shapes.  The identity set keeps the conservative walk
    safe if an analyzer ever introduces shared or cyclic annotations.
    """

    return _value_uses_trycatch(decl, set())


def program_uses_trycatch(program) -> bool:
    """Return whether any declaration establishes an exception contract.

    This deliberately runs before dead-code elimination.  A reachable bundled
    stdlib try frame can catch a throw that crosses user or stdlib callees, so
    source provenance is not a safe substitute for a whole-program call graph.
    """

    return any(uses_trycatch(declaration) for declaration in getattr(program, "declarations", ()))


def _value_uses_trycatch(value, seen: set[int]) -> bool:
    if value is None:
        return False
    if isinstance(value, (ThrowStmt, TryCatchStmt)):
        return True
    if not (is_dataclass(value) or isinstance(value, (dict, list, tuple, set, frozenset))):
        return False

    identity = id(value)
    if identity in seen:
        return False
    seen.add(identity)
    if isinstance(value, dict):
        return any(_value_uses_trycatch(item, seen) for pair in value.items() for item in pair)
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_value_uses_trycatch(item, seen) for item in value)
    return any(_value_uses_trycatch(getattr(value, field.name), seen) for field in fields(value))


def _block_uses_trycatch(block) -> bool:
    """Compatibility entry point for callers scanning one block."""

    return _value_uses_trycatch(block, set())


def _stmt_uses_trycatch(statement) -> bool:
    """Compatibility entry point for callers scanning one statement."""

    return _value_uses_trycatch(statement, set())


__all__ = [
    "_block_uses_trycatch",
    "_stmt_uses_trycatch",
    "program_uses_trycatch",
    "uses_trycatch",
]
