"""IR lowering composition root and module-level orchestration.

Walks AnalyzedProgram → IRModule. All lowering happens here and in sub-modules.
"""

from __future__ import annotations

from ...analyzer.core import AnalyzedProgram, ClassInfo
from ...ast_nodes import TypeExpr
from ...index_protocol import IndexedProtocolResolver
from ...operator_semantics import OperatorSemantics
from ...type_identity import TypeIdentity
from ..nodes import IRModule, IRVar
from .arc import ManagedReleaseLowerer
from .call_arguments import CallArgumentLowerer
from .call_boundary import CallBoundaryLowerer
from .call_emission import CallDispatchLowerer
from .calls import CallLowerer
from .cleanup_slots import CleanupSlotRegistry
from .cycle_metadata import CycleMetadata
from .default_arguments import DefaultArgumentLoweringContext
from .feature_scan import _block_uses_trycatch, _stmt_uses_trycatch  # noqa: F401
from .helpers import RuntimeHelperRegistry
from .hosted_result_conversion import HostedResultLowerer
from .lowering_context import LoweringContext
from .managed_values import ManagedValueSemantics
from .module_generation import _ModuleGenerationMixin
from .ownership import OwnershipLowerer
from .ownership_lifetime import ManagedLifetimeLowerer
from .ownership_order import OwnershipOperandOrder
from .ownership_state import _OwnershipStateMixin
from .types import CTypeRenderer


class IRLowerer(_OwnershipStateMixin, _ModuleGenerationMixin):
    """Walk an analyzed AST and compose its domain lowerers."""

    def __init__(
        self,
        analyzed: AnalyzedProgram,
        *,
        debug: bool = False,
        source_file: str = "",
        freestanding: bool = False,
        line_map=None,
        declaration_line_map=None,
        type_identity: TypeIdentity | None = None,
    ):
        self.analyzed = analyzed
        self.type_identity = type_identity if type_identity is not None else TypeIdentity()
        self.debug = debug
        self.source_file = source_file
        self.line_map = line_map
        self.declaration_line_map = declaration_line_map
        self.freestanding = freestanding
        self.module = IRModule()
        self.helpers = RuntimeHelperRegistry()
        self._default_arguments = DefaultArgumentLoweringContext(self.type_identity)
        self.type_renderer = CTypeRenderer(
            self.analyzed.typedef_table,
            self._default_arguments,
            self.type_identity,
        )
        self.context = LoweringContext(
            analyzed=self.analyzed,
            module=self.module,
            helpers=self.helpers,
        )
        self.managed_values = ManagedValueSemantics(
            self.analyzed,
            self.type_identity,
        )
        self.cycles = CycleMetadata(
            self.analyzed,
            self.managed_values,
            self.type_identity,
        )
        self.cleanup_slots = CleanupSlotRegistry(
            self.module,
            self.helpers,
        )
        self.operator_types = OperatorSemantics(
            self.type_identity,
            class_table=self.analyzed.class_table,
            interface_table=self.analyzed.interface_table,
            enum_names=self.analyzed.enum_table,
        )
        self.index_protocols = IndexedProtocolResolver(
            self.type_identity,
            self.analyzed.class_table,
        )
        self._init_ownership_state(analyzed, freestanding=freestanding)
        from .packing import declaration_pack_alignments

        self._pack_alignments = declaration_pack_alignments(analyzed.program)
        self.module.freestanding = freestanding
        self.module.debug = debug
        self._lambda_counter = 0
        self.context.temporaries.counter = 0
        self._gpu_kernels = {}
        self._emitted_gpu_functions: set[str] = set()
        self.current_class: ClassInfo | None = None
        self.current_class_name: str = ""
        self._c_array_scopes: list[dict[str, bool]] = []
        self.context.callable_environments = {}
        self.context.callable_types = {}
        self._callable_scope_declarations: list[set[str]] = []
        self._callable_exception_captures: list[tuple[frozenset[str], list[dict[str, str]]]] = []
        self._callable_loop_captures: list[
            tuple[
                frozenset[str],
                list[dict[str, str]],
                list[dict[str, str]],
            ]
        ] = []
        self._last_lambda_id = 0
        self.current_return_c_type = "int"
        self.current_return_type: TypeExpr | None = TypeExpr(base="int")
        self.current_return_owned = True
        self._normalizing_void_main = False
        self.context.owning_overrides: dict[int, IRVar] = {}
        self.context.type_overrides: dict[int, object] = {}
        self.context.unevaluated_depth = 0

        self.ownership_order = OwnershipOperandOrder(
            self.context,
            self.managed_values,
            self.index_protocols,
        )
        self.lifetime = ManagedLifetimeLowerer(
            context=self.context,
            helpers=self.helpers,
            values=self.managed_values,
            cycles=self.cycles,
            cleanup_slots=self.cleanup_slots,
            cleanup_scope=self,
            type_renderer=self.type_renderer,
        )
        self.managed_releases = ManagedReleaseLowerer(
            self.lifetime,
            self.type_renderer,
        )
        boundaries = CallBoundaryLowerer(self.context, self.lifetime)
        call_dispatch = CallDispatchLowerer(
            self,
            self.type_renderer,
            self._default_arguments,
        )
        self.ownership = OwnershipLowerer(
            self.context,
            self.managed_values,
            self.ownership_order,
            self.lifetime,
            boundaries,
            call_dispatch,
            self.type_renderer,
            self.index_protocols,
        )
        hosted_results = HostedResultLowerer(self.context)
        call_arguments = CallArgumentLowerer(
            self,
            self.context,
            self.ownership,
            hosted_results,
            call_dispatch,
            self.type_renderer,
            self._default_arguments,
        )
        self.calls = CallLowerer(
            self.context,
            self.ownership,
            hosted_results,
            call_arguments,
            call_dispatch,
            self.type_renderer,
            self._default_arguments,
        )

    def lower(self) -> IRModule:
        """Lower the analyzed program into a complete IR module."""
        self._emit_includes()
        self._emit_forward_decls()
        self._emit_fn_ptr_typedefs()
        self._emit_structs()
        from .gpu_registration import emit_gpu_functions

        emit_gpu_functions(
            self,
            self.type_renderer,
            self._default_arguments,
        )
        self._emit_generic_collections()
        self._emit_enums()
        self._emit_declarations()
        self._emit_fn_ptr_typedefs()
        self.cleanup_slots.finalize()
        from .setjmp_volatility import apply_setjmp_volatility

        apply_setjmp_volatility(self.module)
        self._emit_helpers()
        self.module.refresh_type_declarations()
        from ..runtime_dependencies import RuntimeDependencyMaterializer

        RuntimeDependencyMaterializer(self.module).refresh()
        self.module.validate_declarations()
        return self.module

    def fresh_temp(self, prefix: str = "__tmp") -> str:
        """Generate a unique temporary variable name."""
        return self.context.fresh_temp(prefix)

    def fresh_lambda_id(self) -> int:
        """Generate a unique lambda ID."""
        self._lambda_counter += 1
        return self._lambda_counter


__all__ = ["IRLowerer"]
