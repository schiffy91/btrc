"""Mini AST-to-C emitter for user-defined generic method bodies."""

from __future__ import annotations
from typing import TYPE_CHECKING

from .core import _resolve_type

if TYPE_CHECKING:
    from ..generator import IRGenerator

# Magic identifiers — emitted as-is (resolved by C11 _Generic macros).
_MAGIC_CALLS = {"__btrc_eq", "__btrc_lt", "__btrc_gt", "__btrc_hash"}


class _UserGenericEmitter:
    """Emits C code from AST nodes within a monomorphized generic class."""

    def __init__(self, type_map, mangled, type_to_c_fn, *,
                 gen=None):
        self.type_map = type_map
        self.mangled = mangled
        self._ttc = type_to_c_fn
        self._gen = gen
        # Track variable types for cross-type method call mangling
        self._var_types = {}

    def resolve_c(self, t):
        return self._ttc(_resolve_type(t, self.type_map))

    def _resolve(self, t):
        """Resolve a TypeExpr through the type map."""
        return _resolve_type(t, self.type_map)

    def emit_stmts(self, stmts, indent="    "):
        return "".join(self._stmt(s, indent) for s in stmts)

    def reset_var_types(self, params=None):
        """Reset variable type tracking, optionally seeding with params."""
        self._var_types = {}
        if params:
            for p in params:
                if p.type:
                    self._var_types[p.name] = self._resolve(p.type)

    # ------------------------------------------------------------------
    # Expression emitter
    # ------------------------------------------------------------------
    def _expr(self, e) -> str:
        from ....ast_nodes import (
            FieldAccessExpr, SelfExpr, Identifier, IntLiteral, FloatLiteral,
            BoolLiteral, NullLiteral, StringLiteral, CharLiteral,
            UnaryExpr, BinaryExpr, TernaryExpr, CallExpr, AssignExpr,
            IndexExpr, CastExpr, SizeofExpr, ListLiteral, MapLiteral,
            NewExpr,
        )

        if isinstance(e, FieldAccessExpr) and isinstance(e.obj, SelfExpr):
            return f"self->{e.field}"
        if isinstance(e, FieldAccessExpr):
            inner = self._expr(e.obj)
            return f"{inner}->{e.field}"
        if isinstance(e, IndexExpr):
            return f"{self._expr(e.obj)}[{self._expr(e.index)}]"
        if isinstance(e, Identifier):
            return e.name
        if isinstance(e, IntLiteral):
            return str(e.value)
        if isinstance(e, FloatLiteral):
            return e.raw
        if isinstance(e, BoolLiteral):
            return "true" if e.value else "false"
        if isinstance(e, NullLiteral):
            return "NULL"
        if isinstance(e, StringLiteral):
            return e.value  # already includes quotes
        if isinstance(e, CharLiteral):
            return e.value  # already includes quotes
        if isinstance(e, UnaryExpr):
            operand = self._expr(e.operand)
            if e.prefix:
                return f"({e.op}{operand})"
            return f"({operand}{e.op})"
        if isinstance(e, BinaryExpr):
            return f"({self._expr(e.left)} {e.op} {self._expr(e.right)})"
        if isinstance(e, TernaryExpr):
            return (f"({self._expr(e.condition)} ? "
                    f"{self._expr(e.true_expr)} : {self._expr(e.false_expr)})")
        if isinstance(e, CastExpr):
            resolved = self.resolve_c(e.target_type)
            return f"({resolved}){self._expr(e.expr)}"
        if isinstance(e, SizeofExpr):
            return self._sizeof(e.operand)
        if isinstance(e, CallExpr):
            return self._call(e)
        if isinstance(e, AssignExpr):
            return f"{self._expr(e.target)} {e.op} {self._expr(e.value)}"
        if isinstance(e, ListLiteral):
            return self._list_literal(e)
        if isinstance(e, MapLiteral):
            return self._map_literal(e)
        if isinstance(e, NewExpr):
            return self._new_expr(e)
        return "0"

    def _sizeof(self, operand) -> str:
        from ....ast_nodes import SizeofType, SizeofExprOp
        if isinstance(operand, SizeofType):
            return f"sizeof({self.resolve_c(operand.type)})"
        if isinstance(operand, SizeofExprOp):
            return f"sizeof({self._expr(operand.expr)})"
        return "sizeof(int)"

    def _list_literal(self, e) -> str:
        """Emit [] as TYPE_new() + TYPE_push() calls."""
        # Empty list: just TYPE_new() — the variable type determines which
        if not e.elements:
            return f"{self.mangled}_new()"
        # Non-empty: use statement expression
        elems = ", ".join(self._expr(x) for x in e.elements)
        items = "".join(
            f" {self.mangled}_push(__tmp, {self._expr(x)});"
            for x in e.elements
        )
        return (f"({{ {self.mangled}* __tmp = {self.mangled}_new();"
                f"{items} __tmp; }})")

    def _map_literal(self, e) -> str:
        """Emit {} as TYPE_new() + TYPE_put() calls."""
        if not e.entries:
            return f"{self.mangled}_new()"
        items = "".join(
            f" {self.mangled}_put(__tmp, {self._expr(entry.key)},"
            f" {self._expr(entry.value)});"
            for entry in e.entries
        )
        return (f"({{ {self.mangled}* __tmp = {self.mangled}_new();"
                f"{items} __tmp; }})")

    def _new_expr(self, e) -> str:
        """Emit new Type(args) as mangled_new(args)."""
        from ..types import mangle_generic_type
        resolved = self._resolve(e.type)
        if resolved.generic_args:
            mangled = mangle_generic_type(resolved.base, resolved.generic_args)
        else:
            mangled = resolved.base
        args = ", ".join(self._expr(a) for a in e.args)
        return f"{mangled}_new({args})" if args else f"{mangled}_new()"

    def _call(self, e) -> str:
        from ....ast_nodes import Identifier, FieldAccessExpr, SelfExpr
        args = ", ".join(self._expr(x) for x in e.args)

        if isinstance(e.callee, Identifier):
            name = e.callee.name
            # Magic calls (__btrc_eq etc.) — emit as-is, C11 _Generic macros resolve
            if name in _MAGIC_CALLS:
                return f"{name}({args})"
            # Constructor calls: Set(), Map(), etc.
            if self._gen and name in self._gen.analyzed.class_table:
                cls = self._gen.analyzed.class_table[name]
                if cls.generic_params:
                    # Bare constructor call like Set() — mangle with self's
                    # type map (e.g. Set<T> with T=int → btrc_Set_int)
                    return f"{self.mangled}_new()" if not args else f"{self.mangled}_new({args})"
            # Register known runtime helpers
            if self._gen and name in (
                "__btrc_safe_realloc", "__btrc_safe_calloc",
            ):
                self._gen.use_helper(name)
            return f"{name}({args})"

        if isinstance(e.callee, FieldAccessExpr):
            if isinstance(e.callee.obj, SelfExpr):
                if args:
                    return f"{self.mangled}_{e.callee.field}(self, {args})"
                return f"{self.mangled}_{e.callee.field}(self)"

            # Cross-type method call: check if the object has a known type
            obj_name = self._get_obj_name(e.callee.obj)
            if obj_name and obj_name in self._var_types:
                target = self._mangle_for_var(obj_name)
                if target:
                    obj = self._expr(e.callee.obj)
                    if args:
                        return f"{target}_{e.callee.field}({obj}, {args})"
                    return f"{target}_{e.callee.field}({obj})"

            # Fallback: bare function name
            obj = self._expr(e.callee.obj)
            if args:
                return f"{e.callee.field}({obj}, {args})"
            return f"{e.callee.field}({obj})"

        return f"/* unknown call */({args})"

    def _get_obj_name(self, e) -> str | None:
        """Extract variable name from an expression, if it's an Identifier."""
        from ....ast_nodes import Identifier
        if isinstance(e, Identifier):
            return e.name
        return None

    def _mangle_for_var(self, var_name: str) -> str | None:
        """Get the mangled type name for a tracked variable."""
        from ..types import mangle_generic_type
        var_type = self._var_types.get(var_name)
        if var_type and var_type.generic_args:
            return mangle_generic_type(var_type.base, var_type.generic_args)
        return None


    # ------------------------------------------------------------------
    # Statement emitter
    # ------------------------------------------------------------------
    def _stmt(self, s, indent="    ") -> str:
        from ....ast_nodes import (
            ReturnStmt, ExprStmt, IfStmt, Block, VarDeclStmt,
            CForStmt, ForInStmt, WhileStmt, DoWhileStmt,
            BreakStmt, ContinueStmt, DeleteStmt,
            ForInitVar, ForInitExpr,
        )

        if isinstance(s, ReturnStmt):
            if s.value:
                return f"{indent}return {self._expr(s.value)};\n"
            return f"{indent}return;\n"
        if isinstance(s, ExprStmt):
            return f"{indent}{self._expr(s.expr)};\n"
        if isinstance(s, VarDeclStmt):
            return self._var_decl(s, indent)
        if isinstance(s, IfStmt):
            return self._if_stmt(s, indent)
        if isinstance(s, CForStmt):
            return self._cfor_stmt(s, indent)
        if isinstance(s, ForInStmt):
            return self._forin_stmt(s, indent)
        if isinstance(s, WhileStmt):
            return self._while_stmt(s, indent)
        if isinstance(s, DoWhileStmt):
            return self._dowhile_stmt(s, indent)
        if isinstance(s, BreakStmt):
            return f"{indent}break;\n"
        if isinstance(s, ContinueStmt):
            return f"{indent}continue;\n"
        if isinstance(s, DeleteStmt):
            return f"{indent}free({self._expr(s.expr)});\n"
        return f"{indent}/* unhandled stmt */;\n"

    def _var_decl(self, s, indent):
        c_type = self.resolve_c(s.type)
        # Track the resolved type for cross-type method call mangling
        if s.type:
            resolved = self._resolve(s.type)
            self._var_types[s.name] = resolved
        if s.initializer:
            # For list/map literal inits on a known generic type, use that
            # type's mangled constructor instead of self's
            init = self._var_init_expr(s)
            return f"{indent}{c_type} {s.name} = {init};\n"
        return f"{indent}{c_type} {s.name};\n"

    def _var_init_expr(self, s) -> str:
        """Emit the initializer for a variable, handling typed literals."""
        from ....ast_nodes import ListLiteral, MapLiteral
        from ..types import mangle_generic_type

        # If the initializer is a [] or {} literal, and the variable has a
        # known generic type, use that type's mangled constructor
        if s.type and isinstance(s.initializer, (ListLiteral, MapLiteral)):
            resolved = self._resolve(s.type)
            if resolved.generic_args:
                target = mangle_generic_type(resolved.base,
                                             resolved.generic_args)
                if isinstance(s.initializer, ListLiteral):
                    if not s.initializer.elements:
                        return f"{target}_new()"
                    items = "".join(
                        f" {target}_push(__tmp, {self._expr(x)});"
                        for x in s.initializer.elements
                    )
                    return (f"({{ {target}* __tmp = {target}_new();"
                            f"{items} __tmp; }})")
                if isinstance(s.initializer, MapLiteral):
                    if not s.initializer.entries:
                        return f"{target}_new()"
                    items = "".join(
                        f" {target}_put(__tmp, {self._expr(e.key)},"
                        f" {self._expr(e.value)});"
                        for e in s.initializer.entries
                    )
                    return (f"({{ {target}* __tmp = {target}_new();"
                            f"{items} __tmp; }})")
        return self._expr(s.initializer)

    def _if_stmt(self, s, indent):
        from ....ast_nodes import Block, ElseIf, ElseBlock
        txt = f"{indent}if ({self._expr(s.condition)}) {{\n"
        if s.then_block:
            txt += self.emit_stmts(s.then_block.statements, indent + "    ")
        txt += f"{indent}}}"
        if s.else_block:
            eb = s.else_block
            if isinstance(eb, ElseBlock):
                eb = eb.body
            if isinstance(eb, Block):
                txt += f" else {{\n"
                txt += self.emit_stmts(eb.statements, indent + "    ")
                txt += f"{indent}}}"
            elif isinstance(eb, ElseIf):
                txt += f" else {self._if_stmt(eb.if_stmt, indent).lstrip()}"
                return txt
        txt += "\n"
        return txt

    def _cfor_stmt(self, s, indent):
        from ....ast_nodes import ForInitVar, ForInitExpr
        init_str = ""
        if s.init:
            if isinstance(s.init, ForInitVar):
                vd = s.init.var_decl
                c_type = self.resolve_c(vd.type)
                init_str = f"{c_type} {vd.name} = {self._expr(vd.initializer)}"
            elif isinstance(s.init, ForInitExpr):
                init_str = self._expr(s.init.expression)
        cond_str = self._expr(s.condition) if s.condition else ""
        upd_str = self._expr(s.update) if s.update else ""
        txt = f"{indent}for ({init_str}; {cond_str}; {upd_str}) {{\n"
        txt += self.emit_stmts(s.body.statements, indent + "    ")
        txt += f"{indent}}}\n"
        return txt

    def _forin_stmt(self, s, indent):
        from ....ast_nodes import CallExpr, Identifier
        if (isinstance(s.iterable, CallExpr) and
                isinstance(s.iterable.callee, Identifier) and
                s.iterable.callee.name == "range"):
            args = s.iterable.args
            if len(args) == 1:
                n = self._expr(args[0])
                txt = (f"{indent}for (int {s.var_name} = 0; "
                       f"{s.var_name} < {n}; {s.var_name}++) {{\n")
            elif len(args) >= 2:
                start = self._expr(args[0])
                end = self._expr(args[1])
                txt = (f"{indent}for (int {s.var_name} = {start}; "
                       f"{s.var_name} < {end}; {s.var_name}++) {{\n")
            else:
                txt = f"{indent}for (int {s.var_name} = 0; 0; ) {{\n"
            txt += self.emit_stmts(s.body.statements, indent + "    ")
            txt += f"{indent}}}\n"
            return txt
        return f"{indent}/* unhandled for-in */;\n"

    def _while_stmt(self, s, indent):
        txt = f"{indent}while ({self._expr(s.condition)}) {{\n"
        txt += self.emit_stmts(s.body.statements, indent + "    ")
        txt += f"{indent}}}\n"
        return txt

    def _dowhile_stmt(self, s, indent):
        txt = f"{indent}do {{\n"
        txt += self.emit_stmts(s.body.statements, indent + "    ")
        txt += f"{indent}}} while ({self._expr(s.condition)});\n"
        return txt
