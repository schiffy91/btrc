"""Mini AST-to-IR emitter for user-defined generic method bodies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCast,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRIndex,
    IRLiteral,
    IRSizeof,
    IRStmt,
    IRStmtExpr,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .core import _resolve_type
from .user_emitter_stmts import (
    _ir_expr_to_text,
    _ir_stmt_to_text,
    _ir_stmts_to_text,
    _UserGenericStmtMixin,
)

if TYPE_CHECKING:
    pass

# Re-export IR-to-text helpers so existing importers don't break
__all__ = [
    "_UserGenericEmitter",
    "_ir_expr_to_text", "_ir_stmt_to_text", "_ir_stmts_to_text",
]

# Magic identifiers — emitted as-is (resolved by C11 _Generic macros).
_MAGIC_CALLS = {"__btrc_eq", "__btrc_lt", "__btrc_gt", "__btrc_hash"}


class _UserGenericEmitter(_UserGenericStmtMixin):
    """Emits IR nodes from AST nodes within a monomorphized generic class."""

    def __init__(self, type_map, mangled, type_to_c_fn, *,
                 gen=None, cls_info=None):
        self.type_map = type_map
        self.mangled = mangled
        self._ttc = type_to_c_fn
        self._gen = gen
        self._cls_info = cls_info  # the generic class being monomorphized
        # Track variable types for method-call mangling on local variables
        self._var_types = {}
        # Unique temp counter (avoids name collisions without GCC scoping)
        self._temp_counter = 0

    def _fresh_temp(self, prefix: str = "__tmp") -> str:
        """Generate a unique temporary variable name."""
        self._temp_counter += 1
        return f"{prefix}_{self._temp_counter}"

    def resolve_c(self, t):
        return self._ttc(_resolve_type(t, self.type_map))

    def iter_value_c(self, t):
        resolved = self._resolve(t)
        c_type = self._ttc(resolved)
        if (self._gen and resolved and resolved.base in self._gen.analyzed.class_table
                and not c_type.endswith("*")):
            return f"{c_type}*"
        return c_type

    def _resolve(self, t):
        """Resolve a TypeExpr through the type map."""
        return _resolve_type(t, self.type_map)

    def emit_stmts(self, stmts) -> list[IRStmt]:
        """Emit a list of AST statements as a list of IR statements."""
        result = []
        for s in stmts:
            result.extend(self._stmt(s))
        return result

    def reset_var_types(self, params=None):
        """Reset variable type tracking, optionally seeding with params."""
        self._var_types = {}
        if params:
            for p in params:
                if p.type:
                    self._var_types[p.name] = self._resolve(p.type)

    # ------------------------------------------------------------------
    # Expression emitter — returns IRExpr nodes
    # ------------------------------------------------------------------
    def _expr(self, e) -> IRExpr:
        from ....ast_nodes import (
            AssignExpr,
            BinaryExpr,
            BoolLiteral,
            CallExpr,
            CastExpr,
            CharLiteral,
            FieldAccessExpr,
            FloatLiteral,
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
            UnaryExpr,
        )

        if isinstance(e, FieldAccessExpr) and isinstance(e.obj, SelfExpr):
            return IRFieldAccess(obj=IRVar(name="self"), field=e.field,
                                 arrow=True)
        if isinstance(e, FieldAccessExpr):
            inner = self._expr(e.obj)
            return IRFieldAccess(obj=inner, field=e.field, arrow=True)
        if isinstance(e, IndexExpr):
            return IRIndex(obj=self._expr(e.obj),
                           index=self._expr(e.index))
        if isinstance(e, Identifier):
            return IRVar(name=e.name)
        if isinstance(e, IntLiteral):
            return IRLiteral(text=str(e.value))
        if isinstance(e, FloatLiteral):
            return IRLiteral(text=e.raw)
        if isinstance(e, BoolLiteral):
            return IRLiteral(text="true" if e.value else "false")
        if isinstance(e, NullLiteral):
            return IRLiteral(text="NULL")
        if isinstance(e, StringLiteral):
            return IRLiteral(text=e.value)  # already includes quotes
        if isinstance(e, CharLiteral):
            return IRLiteral(text=e.value)  # already includes quotes
        if isinstance(e, UnaryExpr):
            operand = self._expr(e.operand)
            return IRUnaryOp(op=e.op, operand=operand, prefix=e.prefix)
        if isinstance(e, BinaryExpr):
            return IRBinOp(left=self._expr(e.left), op=e.op,
                           right=self._expr(e.right))
        if isinstance(e, TernaryExpr):
            return IRTernary(condition=self._expr(e.condition),
                             true_expr=self._expr(e.true_expr),
                             false_expr=self._expr(e.false_expr))
        if isinstance(e, CastExpr):
            resolved = self.resolve_c(e.target_type)
            return IRCast(target_type=CType(text=resolved),
                          expr=self._expr(e.expr))
        if isinstance(e, SizeofExpr):
            return self._sizeof(e.operand)
        if isinstance(e, CallExpr):
            return self._call(e)
        if isinstance(e, AssignExpr):
            # A collection literal takes its type from the assignment target,
            # e.g. self.items = []  inside Ring<int>  →  btrc_Vector_int_new().
            if isinstance(e.value, (ListLiteral, MapLiteral)):
                target = self._mangle_type(self._resolve_expr_type(e.target))
                if target:
                    return IRBinOp(
                        left=self._expr(e.target), op=e.op,
                        right=self._collection_literal(target, e.value))
            return IRBinOp(left=self._expr(e.target), op=e.op,
                           right=self._expr(e.value))
        if isinstance(e, ListLiteral):
            return self._list_literal(e)
        if isinstance(e, MapLiteral):
            return self._map_literal(e)
        if isinstance(e, NewExpr):
            return self._new_expr(e)
        return IRLiteral(text="0")

    def _sizeof(self, operand) -> IRExpr:
        from ....ast_nodes import SizeofExprOp, SizeofType
        if isinstance(operand, SizeofType):
            return IRSizeof(operand=self.resolve_c(operand.type))
        if isinstance(operand, SizeofExprOp):
            return IRSizeof(operand=_ir_expr_to_text(self._expr(operand.expr)))
        return IRSizeof(operand="int")

    def _collection_literal(self, target: str, lit) -> IRExpr:
        """Build a list/map literal as target_new() (+ target_push/put calls).

        `target` is the mangled collection type the literal flows into (driven
        by the declared/assigned type, not the enclosing class)."""
        from ....ast_nodes import ListLiteral
        ctor = IRCall(callee=f"{target}_new", args=[])
        is_list = isinstance(lit, ListLiteral)
        items = lit.elements if is_list else lit.entries
        if not items:
            return ctor
        tmp = self._fresh_temp("__list" if is_list else "__map")
        stmts = [IRVarDecl(c_type=CType(text=f"{target}*"), name=tmp, init=ctor)]
        if is_list:
            for x in lit.elements:
                stmts.append(IRExprStmt(expr=IRCall(
                    callee=f"{target}_push",
                    args=[IRVar(name=tmp), self._expr(x)])))
        else:
            for entry in lit.entries:
                stmts.append(IRExprStmt(expr=IRCall(
                    callee=f"{target}_put",
                    args=[IRVar(name=tmp), self._expr(entry.key),
                          self._expr(entry.value)])))
        return IRStmtExpr(stmts=stmts, result=IRVar(name=tmp))

    def _list_literal(self, e) -> IRExpr:
        return self._collection_literal(self.mangled, e)

    def _map_literal(self, e) -> IRExpr:
        return self._collection_literal(self.mangled, e)

    def _new_expr(self, e) -> IRExpr:
        """Emit new Type(args) as mangled_new(args)."""
        from ..types import mangle_generic_type
        resolved = self._resolve(e.type)
        if resolved.generic_args:
            mangled = mangle_generic_type(resolved.base,
                                           resolved.generic_args)
        else:
            mangled = resolved.base
        args = [self._expr(a) for a in e.args]
        return IRCall(callee=f"{mangled}_new", args=args)

    def _call(self, e) -> IRExpr:
        from ....ast_nodes import FieldAccessExpr, Identifier, SelfExpr
        args = [self._expr(x) for x in e.args]

        if isinstance(e.callee, Identifier):
            name = e.callee.name
            # Magic calls (__btrc_eq etc.) — emit as-is
            if name in _MAGIC_CALLS:
                return IRCall(callee=name, args=args)
            # Constructor calls: Set(), Map(), etc.
            if self._gen and name in self._gen.analyzed.class_table:
                cls = self._gen.analyzed.class_table[name]
                if cls.generic_params:
                    return IRCall(callee=f"{self.mangled}_new", args=args)
            # Register known runtime helpers
            if self._gen and name in (
                "__btrc_safe_realloc", "__btrc_safe_calloc",
            ):
                self._gen.use_helper(name)
            return IRCall(callee=name, args=args)

        if isinstance(e.callee, FieldAccessExpr):
            if isinstance(e.callee.obj, SelfExpr):
                return IRCall(
                    callee=f"{self.mangled}_{e.callee.field}",
                    args=[IRVar(name="self")] + args)

            # Method call on a typed receiver (a local variable, self.field,
            # etc.): resolve the receiver's type and dispatch to the
            # monomorphized method — e.g. self.items.push(x) inside Ring<int>
            # becomes btrc_Vector_int_push(self->items, x).
            target = self._mangle_type(self._resolve_expr_type(e.callee.obj))
            obj = self._expr(e.callee.obj)
            if target:
                return IRCall(callee=f"{target}_{e.callee.field}",
                              args=[obj] + args)
            # Fallback: bare function name
            return IRCall(callee=e.callee.field, args=[obj] + args)

        return IRCall(callee="/* unknown call */", args=args)
