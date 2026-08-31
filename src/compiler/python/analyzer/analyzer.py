"""Semantic-analysis composition root."""

from __future__ import annotations

from src.compiler.python.runtime.catalog import RuntimeHelperCatalog
from src.compiler.python.syntax.ast.generated import Program, RichEnumDecl

from .aggregates import AggregateAnalyzer
from .calls import CallAnalyzer
from .declarations import DeclarationRegistry, HierarchyValidator, SignatureTypePolicy
from .expressions import ExpressionAnalyzer
from .flow import ControlFlowAnalyzer
from .generated_symbols import GeneratedSymbolRegistry
from .generics import GenericAnalyzer
from .gpu import GpuAnalyzer
from .macros import SourceMacroAnalyzer
from .ownership import CallableValueSemantics, OwnershipAnalyzer
from .program import AnalysisSession, AnalyzedProgram, DeclarationIndex
from .realtime import RealtimeAnalyzer
from .statements import StatementAnalyzer
from .storage import StorageModel
from .types import NumericLiteralSemantics, TypeIdentity, TypeSystem


class SemanticAnalyzer:
    """Compose and run one isolated semantic-analysis session."""

    def __init__(
        self,
        *,
        record_occurrences: bool = False,
        seed: AnalyzedProgram | None = None,
        numeric_literals: NumericLiteralSemantics | None = None,
        type_identity: TypeIdentity | None = None,
        runtime_catalog: RuntimeHelperCatalog | None = None,
    ) -> None:
        session = AnalysisSession()
        identity = type_identity if type_identity is not None else TypeIdentity()
        literal_semantics = numeric_literals if numeric_literals is not None else NumericLiteralSemantics()
        runtime_helpers = runtime_catalog if runtime_catalog is not None else RuntimeHelperCatalog()
        session.source_visible_runtime_names = runtime_helpers.source_visible_names
        index = DeclarationIndex()
        declarations = DeclarationRegistry(session, index, identity, seed=seed)
        types = TypeSystem(session, index, numeric_literals=literal_semantics, type_identity=identity)
        aggregates = AggregateAnalyzer(session, index, types)
        storage = StorageModel(session, index, types, aggregates)
        callable_values = CallableValueSemantics(session, index, types)
        ownership = OwnershipAnalyzer(session, index, types, storage, callable_values)
        gpu = GpuAnalyzer(session, index, types, aggregates)
        macros = SourceMacroAnalyzer(session, index, types)
        generics = GenericAnalyzer(session, index, types)
        calls = CallAnalyzer(
            session,
            index,
            types,
            aggregates,
            storage,
            ownership,
            gpu,
            macros,
            generics,
        )
        expressions = ExpressionAnalyzer(
            session, declarations, index, types, aggregates, storage, ownership, calls, gpu, generics
        )
        flow = ControlFlowAnalyzer(session, types)
        generated_symbols = GeneratedSymbolRegistry(session, index, types, storage, macros, runtime_helpers)
        realtime = RealtimeAnalyzer(session, index, runtime_helpers)
        statements = StatementAnalyzer(
            session,
            declarations,
            index,
            types,
            aggregates,
            storage,
            ownership,
            expressions,
            flow,
            gpu,
            generics,
            generated_symbols,
        )
        signature_types = SignatureTypePolicy(session, index, identity)
        hierarchy = HierarchyValidator(session, index, signature_types)
        session.record_occurrences = record_occurrences
        if seed is not None:
            session.generic_instances = {name: list(instances) for name, instances in seed.generic_instances.items()}
            session.generic_class_callable_instances = {
                callable_identity: list(instances)
                for callable_identity, instances in seed.generic_class_callable_instances.items()
            }
            session.generic_class_callable_dependencies = {
                callable_identity: list(dependencies)
                for callable_identity, dependencies in seed.generic_class_callable_dependencies.items()
            }
            session.generic_class_lifecycle_dependencies = {
                owner: list(dependencies) for owner, dependencies in seed.generic_class_lifecycle_dependencies.items()
            }
            session.generic_method_callable_dependencies = {
                callable_identity: list(dependencies)
                for callable_identity, dependencies in seed.generic_method_callable_dependencies.items()
            }
        self.session = session
        self.index = index
        self.declarations = declarations
        self.types = types
        self.aggregates = aggregates
        self.expressions = expressions
        self.calls = calls
        self.statements = statements
        self.flow = flow
        self.storage = storage
        self.callable_values = callable_values
        self.ownership = ownership
        self.generics = generics
        self.gpu = gpu
        self.macros = macros
        self.generated_symbols = generated_symbols
        self.realtime = realtime
        self.signature_types = signature_types
        self.hierarchy = hierarchy

    def analyze(self, program: Program) -> AnalyzedProgram:
        """Register declarations, analyze bodies, and freeze the result."""
        state = self.session
        state.begin(program)
        self.ownership.begin()
        self.declarations.register(program)
        self.types.normalize_declarations(program)
        self.statements.validate_declarations(program)
        self.declarations.resolve_interface_parents(program)
        self.hierarchy.validate(program)
        self.ownership.compute_cyclable_flags()
        self.aggregates.validate_declarations(program)
        for declaration in state.declarations(program):
            if isinstance(declaration, RichEnumDecl):
                self.statements.analyze_rich_enum_defaults(declaration)
        for declaration in state.declarations(program):
            self.statements.analyze_declaration(declaration)
        self.generics.close_generic_instance_graph()
        realtime_safe_callables = self.realtime.analyze(program)
        self.ownership.validate_generic_type_facts()
        self.generated_symbols.validate_program_symbols(program)
        return AnalyzedProgram(
            program=program,
            generic_instances=state.generic_instances,
            class_table=self.index.class_table,
            generic_class_callable_instances=state.generic_class_callable_instances,
            generic_class_callable_dependencies=state.generic_class_callable_dependencies,
            generic_class_lifecycle_dependencies=state.generic_class_lifecycle_dependencies,
            generic_method_callable_dependencies=state.generic_method_callable_dependencies,
            generic_method_instances=state.generic_method_instances,
            generic_method_call_args=state.generic_method_call_args,
            function_table=self.index.function_table,
            global_var_types={
                name: declaration.type
                for name, declaration in self.index.global_declarations.items()
                if declaration.type is not None
            },
            defined_global_names=frozenset(self.index.global_definitions),
            hosted_call_ids=set(state.hosted_call_ids),
            realtime_safe_callables=realtime_safe_callables,
            realtime_bounded_loop_ids=set(state.realtime_bounded_loop_ids),
            typedef_table=self.index.typedef_table,
            struct_table=self.index.struct_table,
            node_types=state.node_types,
            enum_table=self.index.enum_table,
            interface_table=self.index.interface_table,
            rich_enum_table=self.index.rich_enum_table,
            rich_enum_unsafe_default_ids=set(state.rich_enum_unsafe_default_ids),
            array_iteration_capacity_ids=set(state.array_iteration_capacity_ids),
            constant_array_bound_ids=set(state.constant_array_bound_ids),
            errors=state.errors,
            warnings=state.warnings,
            diags=state.diagnostics,
            occurrences=state.occurrences,
        )


__all__ = ["SemanticAnalyzer"]
