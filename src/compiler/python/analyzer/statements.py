"""Statement analysis: block, dispatch, var_decl, for loops, control flow."""

from ..ast_nodes import (
    Block,
    BreakStmt,
    CForStmt,
    ContinueStmt,
    DeleteStmt,
    DoWhileStmt,
    ExprStmt,
    ForInStmt,
    IfStmt,
    KeepStmt,
    ParallelForStmt,
    ReleaseStmt,
    ReturnStmt,
    SwitchStmt,
    ThrowStmt,
    TryCatchStmt,
    VarDeclStmt,
    WhileStmt,
)


class StatementsMixin:
    def _analyze_block(self, block):
        if block is None:
            return
        self._push_scope()
        self._analyze_statement_sequence(block)
        self._pop_scope()

    def _analyze_root_block(self, block):
        """Analyze a callable body in the same scope as its parameters."""
        if block is not None:
            self._analyze_statement_sequence(block)

    def _analyze_statement_sequence(self, block):
        self._analyze_statements(block.statements)

    def _analyze_statements(self, statements):
        found_terminal = False
        outer_previous = self._previous_statement
        self._previous_statement = None
        try:
            for stmt in statements:
                if found_terminal:
                    line = getattr(stmt, "line", 0)
                    col = getattr(stmt, "col", 0)
                    self._error("Unreachable code after return/throw/break/continue", line, col)
                    break
                self._analyze_stmt(stmt)
                self._previous_statement = stmt
                if isinstance(stmt, (ReturnStmt, BreakStmt, ContinueStmt, ThrowStmt)):
                    found_terminal = True
        finally:
            self._previous_statement = outer_previous

    def _analyze_stmt(self, stmt):
        if isinstance(stmt, VarDeclStmt):
            self._analyze_var_decl(stmt)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                self._contextualize_generic_constructor(self.current_return_type, stmt.value)
                self._analyze_expr(stmt.value)
                self._validate_thread_transfer_source(stmt.value)
                if self.current_return_type:
                    self._contextualize_aggregate_initializer(
                        self.current_return_type,
                        stmt.value,
                        "Return value",
                        stmt.line,
                        stmt.col,
                    )
                if self._is_nonpointer_void_object(self.current_return_type):
                    self._error("Void function or method cannot return a value", stmt.line, stmt.col)
                elif self.current_return_type:
                    ret_type = self._infer_type(stmt.value)
                    escaping_callable = self._validate_callable_value(
                        self.current_return_type,
                        stmt.value,
                        stmt.line,
                        stmt.col,
                    )
                    if (
                        not escaping_callable
                        and ret_type
                        and not self._return_type_compatible(self.current_return_type, ret_type)
                    ):
                        self._error(
                            f"Return type mismatch: expected "
                            f"'{self._format_type(self.current_return_type)}' "
                            f"but got '{self._format_type(ret_type)}'",
                            stmt.line,
                            stmt.col,
                        )
            elif self.current_return_type and not self._is_nonpointer_void_object(self.current_return_type):
                self._error(
                    f"Non-void function or method must return '{self._format_type(self.current_return_type)}'",
                    stmt.line,
                    stmt.col,
                )
        elif isinstance(stmt, IfStmt):
            self._analyze_nullable_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._analyze_nullable_while(stmt)
        elif isinstance(stmt, DoWhileStmt):
            self.loop_depth += 1
            self.break_depth += 1
            self._analyze_nullable_loop_body(stmt.body)
            self.loop_depth -= 1
            self.break_depth -= 1
            self._analyze_expr(stmt.condition)
            self._reject_thread_observation(stmt.condition)
        elif isinstance(stmt, ForInStmt):
            self._analyze_for_in(stmt)
        elif isinstance(stmt, ParallelForStmt):
            self._analyze_parallel_for(stmt)
        elif isinstance(stmt, CForStmt):
            self._analyze_c_for(stmt)
        elif isinstance(stmt, SwitchStmt):
            self._analyze_switch(stmt)
        elif isinstance(stmt, ExprStmt):
            previous_root = self._standalone_expression_root
            self._standalone_expression_root = stmt.expr
            try:
                self._analyze_expr(stmt.expr)
            finally:
                self._standalone_expression_root = previous_root
            self._validate_thread_expression_discard(stmt.expr)
        elif isinstance(stmt, DeleteStmt):
            self._analyze_expr(stmt.expr)
            self._validate_ownership_operand(stmt)
        elif isinstance(stmt, Block):
            self._analyze_block(stmt)
        elif isinstance(stmt, TryCatchStmt):
            self._analyze_try_catch(stmt)
        elif isinstance(stmt, (ThrowStmt, KeepStmt, ReleaseStmt)):
            self._analyze_expr(stmt.expr)
            if isinstance(stmt, ThrowStmt):
                self._reject_thread_observation(stmt.expr)
            if isinstance(stmt, (KeepStmt, ReleaseStmt)):
                self._validate_ownership_operand(stmt)
        elif isinstance(stmt, BreakStmt):
            if self.break_depth == 0:
                self._error("'break' statement outside of loop or switch", stmt.line, stmt.col)
        elif isinstance(stmt, ContinueStmt):
            if self.loop_depth == 0:
                self._error("'continue' statement outside of loop", stmt.line, stmt.col)

    def _return_type_compatible(self, expected, actual) -> bool:
        if (
            self.in_gpu_function
            and expected.is_array
            and expected.base == actual.base
            and actual.pointer_depth == 0
            and not actual.generic_args
        ):
            # An array-returning kernel may either return the destination
            # buffer or one element for the current gpu_id invocation.
            return True
        return self._types_compatible(expected, actual)
