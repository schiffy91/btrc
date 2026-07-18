"""Analyzer core: data structures, scope management, and orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ast_nodes import (
    FieldDecl,
    FunctionDecl,
    MethodDecl,
    MethodSig,
    Program,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypeExpr,
)


class AnalyzerError(Exception):
    def __init__(self, message: str, line: int = 0, col: int = 0):
        self.line = line
        self.col = col
        super().__init__(f"{message} at {line}:{col}")


@dataclass
class Diag:
    """Structured diagnostic with file provenance.

    ``file`` is the source file of the top-level declaration under analysis
    when the diagnostic was reported (None when declarations carry no
    ``source_file`` provenance, e.g. plain CLI compiles of resolved source).
    """

    message: str
    line: int
    col: int
    severity: str = "error"  # "error" | "warning"
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
    # ARC: true if this class can participate in reference cycles
    # (has class-type fields that could transitively reference self)
    is_cyclable: bool = False


@dataclass
class SymbolInfo:
    name: str
    type: TypeExpr
    kind: str = "variable"  # "variable" | "function" | "param"
    # Definition site of the symbol (where it was declared). Populated at the
    # ``Scope.define`` call sites so a resolved symbol knows where it lives.
    # Defaults of 0/0/None mean "no recorded definition site" (e.g. seeded
    # stdlib symbols or synthetic symbols like ``self``/``value``).
    decl_line: int = 0
    decl_col: int = 0
    decl_file: str | None = None
    # A capturing lambda cannot be represented by a bare C function pointer.
    # Direct local calls have a dedicated lowering path; aliases, parameters,
    # and returns must reject the value until the language has a closure type.
    captures_environment: bool = False
    # Whether this lexical binding owns a managed value and can safely replace
    # it. Parameters and raw iteration projections are borrowed by default.
    owned_storage: bool = False


@dataclass
class Occurrence:
    """An identifier use resolved to its definition by the analyzer.

    Recorded only when ``AnalyzerBase.record_occurrences`` is True (the LSP
    path); the CLI compiler never pays. Positions are native to ``def_file``.
    """

    kind: str  # 'variable'|'param'|'function'|'class'|'method'|'field'|'enum'|...
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


@dataclass
class AnalyzedProgram:
    program: Program
    generic_instances: dict[str, list[tuple[TypeExpr, ...]]]
    class_table: dict[str, ClassInfo]
    # Generic-method monomorphization targets. Keyed by
    # (owning_class_base, method_name); each entry is a (class_args, method_args)
    # pair of TypeExpr tuples, where class_args are the concrete generic args of
    # the receiver instance (e.g. (int,) for Vector<int>) and method_args are the
    # concrete method-level type arguments (e.g. (string,) for mapTo<string>).
    generic_method_instances: dict[tuple[str, str], list[tuple[tuple, tuple]]] = field(default_factory=dict)
    # id(CallExpr) -> tuple of concrete method-level type args for that generic
    # call site (e.g. (string,) for v.mapTo<string>(...)). Used by IR-gen to
    # name-mangle the call to the monomorphized instance.
    generic_method_call_args: dict[int, tuple] = field(default_factory=dict)
    function_table: dict[str, FunctionDecl] = field(default_factory=dict)
    typedef_table: dict[str, TypeExpr] = field(default_factory=dict)
    struct_table: dict[str, StructDecl] = field(default_factory=dict)
    node_types: dict[int, TypeExpr] = field(default_factory=dict)
    enum_table: dict[str, list[str]] = field(default_factory=dict)
    interface_table: dict[str, InterfaceInfo] = field(default_factory=dict)
    rich_enum_table: dict[str, RichEnumDecl] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diags: list[Diag] = field(default_factory=list)
    # id(identifier-node) -> Occurrence. Empty unless analysis ran with
    # ``record_occurrences=True`` (LSP path). The CLI compiler never fills it.
    occurrences: dict[int, Occurrence] = field(default_factory=dict)


class AnalyzerBase:
    def __init__(self):
        self.class_table: dict[str, ClassInfo] = {}
        self.function_table: dict[str, FunctionDecl] = {}
        self.typedef_table: dict[str, TypeExpr] = {}
        self.struct_table: dict[str, StructDecl] = {}
        self.generic_instances: dict[str, list[tuple[TypeExpr, ...]]] = {}
        self.generic_method_instances: dict[tuple[str, str], list[tuple[tuple, tuple]]] = {}
        self.generic_method_call_args: dict[int, tuple] = {}
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.diags: list[Diag] = []
        self.current_source_file: str | None = None
        self.scope: Scope = Scope()
        self.global_scope: Scope = self.scope
        self.current_class: ClassInfo | None = None
        self.current_method: MethodDecl | None = None
        self.current_callable = None
        self._previous_statement = None
        # Only the root expression of an ExprStmt may consume a physical
        # Mutex slot through `.destroy()`.
        self._standalone_expression_root = None
        self.in_virtual_setter: bool = False
        self.current_return_type: TypeExpr | None = None
        self.in_gpu_function: bool = False
        self.node_types: dict[int, TypeExpr] = {}
        self.loop_depth: int = 0
        self.break_depth: int = 0
        self._assignment_target_depth: int = 0
        self._analyzed_array_bounds: set[int] = set()
        self._nonnull_paths: set = set()
        # Symbol identities whose storage address has escaped. A later call can
        # rebind those locals indirectly, so nullable refinements for them are
        # not stable across calls.
        self._address_escaped_symbol_ids: set[int] = set()
        self.enum_table: dict[str, list[str]] = {}
        self.interface_table: dict[str, InterfaceInfo] = {}
        self.rich_enum_table: dict[str, RichEnumDecl] = {}
        # Occurrence recording is OFF by default so the CLI compiler pays
        # nothing. The LSP flips it on before analyzing the user program.
        self.record_occurrences: bool = False
        self.occurrences: dict[int, Occurrence] = {}
        # Stack of (outer symbol map, captured type map) for nested lambdas.
        # Symbol identity, not spelling, distinguishes a true capture from a
        # lambda-local declaration that shadows an outer name.
        self._lambda_contexts: list[tuple[dict[str, SymbolInfo], dict[str, TypeExpr]]] = []

    def analyze(self, program: Program) -> AnalyzedProgram:
        # Source of definition sites for top-level names when recording
        # occurrences (the class/enum tables hold no decl reference). The
        # decl index is rebuilt lazily per analysis.
        self._recording_program = program
        self._decl_index_cache = None
        self._register_declarations(program)
        # Registered types are a shared inference context. Normalize all of
        # them before any declaration body is analyzed so generic dispatch is
        # independent of source/import order.
        self._normalize_registered_types(program)
        self._validate_registered_declarations(program)
        self._resolve_interface_parents(program)
        self._validate_inheritance(program)
        self._validate_interfaces(program)
        self._validate_overrides(program)
        self._compute_cyclable_flags()
        self._validate_aggregate_declarations(program)
        for decl in self._decls_with_file(program):
            self._analyze_decl(decl)
        from .generic_instance_closure import close_generic_instance_graph

        close_generic_instance_graph(self)
        self._validate_generated_c_symbols(program)
        return AnalyzedProgram(
            program=program,
            generic_instances=self.generic_instances,
            class_table=self.class_table,
            generic_method_instances=self.generic_method_instances,
            generic_method_call_args=self.generic_method_call_args,
            function_table=self.function_table,
            typedef_table=self.typedef_table,
            struct_table=self.struct_table,
            node_types=self.node_types,
            enum_table=self.enum_table,
            interface_table=self.interface_table,
            rich_enum_table=self.rich_enum_table,
            errors=self.errors,
            warnings=self.warnings,
            diags=self.diags,
            occurrences=self.occurrences,
        )

    def _decls_with_file(self, program: Program):
        """Iterate top-level decls, tracking their source-file provenance.

        ``ImportDecl`` is skipped: the CLI front-end resolves imports away
        before analysis, but the LSP composes programs that may still contain
        them, so analysis treats them as no-ops everywhere.
        """
        from ..ast_nodes import ImportDecl

        for decl in program.declarations:
            if isinstance(decl, ImportDecl):
                continue
            self.current_source_file = getattr(decl, "source_file", None)
            yield decl
        self.current_source_file = None

    def _error(self, msg: str, line: int = 0, col: int = 0):
        self.errors.append(f"{msg} at {line}:{col}")
        self.diags.append(Diag(msg, line, col, "error", self.current_source_file))

    def _warning(self, msg: str, line: int = 0, col: int = 0):
        self.warnings.append(f"{msg} at {line}:{col}")
        self.diags.append(Diag(msg, line, col, "warning", self.current_source_file))

    def _push_scope(self):
        self.scope = Scope(parent=self.scope)

    def _pop_scope(self):
        forget = getattr(self, "_forget_nonnull_symbols", None)
        if forget is not None:
            forget(self.scope.symbols.values())
        self.scope = self.scope.parent

    def _local_symbol(
        self,
        name: str,
        type_: TypeExpr,
        kind: str,
        line: int = 0,
        col: int = 0,
        *,
        owned_storage: bool = False,
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
