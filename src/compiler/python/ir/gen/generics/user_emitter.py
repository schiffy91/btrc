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
from ..literal_text import format_c_integer_literal
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

    def __init__(self, type_map, mangled, type_to_c_fn, *, gen=None, cls_info=None):
        self.type_map = type_map
        self.mangled = mangled
        self._ttc = type_to_c_fn
        self._gen = gen
        self._cls_info = cls_info  # the generic class being monomorphized
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

    def _fresh_temp(self, prefix: str = "__tmp") -> str:
        """Generate a unique temporary variable name."""
        if self._gen is not None:
            return self._gen.fresh_temp(prefix)
        self._temp_counter += 1
        return f"{prefix}_{self._temp_counter}"

    def resolve_c(self, t):
        return _resolve_type_c(
            t,
            self.type_map,
            self._typedefs(),
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
        return _resolve_type(t, self.type_map, self._typedefs())

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

    def _expr(self, e) -> IRExpr:
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
            from ..default_argument_context import (
                resolve_default_predefined_identifier,
            )

            predefined = resolve_default_predefined_identifier(e)
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
                self._gen.use_helper(e.name)
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
            return IRCast(target_type=CType(text=resolved), expr=self._expr(e.expr))
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
        from ..types import mangle_tuple_type

        return IRCompoundLiteral(
            c_type=CType(text=mangle_tuple_type(tuple_type)),
            fields=[(f"_{index}", self._expr(element)) for index, element in enumerate(expression.elements)],
        )

    def _new_expr(self, e) -> IRExpr:
        """Emit new Type(args) as mangled_new(args)."""
        return self._new_with_arc(e)

    def _new_expr_plain(self, e) -> IRExpr:
        """Emit a constructor after managed operands are stabilized."""
        return lower_new_constructor_call(self, e)
