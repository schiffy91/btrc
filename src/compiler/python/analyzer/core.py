"""Analyzer core: data structures, scope management, and orchestration."""

from __future__ import annotations

from ..ast_nodes import MethodDecl, Program, RichEnumDecl, TypeExpr
from .analysis_context import AnalysisContext
from .core_models import (
    AnalyzedProgram,
    ClassInfo,
    Occurrence,
    Scope,
    SymbolInfo,
)
from .core_models import (
    AnalyzerError as AnalyzerError,
)


class AnalyzerBase:
    def __init__(self, context: AnalysisContext):
        self.context = context
        self.generic_instances: dict[str, list[tuple[TypeExpr, ...]]] = {}
        self.generic_method_instances: dict[tuple[str, str], list[tuple[tuple, tuple]]] = {}
        self.generic_method_call_args: dict[int, tuple] = {}
        self._hosted_call_ids: set[int] = set()
        self.scope: Scope = Scope()
        self.global_scope: Scope = self.scope
        self.current_class: ClassInfo | None = None
        self.current_method: MethodDecl | None = None
        self.current_callable = None
        self._analyzing_parameter_default = False
        self._analyzing_constructor_default = False
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
        self.array_iteration_capacity_ids: set[int] = set()
        self._nonnull_paths: set = set()
        # Symbol identities whose storage address has escaped. A later call can
        # rebind those locals indirectly, so nullable refinements for them are
        # not stable across calls.
        self._address_escaped_symbol_ids: set[int] = set()
        # Rich-enum payloads are shallow borrowed references. Classify their
        # defaults once in declaration scope so caller shadowing cannot change
        # whether an omitted default would create an unrepresentable owner.
        self.rich_enum_unsafe_default_ids: set[int] = set()
        # Occurrence recording is OFF by default so the CLI compiler pays
        # nothing. The LSP flips it on before analyzing the user program.
        self.record_occurrences: bool = False
        self.occurrences: dict[int, Occurrence] = {}
        # Stack of (outer symbol map, captured type map) for nested lambdas.
        # Symbol identity, not spelling, distinguishes a true capture from a
        # lambda-local declaration that shadows an outer name.
        self._lambda_contexts: list[tuple[dict[str, SymbolInfo], dict[str, TypeExpr]]] = []

    def analyze(self, program: Program) -> AnalyzedProgram:
        # Definition sites for occurrence recording are rebuilt per analysis.
        self._recording_program = program
        self._decl_index_cache = None
        self._unresolved_direct_callee_ids: set[int] = set()
        self._unresolved_c_symbol_reference_ids: set[int] = set()
        self._hosted_call_ids = set()
        self.array_iteration_capacity_ids = set()
        self.rich_enum_unsafe_default_ids = set()
        self.declarations.register(program)
        # Registered types are a shared inference context. Normalize all of
        # them before any declaration body is analyzed so generic dispatch is
        # independent of source/import order.
        self._normalize_registered_types(program)
        self._validate_registered_declarations(program)
        self.declarations.resolve_interface_parents(program)
        self.hierarchy.validate(program)
        self._compute_cyclable_flags()
        self._validate_aggregate_declarations(program)
        from .rich_enum_defaults import analyze_rich_enum_defaults

        for declaration in self.context.declarations(program):
            if isinstance(declaration, RichEnumDecl):
                analyze_rich_enum_defaults(self, declaration)
        for decl in self.context.declarations(program):
            self._analyze_decl(decl)
        from .generic_instance_closure import close_generic_instance_graph

        close_generic_instance_graph(self)
        self._validate_generated_c_symbols(program)
        return AnalyzedProgram(
            program=program,
            generic_instances=self.generic_instances,
            class_table=self.declarations.class_table,
            generic_method_instances=self.generic_method_instances,
            generic_method_call_args=self.generic_method_call_args,
            function_table=self.declarations.function_table,
            global_var_types={
                name: declaration.type
                for name, declaration in self.declarations.global_declarations.items()
                if declaration.type is not None
            },
            hosted_call_ids=self._hosted_call_ids,
            typedef_table=self.declarations.typedef_table,
            struct_table=self.declarations.struct_table,
            node_types=self.node_types,
            enum_table=self.declarations.enum_table,
            interface_table=self.declarations.interface_table,
            rich_enum_table=self.declarations.rich_enum_table,
            rich_enum_unsafe_default_ids=set(self.rich_enum_unsafe_default_ids),
            array_iteration_capacity_ids=set(self.array_iteration_capacity_ids),
            errors=self.context.errors,
            warnings=self.context.warnings,
            diags=self.context.diagnostics,
            occurrences=self.occurrences,
        )

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
            decl_file=self.context.current_source_file,
            owned_storage=owned_storage,
        )

    def _claim_local_binding(
        self,
        name,
        kind,
        line=0,
        col=0,
        *,
        c_name_generated=False,
    ) -> bool:
        """Claim a name in exactly the current lexical scope."""
        self.declaration_policy.validate_name(
            name,
            kind.capitalize(),
            line,
            col,
            c_name_generated=c_name_generated,
        )
        existing = self.scope.symbols.get(name)
        if existing is None or existing.kind == "function":
            outer = self.scope.parent.lookup(name) if self.scope.parent else None
            if outer is not None and self._contains_thread_storage(outer.type):
                self.context.error(
                    f"Binding '{name}' cannot shadow an active Thread owner",
                    line,
                    col,
                )
                return False
            return True
        self.context.error(
            f"Duplicate {kind} name '{name}' in the same scope",
            line,
            col,
        )
        return False
