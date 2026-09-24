"""Mutable data for one IR-lowering invocation."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.compiler.python.runtime.catalog import RuntimeHelperSelection
from src.compiler.python.syntax.ast.generated import ClassDecl, MethodDecl, TypeExpr

from ..nodes import IRFunctionDecl, IRModule, IRVarDecl

if TYPE_CHECKING:
    from src.compiler.python.frontend.sources import SourceMap

    from .generics import SpecializationView, SpecializedDeclarationView
    from .reachability import StdlibReachabilityPlan


_MISSING = object()


@dataclass(slots=True)
class TemporaryNames:
    """Monotonic C temporary-name state."""

    counter: int = 0

    def fresh(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter}"


@dataclass(slots=True)
class ProgramLoweringFacts:
    """Program-wide results that every module-unit session of one program shares.

    Each is a pure function of the analyzed program, computed by the first
    session that needs it and then only read, so per-group sessions do not
    repeat whole-program walks.
    """

    uses_trycatch: bool | None = None
    stdlib_reachability: StdlibReachabilityPlan | None = None
    stdlib_reachability_computed: bool = False
    tuple_types: dict[str, list[TypeExpr]] | None = None
    # Every generic class and method specialization the program demands, in
    # plan order; a session filters them to what its group owns.
    class_views: tuple[SpecializedDeclarationView[ClassDecl], ...] | None = None
    method_views: tuple[SpecializedDeclarationView[MethodDecl], ...] | None = None


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
    # Stdlib callables this program reaches (see lowering.reachability); None lowers everything.
    stdlib_reachability: StdlibReachabilityPlan | None = None
    persistent_edge_owner_c_name: str | None = None
    c_array_scopes: list[dict[str, bool]] = field(default_factory=list)
    control_context: list[object] = field(default_factory=list)
    # Module-unit lowering: the one compilation group whose bodies this session
    # lowers. A declaration owned by another group keeps its declaration-level
    # IR but no body; `definition_owners` names the group behind every function
    # and global created while lowering a declaration. None lowers everything.
    owned_group: str | None = None
    foreign_body: bool = False
    # The unit's foreign declarations come from shared program declarations,
    # so this session skips them entirely instead of lowering them bodiless.
    declarations_elsewhere: bool = False
    definition_owners: dict[str, str] = field(default_factory=dict)
    # Name index over the append-only `module.function_decls` prefix it covers.
    _declaration_index: dict[str, list[IRFunctionDecl]] = field(default_factory=dict)
    _declaration_indexed: int = 0
    _declaration_list: list[IRFunctionDecl] | None = None

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

    def declare_function_once(self, declaration: IRFunctionDecl) -> None:
        """Append a prototype unless an equal one is already declared.

        Equivalent to a linear `in` test over `module.function_decls`, but
        compares only same-named prototypes. The index covers the list as an
        append-only sequence and is rebuilt if the list is replaced or shrinks.
        """
        declarations = self.module.function_decls
        if declarations is not self._declaration_list or len(declarations) < self._declaration_indexed:
            self._declaration_index = {}
            self._declaration_indexed = 0
            self._declaration_list = declarations
        for existing in declarations[self._declaration_indexed :]:
            self._declaration_index.setdefault(existing.name, []).append(existing)
        self._declaration_indexed = len(declarations)
        if declaration in self._declaration_index.get(declaration.name, ()):
            return
        declarations.append(declaration)
        self._declaration_index.setdefault(declaration.name, []).append(declaration)
        self._declaration_indexed = len(declarations)

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
