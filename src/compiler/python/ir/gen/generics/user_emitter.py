"""Mini AST-to-IR emitter for user-defined generic method bodies."""

from __future__ import annotations

from ....source_runtime_symbols import is_source_runtime_helper
from ...nodes import (
    CType,
    IRCast,
    IRCompoundLiteral,
    IRExpr,
    IRFunctionRef,
    IRLiteral,
    IRStmt,
    IRVar,
)
from ..call_boundary import CallBoundaryLowerer
from ..literal_text import format_c_integer_literal
from ..lowering_context import LoweringContext
from ..ownership import OwnershipLowerer
from ..ownership_order import OwnershipOperandOrder
from ..types import CTypeRenderer
from .core import _resolve_type, _resolve_type_c
from .user_constructor_calls import lower_new_constructor_call
from .user_emitter_bindings import (
    reset_source_bindings,
    source_binding_c_name,
)
from .user_emitter_calls import _UserGenericCallMixin
from .user_emitter_fstrings import _UserGenericFStringMixin
from .user_emitter_operators import _UserGenericOperatorMixin
from .user_emitter_scopes import emit_scoped_stmts, reset_scope_state
from .user_emitter_stmts import _UserGenericStmtMixin

__all__ = ["_UserGenericEmitter"]


class _UserGenericEmitter(
    _UserGenericStmtMixin, _UserGenericCallMixin, _UserGenericOperatorMixin, _UserGenericFStringMixin
):
    """Emits IR nodes from AST nodes within a monomorphized generic class."""

    def __init__(
        self,
        type_map,
        mangled,
        type_renderer: CTypeRenderer,
        *,
        gen=None,
        cls_info=None,
        default_arguments=None,
    ):
        self.type_map = type_map
        self.mangled = mangled
        self._type_renderer = type_renderer
        self.type_identity = type_renderer.type_identity
        self._ttc = type_renderer.render
        self._gen = gen
        self._cls_info = cls_info  # the generic class being monomorphized
        self._default_arguments = default_arguments
        # Track variable types for method-call mangling on local variables
        self._var_types = {}
        # Unique temp counter (avoids name collisions without GCC scoping)
        self._temp_counter = 0
        self._func_var_decls = []
        self._try_depth = 0
        self._trycatch_depth = 0
        self._control_context = []
        self._return_c_type = "void"
        self._return_type = None
        self._return_owned = True
        self._batch_explicit_releases = False
        # Explicit ``keep`` inside the built-in collection implementations
        # creates a persistent element edge, including in private helpers such
        # as Map.putRetained.  Batching is a separate public-method concern.
        from ...cycle_boundaries import PUBLIC_COLLECTION_BASES

        self._collection_edge_keeps = bool(cls_info and cls_info.name in PUBLIC_COLLECTION_BASES)
        self._arc_overrides = {}
        self._arc_type_overrides = {}
        self._unevaluated_depth = 0
        self._current_property_backing = None
        reset_scope_state(self)
        if gen is not None:
            self._boundary_ownership = self._build_boundary_ownership(gen)

    def _build_boundary_ownership(self, lowerer):
        """Bind generic ownership sequencing to this emitter's local state."""
        context = LoweringContext(
            analyzed=lowerer.analyzed,
            module=lowerer.module,
            helpers=lowerer.helpers,
            function_declarations=self._func_var_decls,
            owning_overrides=self._arc_overrides,
            type_overrides=self._arc_type_overrides,
            local_ownership_scopes=self._local_ownership_scopes,
            callable_types=self._callable_types,
            callable_return_abis=self._callable_return_abis,
            current_property_backing=self._current_property_backing,
            gpu_cpu_index=lowerer.context.gpu_cpu_index,
            unevaluated_depth=self._unevaluated_depth,
            temporaries=lowerer.context.temporaries,
        )
        self.context = context
        lifetime = lowerer.lifetime.bind(context, self)
        self._boundary_lifetime = lifetime
        return OwnershipLowerer(
            context,
            lowerer.managed_values,
            OwnershipOperandOrder(
                context,
                lowerer.managed_values,
                lowerer.index_protocols,
            ),
            lifetime,
            CallBoundaryLowerer(context, lifetime),
            self,
            self._type_renderer,
            lowerer.index_protocols,
        )

    def _sync_boundary_context(self) -> None:
        """Rebind collections replaced at a generic function boundary."""
        context = self._boundary_ownership.context
        context.function_declarations = self._func_var_decls
        context.owning_overrides = self._arc_overrides
        context.type_overrides = self._arc_type_overrides
        context.local_ownership_scopes = self._local_ownership_scopes
        context.callable_types = self._callable_types
        context.callable_return_abis = self._callable_return_abis
        context.current_property_backing = self._current_property_backing
        context.unevaluated_depth = self._unevaluated_depth

    def _fresh_temp(self, prefix: str = "__tmp") -> str:
        """Generate a unique temporary variable name."""
        if self._gen is not None:
            return self._gen.fresh_temp(prefix)
        self._temp_counter += 1
        return f"{prefix}_{self._temp_counter}"

    def exception_cleanup_active(self) -> bool:
        """Whether this generic body can unwind into a live try frame."""
        return bool(self._gen is not None and (self._try_depth > 0 or self._gen.cross_function_cleanup_enabled))

    def mark_cleanup_registration(self) -> None:
        """Activate this generic body's innermost cleanup baseline."""
        if not self._cleanup_scope_markers:
            return
        marker = self._cleanup_scope_markers[-1]
        if marker is not None:
            self._active_cleanup_markers.add(marker)

    def mark_borrowed_cycle_seeds(self) -> None:
        """Invalidate the cycle proof of every live generic ARC alias."""
        for scope in self._managed_vars_stack:
            for local in scope:
                local.mark_cycle_seed()

    def resolve_c(self, t):
        return _resolve_type_c(
            t,
            self.type_map,
            self._typedefs(),
            self.type_identity,
            render=self._ttc,
        )

    def iter_value_c(self, t):
        resolved = self._resolve(t)
        c_type = self._ttc(resolved)
        if self._gen and resolved and resolved.base in self._gen.analyzed.class_table and not c_type.endswith("*"):
            return f"{c_type}*"
        return c_type

    def _resolve(self, t):
        """Resolve a TypeExpr through the type map."""
        return _resolve_type(t, self.type_map, self._typedefs(), self.type_identity)

    def emit_stmts(self, stmts) -> list[IRStmt]:
        """Emit a list of AST statements as a list of IR statements."""
        return emit_scoped_stmts(self, stmts)

    def reset_var_types(
        self,
        params=None,
        return_type=None,
        *,
        return_owned=True,
        batch_explicit_releases=False,
    ):
        """Reset per-function type/control state and seed its signature."""
        self._var_types = {}
        self._func_var_decls = []
        self._try_depth = 0
        self._trycatch_depth = 0
        self._control_context = []
        self._return_c_type = self.resolve_c(return_type) if return_type else "void"
        self._return_type = self._resolve(return_type) if return_type else None
        self._return_owned = return_owned
        self._batch_explicit_releases = batch_explicit_releases
        self._arc_overrides = {}
        self._arc_type_overrides = {}
        self._current_property_backing = None
        reset_scope_state(self)
        reset_source_bindings(self, params or ())
        self._sync_boundary_context()
        if params:
            for parameter in params:
                if parameter.type:
                    self._var_types[parameter.name] = self._resolve(parameter.type)

    def _exited_try_depth(self, targets):
        depth = 0
        for kind in reversed(self._control_context):
            if kind in targets:
                return depth
            if kind == "try":
                depth += 1
        return 0

    def lower_expression(self, e) -> IRExpr:
        from ....ast_nodes import (
            AssignExpr,
            BinaryExpr,
            BoolLiteral,
            BraceInitializer,
            CallExpr,
            CastExpr,
            CharLiteral,
            FieldAccessExpr,
            FloatLiteral,
            FStringLiteral,
            Identifier,
            IndexExpr,
            IntLiteral,
            ListLiteral,
            MapLiteral,
            NewExpr,
            NullLiteral,
            SelfExpr,
            SizeofExpr,
            StringLiteral,
            TernaryExpr,
            TupleLiteral,
            UnaryExpr,
        )
        from ..errors import unsupported_node

        override = self._arc_overrides.get(id(e))
        if override is not None:
            return override

        if isinstance(e, FieldAccessExpr):
            from .user_emitter_projections import lower_generic_field_access

            return lower_generic_field_access(self, e)
        if isinstance(e, IndexExpr):
            from .user_emitter_projections import lower_generic_index

            return lower_generic_index(self, e)
        if isinstance(e, Identifier):
            predefined = (
                self._default_arguments.predefined_identifier(e) if self._default_arguments is not None else None
            )
            if predefined is not None:
                return IRLiteral(text=predefined)
            if e.name in self._var_types:
                from .user_emitter_identifiers import generic_identifier_reference

                return generic_identifier_reference(
                    self,
                    e,
                    source_binding_c_name(self, e.name),
                )
            if self._gen and is_source_runtime_helper(e.name) and e.name not in self._var_types:
                self._gen.helpers.use(e.name)
                return IRFunctionRef(name=e.name)
            if self._gen and e.name in self._gen.analyzed.function_table and e.name not in self._var_types:
                from ..function_symbols import source_function_c_name

                return IRFunctionRef(name=source_function_c_name(self._gen.analyzed, e.name))
            from .user_emitter_identifiers import generic_identifier_reference

            return generic_identifier_reference(self, e, e.name)
        if isinstance(e, IntLiteral):
            return IRLiteral(text=format_c_integer_literal(e.raw, e.value))
        if isinstance(e, FloatLiteral):
            return IRLiteral(text=e.raw)
        if isinstance(e, BoolLiteral):
            return IRLiteral(text="true" if e.value else "false")
        if isinstance(e, NullLiteral):
            return IRLiteral(text="NULL")
        if isinstance(e, SelfExpr):
            return IRVar(name="self")
        if isinstance(e, StringLiteral):
            return IRLiteral(text=e.value)  # already includes quotes
        if isinstance(e, CharLiteral):
            return IRLiteral(text=e.value)  # already includes quotes
        if isinstance(e, UnaryExpr):
            return self._unary_expr(e)
        if isinstance(e, BinaryExpr):
            return self._binary_expr(e)
        if isinstance(e, TernaryExpr):
            return self._ternary_expr(e)
        if isinstance(e, CastExpr):
            resolved = self.resolve_c(e.target_type)
            return IRCast(target_type=CType(text=resolved), expr=self.lower_expression(e.expr))
        if isinstance(e, SizeofExpr):
            return self._sizeof(e.operand)
        if isinstance(e, CallExpr):
            return self._call(e)
        if isinstance(e, AssignExpr):
            return self._assignment_expr(e)
        if isinstance(e, ListLiteral):
            return self._list_literal(e)
        if isinstance(e, MapLiteral):
            return self._map_literal(e)
        if isinstance(e, BraceInitializer):
            return self._list_literal(e)
        if isinstance(e, FStringLiteral):
            return self._fstring(e)
        if isinstance(e, NewExpr):
            return self._new_expr(e)
        if isinstance(e, TupleLiteral):
            return self._tuple_literal(e)
        raise unsupported_node("generic method expression", e)

    def _sizeof(self, operand) -> IRExpr:
        from .user_emitter_sizeof import lower_generic_sizeof

        return lower_generic_sizeof(self, operand)

    def _collection_literal(self, target: str, lit, target_type=None) -> IRExpr:
        """Build a collection using its contextual concrete target type."""
        from .user_emitter_collections import lower_collection_literal

        return lower_collection_literal(self, target, lit, target_type)

    def _list_literal(self, e) -> IRExpr:
        return self._collection_literal(
            self.mangled,
            e,
            self._resolve_expr_type(e),
        )

    def _map_literal(self, e) -> IRExpr:
        return self._collection_literal(
            self.mangled,
            e,
            self._resolve_expr_type(e),
        )

    def _tuple_literal(self, expression) -> IRExpr:
        """Lower a shallow tuple using this specialization's concrete types."""
        if any(self._owns_expr(element) for element in expression.elements):
            from ..errors import CodegenError

            raise CodegenError("Cannot store an owning temporary in a shallow aggregate")
        tuple_type = self._resolve_expr_type(expression)
        if tuple_type is None or not tuple_type.generic_args:
            from ....ast_nodes import TypeExpr

            tuple_type = TypeExpr(
                base="Tuple",
                generic_args=[
                    self._resolve_expr_type(element) or TypeExpr(base="int") for element in expression.elements
                ],
            )
        return IRCompoundLiteral(
            c_type=CType(text=self.type_identity.generic_symbol("Tuple", tuple_type.generic_args)),
            fields=[(f"_{index}", self.lower_expression(element)) for index, element in enumerate(expression.elements)],
        )

    def _new_expr(self, e) -> IRExpr:
        """Emit new Type(args) as mangled_new(args)."""
        return self._new_with_arc(e)

    def _new_expr_plain(self, e) -> IRExpr:
        """Emit a constructor after managed operands are stabilized."""
        return lower_new_constructor_call(self, e)
