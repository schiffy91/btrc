"""Mutable data for one IR-lowering invocation."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.compiler.python.runtime.catalog import RuntimeHelperSelection
from src.compiler.python.syntax.ast.generated import TypeExpr

from ..nodes import IRModule, IRVarDecl

if TYPE_CHECKING:
    from src.compiler.python.frontend.sources import SourceMap

    from .generics import SpecializationView


_MISSING = object()


@dataclass(slots=True)
class TemporaryNames:
    """Monotonic C temporary-name state."""

    counter: int = 0

    def fresh(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter}"


@dataclass(slots=True)
class LoweringSession:
    """State for one lowering run, deliberately free of collaborators."""

    module: IRModule
    node_types: Mapping[int, TypeExpr]
    debug: bool = False
    source_file: str = ""
    freestanding: bool = False
    source_map: SourceMap | None = None
    function_declarations: list[IRVarDecl] = field(default_factory=list)
    owning_overrides: dict[int, object] = field(default_factory=dict)
    ownership_overrides: dict[int, bool] = field(default_factory=dict)
    type_overrides: dict[int, object] = field(default_factory=dict)
    local_ownership_scopes: list[dict[str, str | None]] = field(default_factory=list)
    hosted_result_conversion_requests: dict[int, tuple[str, object]] = field(default_factory=dict)
    runtime_helpers: RuntimeHelperSelection = field(default_factory=RuntimeHelperSelection)
    runtime_headers: set[str] = field(default_factory=set)
    deferred_specializations: list[object] = field(default_factory=list)
    pending_lambdas: list[object] = field(default_factory=list)
    pending_thread_spawns: list[object] = field(default_factory=list)
    arc_descriptor_types: set[str] = field(default_factory=set)
    enum_lowering_owner: str = ""
    enum_lowering_members: frozenset[str] = field(default_factory=frozenset)
    current_property_backing: str | None = None
    current_class: object | None = None
    gpu_cpu_index: str | None = None
    current_class_name: str = ""
    current_return_c_type: str = "int"
    current_return_type: TypeExpr | None = field(default_factory=lambda: TypeExpr(base="int"))
    current_return_owned: bool = True
    unevaluated_depth: int = 0
    in_try_depth: int = 0
    in_trycatch_depth: int = 0
    temporaries: TemporaryNames = field(default_factory=TemporaryNames)
    lambda_counter: int = 0
    active_specialization: SpecializationView | None = None
    persistent_edge_owner_c_name: str | None = None
    c_array_scopes: list[dict[str, bool]] = field(default_factory=list)
    control_context: list[object] = field(default_factory=list)

    def source_type_of(self, node: object) -> TypeExpr | None:
        """Return the analyzed or operand-overridden type before specialization."""
        override = self.type_overrides.get(id(node), _MISSING)
        return override if override is not _MISSING else self.node_types.get(id(node))  # type: ignore[return-value]

    def type_of(self, node: object) -> TypeExpr | None:
        type_expr = self.source_type_of(node)
        specialization = self.active_specialization
        if specialization is not None:
            return specialization.substitution.resolve(type_expr)
        return type_expr

    def type_of_is_specialized(self, node: object) -> bool:
        specialization = self.active_specialization
        return bool(specialization is not None and specialization.substitution.applies_to(self.source_type_of(node)))

    def fresh_temp(self, prefix: str = "__tmp") -> str:
        return self.temporaries.fresh(prefix)

    def fresh_lambda_id(self) -> int:
        self.lambda_counter += 1
        return self.lambda_counter

    def record_declaration(self, declaration: IRVarDecl) -> None:
        self.function_declarations.append(declaration)

    def require_helper(self, name: str) -> None:
        self.runtime_helpers.use(name)

    def uses_any_helper(self, names: set[str]) -> bool:
        return self.runtime_helpers.uses_any(names)

    def require_runtime_header(self, header: str) -> None:
        self.runtime_headers.add(header)

    def consume_runtime_headers(self) -> tuple[str, ...]:
        """Return deterministic native-header requirements exactly once."""
        headers = tuple(sorted(self.runtime_headers))
        self.runtime_headers.clear()
        return headers

    @property
    def is_unevaluated(self) -> bool:
        return self.unevaluated_depth > 0

    def local_is_declared(self, name: str) -> bool:
        return any(name in scope for scope in reversed(self.local_ownership_scopes))

    def managed_local_type(self, name: str) -> str | None:
        for scope in reversed(self.local_ownership_scopes):
            if name in scope:
                return scope[name]
        return None

    @contextmanager
    def operand_scope(
        self,
        values: Mapping[int, object],
        types: Mapping[int, object] | None = None,
        ownership: Mapping[int, bool] | None = None,
    ) -> Iterator[None]:
        previous_values = {key: self.owning_overrides.get(key, _MISSING) for key in values}
        previous_types = {key: self.type_overrides.get(key, _MISSING) for key in (types or {})}
        previous_ownership = {key: self.ownership_overrides.get(key, _MISSING) for key in (ownership or {})}
        self.owning_overrides.update(values)
        self.type_overrides.update(types or {})
        self.ownership_overrides.update(ownership or {})
        try:
            yield
        finally:
            self._restore(self.owning_overrides, previous_values)
            self._restore(self.type_overrides, previous_types)
            self._restore(self.ownership_overrides, previous_ownership)

    @contextmanager
    def specialization(self, view: SpecializationView) -> Iterator[None]:
        previous = self.active_specialization
        self.active_specialization = view
        try:
            yield
        finally:
            self.active_specialization = previous

    @contextmanager
    def persistent_edge_scope(self, owner_c_name: str | None) -> Iterator[None]:
        """Bind explicit keep/release statements to one physical edge owner."""
        previous = self.persistent_edge_owner_c_name
        self.persistent_edge_owner_c_name = owner_c_name
        try:
            yield
        finally:
            self.persistent_edge_owner_c_name = previous

    @contextmanager
    def enum_values(
        self,
        owner: str,
        members: frozenset[str],
    ) -> Iterator[None]:
        """Expose only preceding members while lowering one enum initializer."""

        previous_owner = self.enum_lowering_owner
        previous_members = self.enum_lowering_members
        self.enum_lowering_owner = owner
        self.enum_lowering_members = members
        try:
            yield
        finally:
            self.enum_lowering_owner = previous_owner
            self.enum_lowering_members = previous_members

    @staticmethod
    def _restore(target: dict, previous: Mapping[int, object]) -> None:
        for key, value in previous.items():
            if value is _MISSING:
                target.pop(key, None)
            else:
                target[key] = value
