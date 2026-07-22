"""IR Generator: main class and module-level orchestration.

Walks AnalyzedProgram → IRModule. All lowering happens here and in sub-modules.
"""

from __future__ import annotations

from ...analyzer.core import AnalyzedProgram, ClassInfo
from ...ast_nodes import TypeExpr
from ..nodes import IRModule, IRVar
from .feature_scan import _block_uses_trycatch, _stmt_uses_trycatch  # noqa: F401
from .module_generation import _ModuleGenerationMixin
from .ownership_state import _OwnershipStateMixin


class IRGenerator(_OwnershipStateMixin, _ModuleGenerationMixin):
    """Walks an analyzed AST and produces an IRModule."""

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
        # debug line mapping: combined-source line -> (abs_file, native_line),
        # used to emit #line directives so DWARF points at .btrc source.
        self.line_map = line_map
        # Default arguments retain declaration-file coordinates even when the
        # stdlib and user ASTs were parsed in separate line spaces.
        self.declaration_line_map = declaration_line_map
        self.freestanding = freestanding
        self._init_ownership_state(analyzed, freestanding=freestanding)
        self.module = IRModule()
        from .packing import declaration_pack_alignments

        self._pack_alignments = declaration_pack_alignments(analyzed.program)
        self.module.freestanding = freestanding
        self.module.debug = debug
        self._lambda_counter = 0
        self._temp_counter = 0
        self._cleanup_take_adapters: dict[str, str] = {}
        self._cleanup_take_adapter_defs = []
        self._cleanup_take_adapters_finalized = False
        self._arc_slot_adapters: dict[str, str] = {}
        self._mutex_value_adapters: dict[str, str] = {}
        # Track which helpers are needed
        self._used_helpers: set[str] = set()
        self._gpu_kernels = {}
        self._emitted_gpu_functions: set[str] = set()
        # Current class context (for method lowering)
        self.current_class: ClassInfo | None = None
        self.current_class_name: str = ""
        # While lowering a custom accessor for a property that also owns an
        # automatic backing slot, `self.property` denotes that slot.  Outside
        # the accessor it must route through the public getter/setter.
        self.current_property_backing: str | None = None
        # Nearest lexical binding → whether its C representation is a real
        # array (True) or a scalar/pointer that must shadow outer arrays (False).
        self._c_array_scopes: list[dict[str, bool]] = []
        # Lambda capture environment tracking:
        # Maps fn_ptr variable name → env variable name
        self._fn_ptr_envs: dict[str, str] = {}
        # Lexical function-pointer bindings and their managed-return ABI.
        # Source functions/lambdas return +1; arbitrary C callbacks are
        # borrowed. ``ambiguous`` is a conservative control-flow join and is
        # rejected when the callback returns a managed value.
        self._callable_return_abis: dict[str, str] = {}
        self._callable_types: dict[str, TypeExpr] = {}
        self._callable_scope_declarations: list[set[str]] = []
        self._callable_exception_captures: list[tuple[frozenset[str], list[dict[str, str]]]] = []
        self._callable_loop_captures: list[tuple[frozenset[str], list[dict[str, str]], list[dict[str, str]]]] = []
        # Last lambda ID assigned (for linking lambda to var decl)
        self._last_lambda_id: int = 0
        # C return type of the function/method currently being lowered. Used to
        # declare the ARC return temp with a concrete type (never __auto_type).
        # Set at every function-body lowering entry point; "int" is a safe
        # default (matches main's implicit return).
        self.current_return_c_type: str = "int"
        self.current_return_type: TypeExpr | None = TypeExpr(base="int")
        # Functions/methods return managed values at +1. Property getters are
        # field-like borrowed projections and temporarily disable this ABI.
        self.current_return_owned: bool = True
        self._normalizing_void_main: bool = False
        # ARC: owning-temporary substitution. When an owning temporary (e.g.
        # `new Obj()`) is passed directly to a `keep` parameter, it is hoisted
        # into a temp var so it can be released after the call. Maps the AST arg
        # node id -> the IRVar that replaces it during call lowering.
        self._owning_temp_overrides: dict[int, IRVar] = {}
        self._type_temp_overrides: dict[int, object] = {}
        # `sizeof(expr)` needs the source expression's C type and must never
        # introduce evaluation-order or ARC statement-expression boundaries.
        self._unevaluated_depth = 0

    def generate(self) -> IRModule:
        """Generate the complete IR module from the analyzed program."""
        from .type_render_context import type_render_scope
        from .types import fn_ptr_typedef_scope

        with fn_ptr_typedef_scope(), type_render_scope(self.analyzed.typedef_table):
            self._emit_includes()
            self._emit_forward_decls()
            # Signatures and bodies can each register callback types. Draining
            # twice still emits every declaration before its first consumer.
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
        self._temp_counter += 1
        return f"{prefix}_{self._temp_counter}"

    def fresh_lambda_id(self) -> int:
        """Generate a unique lambda ID."""
        self._lambda_counter += 1
        return self._lambda_counter

    def use_helper(self, name: str):
        """Mark a runtime helper as used."""
        self._used_helpers.add(name)


def generate_ir(
    analyzed: AnalyzedProgram,
    *,
    debug: bool = False,
    source_file: str = "",
    freestanding: bool = False,
    line_map=None,
    declaration_line_map=None,
) -> IRModule:
    """Generate an IR module from an analyzed program.

    This is the main entry point for the IR generation pipeline.
    """
    gen = IRGenerator(
        analyzed,
        debug=debug,
        source_file=source_file,
        freestanding=freestanding,
        line_map=line_map,
        declaration_line_map=declaration_line_map,
    )
    return gen.generate()
