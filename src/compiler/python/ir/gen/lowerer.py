"""IR lowering composition root and module-level orchestration.

Walks AnalyzedProgram → IRModule. All lowering happens here and in sub-modules.
"""

from __future__ import annotations

from ...analyzer.core import AnalyzedProgram, ClassInfo
from ...ast_nodes import TypeExpr
from ..nodes import IRModule, IRVar
from .call_arguments import CallArgumentLowerer
from .call_boundary import CallBoundaryLowerer
from .call_emission import CallDispatchLowerer
from .calls import CallLowerer
from .feature_scan import _block_uses_trycatch, _stmt_uses_trycatch  # noqa: F401
from .helpers import RuntimeHelperRegistry
from .hosted_result_conversion import HostedResultLowerer
from .lowering_context import LoweringContext
from .managed_type_classifier import ManagedTypeClassifier
from .module_generation import _ModuleGenerationMixin
from .ownership import OwnershipLowerer
from .ownership_lifetime import ManagedLifetimeLowerer
from .ownership_order import OwnershipOperandOrder
from .ownership_state import _OwnershipStateMixin


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
    ):
        self.analyzed = analyzed
        self.debug = debug
        self.source_file = source_file
        self.line_map = line_map
        self.declaration_line_map = declaration_line_map
        self.freestanding = freestanding
        self.module = IRModule()
        self.helpers = RuntimeHelperRegistry()
        self.context = LoweringContext(
            analyzed=self.analyzed,
            module=self.module,
            helpers=self.helpers,
        )
        self._init_ownership_state(analyzed, freestanding=freestanding)
        from .packing import declaration_pack_alignments

        self._pack_alignments = declaration_pack_alignments(analyzed.program)
        self.module.freestanding = freestanding
        self.module.debug = debug
        self._lambda_counter = 0
        self.context.temporaries.counter = 0
        self._cleanup_take_adapters: dict[str, str] = {}
        self._cleanup_take_adapter_defs = []
        self._cleanup_take_adapters_finalized = False
        self._arc_slot_adapters: dict[str, str] = {}
        self._mutex_value_adapters: dict[str, str] = {}
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

        self.managed_types = ManagedTypeClassifier(self.analyzed)
        self.ownership_order = OwnershipOperandOrder(
            self.context,
            self.managed_types,
        )
        self.lifetime = ManagedLifetimeLowerer(self, self.managed_types)
        boundaries = CallBoundaryLowerer(self.context, self.lifetime)
        call_dispatch = CallDispatchLowerer(self)
        self.ownership = OwnershipLowerer(
            self.context,
            self.managed_types,
            self.ownership_order,
            self.lifetime,
            boundaries,
            call_dispatch,
        )
        hosted_results = HostedResultLowerer(self.context)
        call_arguments = CallArgumentLowerer(
            self,
            self.context,
            self.ownership,
            hosted_results,
            call_dispatch,
        )
        self.calls = CallLowerer(
            self.context,
            self.ownership,
            hosted_results,
            call_arguments,
            call_dispatch,
        )

    def lower(self) -> IRModule:
        """Lower the analyzed program into a complete IR module."""
        from .type_render_context import type_render_scope
        from .types import fn_ptr_typedef_scope

        with fn_ptr_typedef_scope(), type_render_scope(self.analyzed.typedef_table):
            self._emit_includes()
            self._emit_forward_decls()
            self._emit_fn_ptr_typedefs()
            self._emit_structs()
            from .gpu_registration import emit_gpu_functions

            emit_gpu_functions(self)
            self._emit_generic_collections()
            self._emit_enums()
            self._emit_declarations()
            self._emit_fn_ptr_typedefs()
            from .cleanup_slots import finalize_cleanup_take_adapters

            finalize_cleanup_take_adapters(self)
            from .setjmp_volatility import apply_setjmp_volatility

            apply_setjmp_volatility(self.module)
            self._emit_helpers()
            self.module.refresh_type_declarations()
            from ..runtime_dependencies import refresh_runtime_dependencies

            refresh_runtime_dependencies(self.module)
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
