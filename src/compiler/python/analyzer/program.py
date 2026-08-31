"""Semantic-analysis state, scopes, diagnostics, and result models."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, fields, is_dataclass
from types import MappingProxyType
from typing import Literal

from src.compiler.python.syntax.ast.generated import (
    FieldDecl,
    FunctionDecl,
    ImportDecl,
    MethodDecl,
    MethodSig,
    Program,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypeExpr,
)
from src.compiler.python.syntax.tokens import SourceSymbolDirective


class AnalysisContext:
    """Own diagnostics and the source location active during analysis."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.diagnostics: list[Diag] = []
        self.current_source_file: str | None = None

    def declarations(self, program: Program) -> Iterator[object]:
        """Yield semantic declarations while tracking their source file."""
        for declaration in program.declarations:
            if isinstance(declaration, ImportDecl):
                continue
            with self.source(getattr(declaration, "source_file", None)):
                yield declaration

    @contextmanager
    def source(self, source_file: str | None) -> Iterator[None]:
        """Activate source provenance and restore any enclosing provenance."""
        previous = self.current_source_file
        self.current_source_file = source_file
        try:
            yield
        finally:
            self.current_source_file = previous

    def error(self, message: str, line: int = 0, col: int = 0) -> None:
        self.errors.append(f"{message} at {line}:{col}")
        self.diagnostics.append(Diag(message, line, col, "error", self.current_source_file))

    def warning(self, message: str, line: int = 0, col: int = 0) -> None:
        self.warnings.append(f"{message} at {line}:{col}")
        self.diagnostics.append(Diag(message, line, col, "warning", self.current_source_file))


class AnalyzerError(Exception):
    def __init__(self, message: str, line: int = 0, col: int = 0):
        self.line = line
        self.col = col
        super().__init__(f"{message} at {line}:{col}")


@dataclass
class Diag:
    """One semantic diagnostic with optional source-file provenance."""

    message: str
    line: int
    col: int
    severity: str = "error"
    file: str | None = None


@dataclass
class ClassInfo:
    name: str
    generic_params: list[str] = field(default_factory=list)
    fields: dict[str, FieldDecl] = field(default_factory=dict)
    static_fields: dict[str, FieldDecl] = field(default_factory=dict)
    methods: dict[str, MethodDecl] = field(default_factory=dict)
    properties: dict[str, PropertyDecl] = field(default_factory=dict)
    field_owners: dict[str, str] = field(default_factory=dict)
    method_owners: dict[str, str] = field(default_factory=dict)
    property_owners: dict[str, str] = field(default_factory=dict)
    instance_storage: list[tuple[str, FieldDecl | PropertyDecl]] = field(default_factory=list)
    constructor: MethodDecl = None
    parent: str = None
    interfaces: list[str] = field(default_factory=list)
    is_abstract: bool = False
    is_cyclable: bool = False


ClassCallableKind = Literal["method", "get", "set"]


@dataclass(frozen=True, slots=True)
class ClassCallableIdentity:
    """Stable semantic identity for one class method or property accessor."""

    owner: str
    kind: ClassCallableKind
    name: str

    def __post_init__(self) -> None:
        if not self.owner or not self.name:
            raise ValueError("class callable identities require an owner and name")
        if self.kind not in {"method", "get", "set"}:
            raise ValueError(f"unknown class callable kind: {self.kind}")

    @classmethod
    def method(cls, owner: str, name: str) -> ClassCallableIdentity:
        return cls(owner, "method", name)

    @classmethod
    def getter(cls, owner: str, name: str) -> ClassCallableIdentity:
        return cls(owner, "get", name)

    @classmethod
    def setter(cls, owner: str, name: str) -> ClassCallableIdentity:
        return cls(owner, "set", name)


@dataclass(frozen=True, slots=True)
class GenericClassCallableDependency:
    """One deferred generic receiver call made by a template callable body."""

    receiver: TypeExpr
    callable: ClassCallableIdentity


@dataclass(frozen=True, slots=True)
class GenericMethodInstanceDependency:
    """One deferred generic-method instance demanded by a template body."""

    owner: str
    method_name: str
    class_arguments: tuple[TypeExpr, ...]
    method_arguments: tuple[TypeExpr, ...]
    line: int = 0
    col: int = 0

    def __post_init__(self) -> None:
        if not self.owner or not self.method_name:
            raise ValueError("generic-method dependencies require an owner and method name")


GenericTemplateDependency = GenericClassCallableDependency | GenericMethodInstanceDependency


@dataclass
class SymbolInfo:
    name: str
    type: TypeExpr
    kind: str = "variable"
    decl_line: int = 0
    decl_col: int = 0
    decl_file: str | None = None
    captures_environment: bool = False
    owned_storage: bool = False


@dataclass
class Occurrence:
    """An identifier use resolved to its recorded definition site."""

    kind: str
    name: str
    def_file: str | None = None
    def_line: int = 0
    def_col: int = 0


@dataclass
class Scope:
    symbols: dict[str, SymbolInfo] = field(default_factory=dict)
    parent: Scope = None

    def lookup(self, name: str) -> SymbolInfo | None:
        if name in self.symbols:
            return self.symbols[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def define(self, name: str, info: SymbolInfo):
        self.symbols[name] = info


@dataclass
class InterfaceInfo:
    name: str
    methods: dict[str, MethodSig] = field(default_factory=dict)
    parent: str = None
    generic_params: list[str] = field(default_factory=list)


class SourceMacroNamespace:
    """Immutable declared-name and final-active-definition namespace."""

    def __init__(
        self,
        declared_names: Iterable[str] = (),
        definitions: Mapping[str, SourceSymbolDirective] | None = None,
    ) -> None:
        self._declared_names = frozenset(declared_names)
        self._definitions = MappingProxyType(dict(definitions or {}))

    @classmethod
    def empty(cls) -> SourceMacroNamespace:
        return cls()

    @property
    def declared_names(self) -> frozenset[str]:
        return self._declared_names

    @property
    def definitions(self) -> Mapping[str, SourceSymbolDirective]:
        return self._definitions

    def declared(self, name: str) -> bool:
        return name in self._declared_names

    def active(self, name: str) -> SourceSymbolDirective | None:
        return self._definitions.get(name)

    def expands_to_any(self, name: str, identifiers: frozenset[str]) -> bool:
        """Whether an active macro transitively references a target identifier."""
        pending = [name]
        visiting: set[str] = set()
        while pending:
            current = pending.pop()
            if current in visiting:
                continue
            visiting.add(current)
            directive = self.active(current)
            if directive is None:
                continue
            for identifier in directive.replacement_identifiers():
                if identifier in identifiers:
                    return True
                if identifier not in visiting and self.active(identifier) is not None:
                    pending.append(identifier)
        return False


@dataclass
class DeclarationIndex:
    """Mutable declaration facts shared by semantic owners for one run."""

    class_table: dict[str, ClassInfo] = field(default_factory=dict)
    function_table: dict[str, FunctionDecl] = field(default_factory=dict)
    typedef_table: dict[str, TypeExpr] = field(default_factory=dict)
    struct_table: dict[str, StructDecl] = field(default_factory=dict)
    enum_table: dict[str, list[str]] = field(default_factory=dict)
    interface_table: dict[str, InterfaceInfo] = field(default_factory=dict)
    rich_enum_table: dict[str, RichEnumDecl] = field(default_factory=dict)
    declared_type_names: set[str] = field(default_factory=set)
    top_level_kinds: dict[str, str] = field(default_factory=dict)
    source_macros: SourceMacroNamespace = field(default_factory=SourceMacroNamespace.empty)
    enum_member_owners: dict[str, set[str]] = field(default_factory=dict)
    enum_constant_values: dict[tuple[str, str], int | None] = field(default_factory=dict)
    global_declarations: dict[str, object] = field(default_factory=dict)
    global_definitions: dict[str, object] = field(default_factory=dict)
    struct_definitions: dict[str, object] = field(default_factory=dict)
    definition_index: dict[str, tuple[object, str]] = field(default_factory=dict)


@dataclass
class AnalyzedProgram:
    program: Program
    generic_instances: dict[str, list[tuple[TypeExpr, ...]]]
    class_table: dict[str, ClassInfo]
    generic_class_callable_instances: dict[ClassCallableIdentity, list[tuple[TypeExpr, ...]]] = field(
        default_factory=dict
    )
    generic_class_callable_dependencies: dict[ClassCallableIdentity, list[GenericTemplateDependency]] = field(
        default_factory=dict
    )
    generic_class_lifecycle_dependencies: dict[str, list[GenericTemplateDependency]] = field(default_factory=dict)
    generic_method_callable_dependencies: dict[tuple[str, str], list[GenericTemplateDependency]] = field(
        default_factory=dict
    )
    generic_method_instances: dict[tuple[str, str], list[tuple[tuple, tuple]]] = field(default_factory=dict)
    generic_method_call_args: dict[int, tuple] = field(default_factory=dict)
    function_table: dict[str, FunctionDecl] = field(default_factory=dict)
    global_var_types: dict[str, TypeExpr] = field(default_factory=dict)
    defined_global_names: frozenset[str] = frozenset()
    hosted_call_ids: set[int] = field(default_factory=set)
    realtime_safe_callables: frozenset[str] = frozenset()
    realtime_bounded_loop_ids: set[int] = field(default_factory=set)
    typedef_table: dict[str, TypeExpr] = field(default_factory=dict)
    struct_table: dict[str, StructDecl] = field(default_factory=dict)
    node_types: dict[int, TypeExpr] = field(default_factory=dict)
    enum_table: dict[str, list[str]] = field(default_factory=dict)
    interface_table: dict[str, InterfaceInfo] = field(default_factory=dict)
    rich_enum_table: dict[str, RichEnumDecl] = field(default_factory=dict)
    rich_enum_unsafe_default_ids: set[int] = field(default_factory=set)
    array_iteration_capacity_ids: set[int] = field(default_factory=set)
    constant_array_bound_ids: set[int] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diags: list[Diag] = field(default_factory=list)
    occurrences: dict[int, Occurrence] = field(default_factory=dict)


@dataclass(frozen=True)
class LambdaBodyFacts:
    """Immutable result of StatementAnalyzer's nested-lambda body prewalk."""

    terminates: bool


class AnalysisSession(AnalysisContext):
    """Mutable facts, diagnostics, and provenance for one analysis run.

    The session is deliberately data-only: semantic owners mutate/query these
    facts directly instead of discovering an ``AnalysisContext`` collaborator
    through the session.
    """

    def __init__(self) -> None:
        super().__init__()
        self.generic_instances: dict[str, list[tuple[TypeExpr, ...]]] = {}
        self.generic_class_callable_instances: dict[ClassCallableIdentity, list[tuple[TypeExpr, ...]]] = {}
        self.generic_class_callable_dependencies: dict[ClassCallableIdentity, list[GenericTemplateDependency]] = {}
        self.generic_class_lifecycle_dependencies: dict[str, list[GenericTemplateDependency]] = {}
        self.generic_method_callable_dependencies: dict[tuple[str, str], list[GenericTemplateDependency]] = {}
        self.generic_method_instances: dict[tuple[str, str], list[tuple[tuple, tuple]]] = {}
        self.generic_method_call_args: dict[int, tuple] = {}
        self.generic_resolved_type_facts: list[tuple[TypeExpr, int, int]] = []
        self._hosted_call_ids: set[int] = set()
        self.scope: Scope = Scope()
        self.global_scope: Scope = self.scope
        self.current_class: ClassInfo | None = None
        self.current_method: MethodDecl | None = None
        self.current_class_callable: ClassCallableIdentity | None = None
        self.current_callable = None
        self._analyzing_parameter_default = False
        self._analyzing_constructor_default = False
        self._previous_statement = None
        self._standalone_expression_root = None
        self.in_virtual_setter: bool = False
        self.current_return_type: TypeExpr | None = None
        self.in_gpu_function: bool = False
        self.node_types: dict[int, TypeExpr] = {}
        self.loop_depth: int = 0
        self.break_depth: int = 0
        self._assignment_target_depth: int = 0
        self._analyzed_array_bounds: set[int] = set()
        self.constant_array_bound_ids: set[int] = set()
        self.array_iteration_capacity_ids: set[int] = set()
        self.realtime_bounded_loop_ids: set[int] = set()
        self._nonnull_paths: set = set()
        self._address_escaped_symbol_ids: set[int] = set()
        self.rich_enum_unsafe_default_ids: set[int] = set()
        self.record_occurrences: bool = False
        self.occurrences: dict[int, Occurrence] = {}
        self._lambda_contexts: list[tuple[dict[str, SymbolInfo], dict[str, TypeExpr]]] = []
        self.lambda_body_facts: dict[int, LambdaBodyFacts] = {}
        self.expression_flow_seeds: dict[int, frozenset] = {}
        self.known_nonnull_expression_ids: set[int] = set()
        self.source_visible_runtime_names: frozenset[str] = frozenset()
        self.reported_type_shape_errors: set[tuple[str, int, int]] = set()
        self._gpu_result_boundary: object | None = None

    def begin(self, program: Program) -> None:
        """Reset all mutable facts whose lifetime is one analysis run."""
        self.errors = []
        self.warnings = []
        self.diagnostics = []
        self.current_source_file = None
        self._hosted_call_ids = set()
        self._unresolved_direct_callee_ids = set()
        self._unresolved_c_symbol_reference_ids = set()
        self.array_iteration_capacity_ids = set()
        self.realtime_bounded_loop_ids = set()
        self._analyzed_array_bounds = set()
        self.constant_array_bound_ids = set()
        self.rich_enum_unsafe_default_ids = set()
        self.generic_resolved_type_facts = []
        self.lambda_body_facts = {}
        self.expression_flow_seeds = {}
        self.known_nonnull_expression_ids = set()
        self.reported_type_shape_errors = set()
        self._gpu_result_boundary = None

    @property
    def gpu_result_boundary(self) -> object | None:
        """The GPU result call authorized by the current outward value boundary."""
        return self._gpu_result_boundary

    @contextmanager
    def gpu_result_context(self, boundary: object | None) -> Iterator[None]:
        """Install one GPU materialization boundary for recursive expression analysis."""
        previous = self._gpu_result_boundary
        self._gpu_result_boundary = boundary
        try:
            yield
        finally:
            self._gpu_result_boundary = previous

    @contextmanager
    def scope_frame(self) -> Iterator[Scope]:
        """Install and reliably restore one lexical child scope."""
        previous = self.scope
        self.scope = Scope(parent=previous)
        try:
            yield self.scope
        finally:
            self.scope = previous

    def local_symbol(
        self, name: str, type_: TypeExpr, kind: str, line: int = 0, col: int = 0, *, owned_storage: bool = False
    ) -> SymbolInfo:
        """SymbolInfo for a locally-defined symbol, stamped with its def site.

        The def site is the (line, col) of the name in the current source file,
        so a later occurrence lookup can point exactly at the declaration.
        """
        return SymbolInfo(
            name,
            type_,
            kind,
            decl_line=line,
            decl_col=col,
            decl_file=self.current_source_file,
            owned_storage=owned_storage,
        )

    @property
    def analyzing_parameter_default(self) -> bool:
        return self._analyzing_parameter_default

    @property
    def analyzing_constructor_default(self) -> bool:
        return self._analyzing_constructor_default

    @contextmanager
    def default_analysis(self, *, constructor: bool = False) -> Iterator[None]:
        previous_parameter = self._analyzing_parameter_default
        previous_constructor = self._analyzing_constructor_default
        self._analyzing_parameter_default = True
        self._analyzing_constructor_default = constructor
        try:
            yield
        finally:
            self._analyzing_parameter_default = previous_parameter
            self._analyzing_constructor_default = previous_constructor

    @property
    def nonnull_paths(self) -> frozenset:
        return frozenset(self._nonnull_paths)

    def replace_nonnull_paths(self, facts) -> None:
        self._nonnull_paths = set(facts)

    @contextmanager
    def nonnull_frame(self, facts=None) -> Iterator[None]:
        previous = self._nonnull_paths
        self._nonnull_paths = set(previous if facts is None else facts)
        try:
            yield
        finally:
            self._nonnull_paths = previous

    @contextmanager
    def assignment_target(self) -> Iterator[None]:
        self._assignment_target_depth += 1
        try:
            yield
        finally:
            self._assignment_target_depth -= 1

    @property
    def analyzing_assignment_target(self) -> bool:
        return self._assignment_target_depth > 0

    @contextmanager
    def lambda_capture_frame(self, outer_symbols, captures) -> Iterator[None]:
        self._lambda_contexts.append((outer_symbols, captures))
        try:
            yield
        finally:
            self._lambda_contexts.pop()

    @property
    def lambda_capture_contexts(self) -> tuple:
        return tuple(self._lambda_contexts)

    @contextmanager
    def standalone_expression(self, expression) -> Iterator[None]:
        previous = self._standalone_expression_root
        self._standalone_expression_root = expression
        try:
            yield
        finally:
            self._standalone_expression_root = previous

    @property
    def standalone_expression_root(self):
        return self._standalone_expression_root

    @contextmanager
    def statement_sequence(self) -> Iterator[None]:
        previous = self._previous_statement
        self._previous_statement = None
        try:
            yield
        finally:
            self._previous_statement = previous

    def advance_statement(self, statement) -> None:
        self._previous_statement = statement

    @property
    def previous_statement(self):
        return self._previous_statement

    def mark_array_bound(self, bound) -> bool:
        marker = id(bound)
        if marker in self._analyzed_array_bounds:
            return False
        self._analyzed_array_bounds.add(marker)
        return True

    def record_hosted_call(self, call) -> None:
        self._hosted_call_ids.add(id(call))

    @property
    def hosted_call_ids(self) -> frozenset[int]:
        return frozenset(self._hosted_call_ids)

    def record_unresolved_symbol(self, expression, *, direct_callee: bool = False) -> None:
        self._unresolved_c_symbol_reference_ids.add(id(expression))
        if direct_callee:
            self._unresolved_direct_callee_ids.add(id(expression))

    @property
    def unresolved_c_symbol_reference_ids(self) -> frozenset[int]:
        return frozenset(self._unresolved_c_symbol_reference_ids)

    @property
    def unresolved_direct_callee_ids(self) -> frozenset[int]:
        return frozenset(self._unresolved_direct_callee_ids)

    def mark_address_escaped(self, symbol) -> None:
        self._address_escaped_symbol_ids.add(id(symbol))

    def address_escaped(self, symbol) -> bool:
        return id(symbol) in self._address_escaped_symbol_ids

    def forget_address_escaped(self, symbols) -> None:
        self._address_escaped_symbol_ids.difference_update(id(symbol) for symbol in symbols)

    def record_node_type(self, node, type_: TypeExpr) -> TypeExpr:
        """Record and return a type fact produced by an analysis owner."""
        self.node_types[id(node)] = type_
        return type_

    @staticmethod
    def semantic_ast_key(value):
        """Return a recursive key containing only semantically comparable fields.

        Generated AST dataclasses mark source locations with ``compare=False``.
        Honouring that schema metadata explicitly keeps declaration contracts
        independent of where equivalent syntax appeared in the source.
        """
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, (list, tuple)):
            return tuple(AnalysisSession.semantic_ast_key(item) for item in value)
        if not is_dataclass(value):
            raise TypeError(f"unsupported semantic AST value: {type(value).__name__}")
        return (
            type(value).__name__,
            tuple(
                (field.name, AnalysisSession.semantic_ast_key(getattr(value, field.name)))
                for field in fields(value)
                if field.compare
            ),
        )


__all__ = [
    "AnalysisContext",
    "AnalysisSession",
    "AnalyzedProgram",
    "AnalyzerError",
    "ClassCallableIdentity",
    "ClassCallableKind",
    "ClassInfo",
    "DeclarationIndex",
    "Diag",
    "GenericClassCallableDependency",
    "GenericMethodInstanceDependency",
    "GenericTemplateDependency",
    "InterfaceInfo",
    "LambdaBodyFacts",
    "Occurrence",
    "Scope",
    "SourceMacroNamespace",
    "SymbolInfo",
]
