"""Statement analysis: block, dispatch, var_decl, for loops, control flow."""

from ..ast_nodes import (
    Block, BreakStmt, CallExpr, CForStmt, ContinueStmt, DeleteStmt,
    DoWhileStmt, ElseBlock, ElseIf, ExprStmt, ForInStmt, ForInitExpr,
    ForInitVar, Identifier, IfStmt, KeepStmt, ListLiteral, MapLiteral,
    ParallelForStmt, ReleaseStmt, ReturnStmt, SwitchStmt, ThrowStmt,
    TryCatchStmt, TypeExpr, VarDeclStmt, WhileStmt,
)
from .core import SymbolInfo


class StatementsMixin:

    def _analyze_block(self, block):
        if block is None:
            return
        self._push_scope()
        found_terminal = False
        for stmt in block.statements:
            if found_terminal:
                line = getattr(stmt, 'line', 0)
                col = getattr(stmt, 'col', 0)
                self._error("Unreachable code after return/throw/break/continue", line, col)
                break
            self._analyze_stmt(stmt)
            if isinstance(stmt, (ReturnStmt, BreakStmt, ContinueStmt, ThrowStmt)):
                found_terminal = True
        self._pop_scope()

    def _analyze_stmt(self, stmt):
        if isinstance(stmt, VarDeclStmt):
            self._analyze_var_decl(stmt)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                self._analyze_expr(stmt.value)
                if self.current_return_type and self.current_return_type.base != "void":
                    ret_type = self._infer_type(stmt.value)
                    if ret_type and not self._types_compatible(self.current_return_type, ret_type):
                        self._error(
                            f"Return type mismatch: expected "
                            f"'{self._format_type(self.current_return_type)}' "
                            f"but got '{self._format_type(ret_type)}'",
                            stmt.line, stmt.col)
        elif isinstance(stmt, IfStmt):
            self._analyze_expr(stmt.condition)
            self._analyze_block(stmt.then_block)
            if isinstance(stmt.else_block, ElseIf):
                self._analyze_stmt(stmt.else_block.if_stmt)
            elif isinstance(stmt.else_block, ElseBlock):
                self._analyze_block(stmt.else_block.body)
        elif isinstance(stmt, WhileStmt):
            self._analyze_expr(stmt.condition)
            self.loop_depth += 1
            self.break_depth += 1
            self._analyze_block(stmt.body)
            self.loop_depth -= 1
            self.break_depth -= 1
        elif isinstance(stmt, DoWhileStmt):
            self.loop_depth += 1
            self.break_depth += 1
            self._analyze_block(stmt.body)
            self.loop_depth -= 1
            self.break_depth -= 1
            self._analyze_expr(stmt.condition)
        elif isinstance(stmt, ForInStmt):
            self._analyze_for_in(stmt)
        elif isinstance(stmt, ParallelForStmt):
            self._analyze_parallel_for(stmt)
        elif isinstance(stmt, CForStmt):
            self._analyze_c_for(stmt)
        elif isinstance(stmt, SwitchStmt):
            self._analyze_switch(stmt)
        elif isinstance(stmt, ExprStmt):
            self._analyze_expr(stmt.expr)
        elif isinstance(stmt, DeleteStmt):
            self._analyze_expr(stmt.expr)
        elif isinstance(stmt, Block):
            self._analyze_block(stmt)
        elif isinstance(stmt, TryCatchStmt):
            self._analyze_block(stmt.try_block)
            self._push_scope()
            self.scope.define(stmt.catch_var,
                              SymbolInfo(stmt.catch_var, TypeExpr(base="string"), "variable"))
            self._analyze_block(stmt.catch_block)
            self._pop_scope()
        elif isinstance(stmt, ThrowStmt):
            self._analyze_expr(stmt.expr)
        elif isinstance(stmt, KeepStmt):
            self._analyze_expr(stmt.expr)
        elif isinstance(stmt, ReleaseStmt):
            self._analyze_expr(stmt.expr)
        elif isinstance(stmt, BreakStmt):
            if self.break_depth == 0:
                self._error("'break' statement outside of loop or switch", stmt.line, stmt.col)
        elif isinstance(stmt, ContinueStmt):
            if self.loop_depth == 0:
                self._error("'continue' statement outside of loop", stmt.line, stmt.col)

    def _analyze_switch(self, stmt):
        self._analyze_expr(stmt.value)
        self.break_depth += 1
        has_default = False
        for case in stmt.cases:
            if case.value:
                self._analyze_expr(case.value)
            else:
                has_default = True
            for s in case.body:
                self._analyze_stmt(s)
        self.break_depth -= 1
        if not has_default:
            val_type = self._infer_type(stmt.value)
            if val_type and val_type.base in self.enum_table:
                enum_values = set(self.enum_table[val_type.base])
                covered = set()
                for case in stmt.cases:
                    if case.value and isinstance(case.value, Identifier):
                        covered.add(case.value.name)
                missing = enum_values - covered
                if missing:
                    names = ", ".join(sorted(missing))
                    self._error(
                        f"Switch on enum '{val_type.base}' is not exhaustive, "
                        f"missing: {names}",
                        getattr(stmt, 'line', 0), getattr(stmt, 'col', 0))

    def _analyze_var_decl(self, stmt):
        if stmt.type is None:
            if stmt.initializer is None:
                self._error(f"'var' declaration of '{stmt.name}' requires an initializer",
                            stmt.line, stmt.col)
                stmt.type = TypeExpr(base="int")
                self.scope.define(stmt.name, SymbolInfo(stmt.name, stmt.type, "variable"))
                return
            else:
                self._analyze_expr(stmt.initializer)
                inferred = self._infer_type(stmt.initializer)
                if inferred is None:
                    self._error(f"Cannot infer type for 'var' declaration of '{stmt.name}'",
                                stmt.line, stmt.col)
                    stmt.type = TypeExpr(base="int")
                    self.scope.define(stmt.name, SymbolInfo(stmt.name, stmt.type, "variable"))
                    return
                else:
                    stmt.type = inferred
                if stmt.type.base in self.class_table and stmt.type.pointer_depth == 0:
                    stmt.type = self._upgrade_class_type(stmt.type)
                # ARC aliasing warning: var q = p where p is a managed class-type var
                self._check_alias_warning(stmt)
                self._collect_generic_instances(stmt.type)
                self.scope.define(stmt.name, SymbolInfo(stmt.name, stmt.type, "variable"))
                return

        stmt.type = self._upgrade_class_type(stmt.type)
        self._collect_generic_instances(stmt.type)
        if stmt.initializer:
            self._analyze_expr(stmt.initializer)
            init_type = self._infer_type(stmt.initializer)
            if init_type and init_type.base == "void" and init_type.pointer_depth == 0:
                self._error(f"Cannot assign void expression to variable '{stmt.name}'",
                            stmt.line, stmt.col)
            elif init_type and stmt.type and not self._types_compatible(stmt.type, init_type):
                is_empty_literal = (
                    (isinstance(stmt.initializer, ListLiteral) and not stmt.initializer.elements)
                    or (isinstance(stmt.initializer, MapLiteral) and not stmt.initializer.entries)
                )
                if not is_empty_literal:
                    self._error(
                        f"Cannot assign '{init_type.base}' to variable '{stmt.name}' "
                        f"of type '{stmt.type.base}'", stmt.line, stmt.col)
        self.scope.define(stmt.name, SymbolInfo(stmt.name, stmt.type, "variable"))

    def _analyze_for_in(self, stmt):
        self._analyze_expr(stmt.iterable)
        self.loop_depth += 1
        self.break_depth += 1
        if self._is_range_call(stmt.iterable):
            elem_type = TypeExpr(base="int")
            self._push_scope()
            self.scope.define(stmt.var_name, SymbolInfo(stmt.var_name, elem_type, "variable"))
            self._analyze_block(stmt.body)
            self._pop_scope()
            self.loop_depth -= 1
            self.break_depth -= 1
            return
        iter_type = self._infer_type(stmt.iterable)
        # Two-variable for-in: class with iterValueAt method and 2+ generic args
        _has_iter_value = (iter_type and iter_type.generic_args
                          and len(iter_type.generic_args) >= 2
                          and (iter_type.base not in self.class_table
                               or "iterValueAt" in self.class_table[iter_type.base].methods))
        if _has_iter_value:
            key_type = iter_type.generic_args[0]
            val_type = iter_type.generic_args[1]
            self._push_scope()
            self.scope.define(stmt.var_name, SymbolInfo(stmt.var_name, key_type, "variable"))
            if stmt.var_name2:
                self.scope.define(stmt.var_name2, SymbolInfo(stmt.var_name2, val_type, "variable"))
            self._analyze_block(stmt.body)
            self._pop_scope()
            self.loop_depth -= 1
            self.break_depth -= 1
            return
        if stmt.var_name2:
            self._error(f"Two-variable for-in iteration requires a Map type, got '{iter_type}'",
                        stmt.line, stmt.col)
        elem_type = self._get_element_type(iter_type, stmt.line, stmt.col)
        self._push_scope()
        if elem_type:
            self.scope.define(stmt.var_name, SymbolInfo(stmt.var_name, elem_type, "variable"))
        self._analyze_block(stmt.body)
        self._pop_scope()
        self.loop_depth -= 1
        self.break_depth -= 1

    def _is_range_call(self, expr) -> bool:
        return (isinstance(expr, CallExpr) and
                isinstance(expr.callee, Identifier) and
                expr.callee.name == "range")

    def _analyze_parallel_for(self, stmt):
        self._analyze_expr(stmt.iterable)
        iter_type = self._infer_type(stmt.iterable)
        elem_type = self._get_element_type(iter_type, stmt.line, stmt.col)
        self.loop_depth += 1
        self.break_depth += 1
        self._push_scope()
        if elem_type:
            self.scope.define(stmt.var_name, SymbolInfo(stmt.var_name, elem_type, "variable"))
        self._analyze_block(stmt.body)
        self._pop_scope()
        self.loop_depth -= 1
        self.break_depth -= 1

    def _analyze_c_for(self, stmt):
        self._push_scope()
        if stmt.init:
            if isinstance(stmt.init, ForInitVar):
                self._analyze_var_decl(stmt.init.var_decl)
            elif isinstance(stmt.init, ForInitExpr):
                self._analyze_expr(stmt.init.expression)
        if stmt.condition:
            self._analyze_expr(stmt.condition)
        if stmt.update:
            self._analyze_expr(stmt.update)
        self.loop_depth += 1
        self.break_depth += 1
        self._analyze_block(stmt.body)
        self.loop_depth -= 1
        self.break_depth -= 1
        self._pop_scope()

    def _check_alias_warning(self, stmt: VarDeclStmt):
        """Warn when a variable is initialized by aliasing a managed class-type var."""
        if not isinstance(stmt.initializer, Identifier):
            return
        src_name = stmt.initializer.name
        src_sym = self.scope.lookup(src_name)
        if not src_sym or not src_sym.type:
            return
        # Only warn for class types (heap-allocated, reference-counted)
        if src_sym.type.base not in self.class_table:
            return
        self._warning(
            f"Aliasing managed variable '{src_name}' — "
            f"'{stmt.name}' shares the same reference without incrementing refcount. "
            f"Use 'keep {stmt.name};' if both variables should own the object",
            stmt.line, stmt.col)
