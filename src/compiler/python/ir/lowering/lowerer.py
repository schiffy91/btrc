"""Composition root for the Python compiler's structured IR lowering."""

from __future__ import annotations

from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.analyzer.types import IndexedProtocolResolver, TypeIdentity
from src.compiler.python.frontend.sources import SourceMap
from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

from ..nodes import IRModule
from .calls import (
    CallableSignatureLowerer,
    CallableStorageBoundary,
    CallBoundaryLowerer,
    CallLowerer,
    DefaultArgumentLoweringContext,
)
from .classes import ClassLowerer
from .collections import CollectionLowerer
from .concurrency import ConcurrencyLowerer
from .control_flow import ControlFlowLowerer
from .declarations import DeclarationLowerer
from .exceptions import ExceptionLowerer
from .expressions import ExpressionLowerer
from .functions import FunctionLowerer
from .generics import GenericSpecializer
from .gpu import GpuLowerer
from .iteration import IterationLowerer
from .ownership import (
    CleanupScopeState,
    CleanupSlotRegistry,
    CycleMetadata,
    ManagedLifetimeLowerer,
    ManagedValueSemantics,
    OwnershipLowerer,
    OwnershipOperandOrder,
)
from .session import LoweringSession
from .statements import StatementLowerer
from .storage import StorageLowerer
from .translation_unit import TranslationUnitLowerer
from .types import CTypeLowerer


class IRLowerer:
    """Construct the lowering DAG and expose its single stage operation."""

    def __init__(
        self,
        analyzed: AnalyzedProgram,
        *,
        debug: bool = False,
        source_file: str = "",
        freestanding: bool = False,
        source_map: SourceMap | None = None,
        type_identity: TypeIdentity | None = None,
        runtime_catalog: RuntimeHelperCatalog | None = None,
    ) -> None:
        identity = type_identity or TypeIdentity()
        catalog = runtime_catalog or RuntimeHelperCatalog()
        module = IRModule(freestanding=freestanding, debug=debug)
        session = LoweringSession(
            module=module,
            node_types=analyzed.node_types,
            debug=debug,
            source_file=source_file,
            freestanding=freestanding,
            source_map=source_map,
            runtime_helpers=catalog.selection(),
        )
        program_has_exceptions = TranslationUnitLowerer.program_uses_trycatch(analyzed.program)

        types = CTypeLowerer(session, analyzed, type_identity=identity)
        signatures = CallableSignatureLowerer(analyzed, types)
        index_protocols = IndexedProtocolResolver(identity, analyzed.class_table)
        default_context = DefaultArgumentLoweringContext(identity)
        values = ManagedValueSemantics(analyzed, identity, types)
        cycles = CycleMetadata(analyzed, values, identity)
        cleanup_slots = CleanupSlotRegistry(session)
        cleanup_scope = CleanupScopeState(
            session,
            cross_function_enabled=program_has_exceptions,
        )
        lifetime = ManagedLifetimeLowerer(
            context=session,
            analyzed=analyzed,
            values=values,
            cycles=cycles,
            cleanup_slots=cleanup_slots,
            cleanup_scope=cleanup_scope,
            types=types,
        )
        ownership = OwnershipLowerer(
            session,
            analyzed,
            types,
            index_protocols,
            values,
            cycles,
            lifetime,
            cleanup_scope,
            program_has_exceptions=program_has_exceptions,
        )
        operand_order = OwnershipOperandOrder(
            session,
            analyzed,
            values,
            types,
            ownership,
        )
        call_boundary = CallBoundaryLowerer(
            session,
            lifetime,
            cleanup_scope,
            values,
        )
        callable_boundaries = CallableStorageBoundary(analyzed, values, identity)
        collections = CollectionLowerer(
            session,
            analyzed,
            types,
            identity,
            ownership,
            values,
            lifetime,
            cycles,
            cleanup_slots,
            cleanup_scope,
        )
        storage = StorageLowerer(
            session,
            analyzed,
            types,
            ownership,
            values,
            lifetime,
        )
        calls = CallLowerer(
            session,
            analyzed,
            types,
            default_context,
            identity,
            ownership,
            values,
            operand_order,
        )
        concurrency = ConcurrencyLowerer(
            session,
            analyzed,
            types,
            identity,
            ownership,
            values,
            lifetime,
            cleanup_slots,
            storage,
        )
        gpu = GpuLowerer(
            session,
            analyzed,
            types,
            ownership,
            values,
            lifetime,
            cleanup_scope,
            operand_order,
            calls,
            storage,
        )
        expressions = ExpressionLowerer(
            session,
            analyzed,
            types,
            default_context,
            identity,
            index_protocols,
            ownership,
            values,
            lifetime,
            cleanup_slots,
            cleanup_scope,
            operand_order,
            call_boundary,
            callable_boundaries,
            storage,
            calls,
            collections,
            concurrency,
            gpu,
            program_has_exceptions=program_has_exceptions,
            source_visible_helpers=catalog.source_visible_names,
        )
        control_flow = ControlFlowLowerer(
            session,
            analyzed,
            types,
            expressions,
            ownership,
            lifetime,
            cleanup_scope,
        )
        exceptions = ExceptionLowerer(
            session,
            analyzed,
            types,
            expressions,
            ownership,
        )
        iteration = IterationLowerer(
            session,
            analyzed,
            types,
            identity,
            storage,
            ownership,
            values,
            lifetime,
            cleanup_scope,
        )
        statements = StatementLowerer(
            session,
            analyzed,
            types,
            expressions,
            storage,
            ownership,
            values,
            lifetime,
            cleanup_scope,
            control_flow,
            exceptions,
            iteration,
            gpu,
        )
        functions = FunctionLowerer(
            session,
            analyzed,
            types,
            signatures,
            default_context,
            expressions,
            statements,
            ownership,
            exceptions,
            concurrency,
            gpu,
            calls,
        )
        classes = ClassLowerer(
            session,
            analyzed,
            types,
            signatures,
            identity,
            expressions,
            statements,
            collections,
            ownership,
            values,
            lifetime,
            cycles,
            calls,
            callable_boundaries,
        )
        declarations = DeclarationLowerer(session, analyzed, types, signatures, expressions)
        specializer = GenericSpecializer(analyzed, identity)
        self._translation_unit = TranslationUnitLowerer(
            session,
            analyzed,
            types,
            signatures,
            identity,
            expressions,
            collections,
            declarations,
            classes,
            functions,
            specializer,
            gpu,
            exceptions,
            callable_boundaries,
            cleanup_slots,
        )

    def lower(self) -> IRModule:
        return self._translation_unit.lower()
