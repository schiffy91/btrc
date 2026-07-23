"""Explicit mutable state shared by IR-lowering collaborators."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field

from ...analyzer.core import AnalyzedProgram
from ...ast_nodes import TypeExpr
from ..nodes import IRModule, IRVarDecl
from .helpers import RuntimeHelperRegistry

_MISSING = object()


@dataclass(slots=True)
class TemporaryNames:
    """Monotonic C temporary-name state shared by nested lowerers."""

    counter: int = 0

    def fresh(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter}"


@dataclass(slots=True)
class LoweringContext:
    """Mutable state owned by one IR-lowering run.

    The context deliberately contains data, not lowering behavior. Domain
    collaborators receive the narrow operations they need separately.
    """

    analyzed: AnalyzedProgram
    module: IRModule
    helpers: RuntimeHelperRegistry
    function_declarations: list[IRVarDecl] = field(default_factory=list)
    owning_overrides: dict[int, object] = field(default_factory=dict)
    type_overrides: dict[int, object] = field(default_factory=dict)
    local_ownership_scopes: list[dict[str, str | None]] = field(default_factory=list)
    callable_types: dict[str, TypeExpr] = field(default_factory=dict)
    callable_return_abis: dict[str, str] = field(default_factory=dict)
    callable_environments: dict[str, tuple[str, str]] = field(default_factory=dict)
    hosted_result_conversion_requests: dict[int, tuple[str, object]] = field(default_factory=dict)
    current_property_backing: str | None = None
    gpu_cpu_index: str | None = None
    unevaluated_depth: int = 0
    temporaries: TemporaryNames = field(default_factory=TemporaryNames)

    def type_of(self, node: object) -> TypeExpr | None:
        override = self.type_overrides.get(id(node), _MISSING)
        if override is not _MISSING:
            return override
        return self.analyzed.node_types.get(id(node))

    def fresh_temp(self, prefix: str = "__tmp") -> str:
        return self.temporaries.fresh(prefix)

    def record_declaration(self, declaration: IRVarDecl) -> None:
        self.function_declarations.append(declaration)

    @property
    def is_unevaluated(self) -> bool:
        return self.unevaluated_depth > 0

    def callable_type(self, name: str) -> TypeExpr | None:
        return self.callable_types.get(name)

    def callable_environment(self, name: str) -> tuple[str, str] | None:
        return self.callable_environments.get(name)

    def local_is_declared(self, name: str) -> bool:
        """Whether a lexical binding shadows a same-named module symbol."""
        return any(name in scope for scope in reversed(self.local_ownership_scopes))

    def managed_local_type(self, name: str) -> str | None:
        """Return the nearest lexical binding's managed runtime type."""
        for scope in reversed(self.local_ownership_scopes):
            if name in scope:
                return scope[name]
        return None

    @contextmanager
    def operand_scope(
        self,
        values: Mapping[int, object],
        types: Mapping[int, object] | None = None,
    ) -> Iterator[None]:
        """Install call-scoped operand substitutions and restore them safely."""
        previous_values = {key: self.owning_overrides.get(key, _MISSING) for key in values}
        previous_types = {key: self.type_overrides.get(key, _MISSING) for key in (types or {})}
        self.owning_overrides.update(values)
        self.type_overrides.update(types or {})
        try:
            yield
        finally:
            self._restore(self.owning_overrides, previous_values)
            self._restore(self.type_overrides, previous_types)

    @staticmethod
    def _restore(target: dict, previous: Mapping[int, object]) -> None:
        for key, value in previous.items():
            if value is _MISSING:
                target.pop(key, None)
            else:
                target[key] = value


__all__ = ["LoweringContext", "TemporaryNames"]
