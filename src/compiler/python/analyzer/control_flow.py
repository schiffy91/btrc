"""Loop/switch analysis and all-path termination checks."""

from ..ast_nodes import (
    Block,
    BoolLiteral,
    BreakStmt,
    CForStmt,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    FieldAccessExpr,
    ForInitExpr,
    ForInitVar,
    ForInStmt,
    Identifier,
    IfStmt,
    ParallelForStmt,
    ReturnStmt,
    SwitchStmt,
    ThrowStmt,
    TryCatchStmt,
    TypeExpr,
    WhileStmt,
)


class ControlFlowAnalysisMixin:
    def _analyze_switch(self, stmt):
        self._analyze_expr(stmt.value)
        before_cases = set(self._nonnull_paths)
        case_flows = []
        self.break_depth += 1
        has_default = False
        for case in stmt.cases:
            if case.value:
                self._analyze_expr(case.value)
            else:
                has_default = True
            case_flows.append(
                self._analyze_flow_branch(
                    (),
                    lambda case=case: self._analyze_switch_case(case),
                )
            )
        self.break_depth -= 1
        self._validate_switch_contract(stmt)
        self._nonnull_paths = before_cases & self._join_nonnull_flows(case_flows)
        if not has_default:
            val_type = self._infer_type(stmt.value)
            if val_type and val_type.base in self.enum_table:
                enum_values = set(self.enum_table[val_type.base])
                covered = set()
                for case in stmt.cases:
                    if case.value:
                        if isinstance(case.value, Identifier):
                            covered.add(case.value.name)
                        elif isinstance(case.value, FieldAccessExpr):
                            covered.add(case.value.field)
                missing = enum_values - covered
                if missing:
                    names = ", ".join(sorted(missing))
                    self._error(
                        f"Switch on enum '{val_type.base}' is not exhaustive, missing: {names}",
                        getattr(stmt, "line", 0),
                        getattr(stmt, "col", 0),
                    )

    def _analyze_switch_case(self, case):
        self._push_scope()
        try:
            self._analyze_statements(case.body)
        finally:
            self._pop_scope()

    def _analyze_parallel_for(self, stmt):
        if self._is_range_call(stmt.iterable):
            # `parallel for` has the same structural range form as ordinary
            # for-in. Its binding is always an int and must be visible while
            # analyzing the body so typed operators do not see an unresolved
            # C identifier later in IR generation.
            for argument in stmt.iterable.args:
                self._analyze_expr(argument)
                self._reject_thread_value_escape(
                    argument,
                    "passed as range arguments",
                )
            elem_type = TypeExpr(base="int")
        else:
            self._analyze_expr(stmt.iterable)
            iter_type = self._infer_type(stmt.iterable)
            elem_type = self._get_element_type(
                iter_type,
                stmt.line,
                stmt.col,
            )
        if self._contains_thread_storage(elem_type):
            self._error(
                "parallel-for variables cannot own a Thread handle",
                stmt.line,
                stmt.col,
            )
        self.loop_depth += 1
        self.break_depth += 1
        self._push_scope()
        if elem_type:
            if self._claim_local_binding(stmt.var_name, "parallel variable", stmt.line, stmt.col):
                self.scope.define(
                    stmt.var_name,
                    self._local_symbol(stmt.var_name, elem_type, "parallel", stmt.line, stmt.col),
                )
        self._analyze_nullable_loop_body(stmt.body)
        self._pop_scope()
        self.loop_depth -= 1
        self.break_depth -= 1

    def _analyze_c_for(self, stmt):
        self._push_scope()
        if stmt.init:
            if isinstance(stmt.init, ForInitVar):
                self._analyze_var_decl(stmt.init.var_decl)
                if self._contains_thread_storage(stmt.init.var_decl.type):
                    self._error(
                        "C-style for initializer cannot own a Thread handle; declare it before the loop",
                        stmt.init.var_decl.line,
                        stmt.init.var_decl.col,
                    )
            elif isinstance(stmt.init, ForInitExpr):
                self._analyze_expr(stmt.init.expression)
                self._reject_thread_observation(stmt.init.expression)
        if stmt.condition:
            self._analyze_expr(stmt.condition)
            self._reject_thread_observation(stmt.condition)
        self.loop_depth += 1
        self.break_depth += 1
        body_facts = self._nonnull_facts_for_outcome(stmt.condition, True) if stmt.condition is not None else set()
        before_iteration = set(self._nonnull_paths)
        iteration_flow = self._analyze_flow_branch(
            body_facts,
            lambda: self._analyze_c_for_iteration(stmt),
        )
        # A C-for may execute zero times. Facts learned only in its body/update
        # cannot escape; mutations that occur in a possible iteration do.
        self._nonnull_paths = before_iteration & iteration_flow
        self.loop_depth -= 1
        self.break_depth -= 1
        self._pop_scope()

    def _analyze_c_for_iteration(self, statement) -> None:
        self._analyze_block(statement.body)
        if statement.update:
            self._analyze_expr(statement.update)
            self._reject_thread_observation(statement.update)

    def _block_must_terminate(self, block) -> bool:
        """Whether every path through a block returns or throws."""
        if block is None:
            return False
        return any(self._statement_must_terminate(statement) for statement in block.statements)

    def _statement_must_terminate(self, statement) -> bool:
        if isinstance(statement, (ReturnStmt, ThrowStmt)):
            return True
        if isinstance(statement, Block):
            return self._block_must_terminate(statement)
        if isinstance(statement, IfStmt):
            if not self._block_must_terminate(statement.then_block):
                return False
            if isinstance(statement.else_block, ElseBlock):
                return self._block_must_terminate(statement.else_block.body)
            if isinstance(statement.else_block, ElseIf):
                return self._statement_must_terminate(statement.else_block.if_stmt)
            return False
        if isinstance(statement, SwitchStmt):
            return (
                bool(statement.cases)
                and any(case.value is None for case in statement.cases)
                and all(self._statement_sequence_must_terminate(case.body) for case in statement.cases)
            )
        if isinstance(statement, TryCatchStmt):
            if self._block_must_terminate(statement.finally_block):
                return True
            try_terminates = self._block_must_terminate(statement.try_block)
            if statement.catch_block is None:
                return try_terminates
            return try_terminates and self._block_must_terminate(statement.catch_block)
        if isinstance(statement, WhileStmt):
            return (
                isinstance(statement.condition, BoolLiteral)
                and statement.condition.value
                and not self._contains_loop_break(statement.body)
                and self._block_must_terminate(statement.body)
            )
        if isinstance(statement, DoWhileStmt):
            return not self._contains_loop_break(statement.body) and self._block_must_terminate(statement.body)
        if isinstance(statement, CForStmt):
            return (
                statement.condition is None
                and not self._contains_loop_break(statement.body)
                and self._block_must_terminate(statement.body)
            )
        # for-in may execute zero times; no return inside it is guaranteed.
        return False

    def _statement_sequence_must_terminate(self, statements) -> bool:
        return any(self._statement_must_terminate(statement) for statement in statements)

    def _contains_loop_break(self, node) -> bool:
        """Find a break targeting this loop, ignoring nested loop/switch scopes."""
        if node is None:
            return False
        if isinstance(node, BreakStmt):
            return True
        if isinstance(node, (WhileStmt, DoWhileStmt, CForStmt, ForInStmt, ParallelForStmt, SwitchStmt)):
            return False
        if isinstance(node, Block):
            return any(self._contains_loop_break(statement) for statement in node.statements)
        if isinstance(node, IfStmt):
            if self._contains_loop_break(node.then_block):
                return True
            if isinstance(node.else_block, ElseBlock):
                return self._contains_loop_break(node.else_block.body)
            if isinstance(node.else_block, ElseIf):
                return self._contains_loop_break(node.else_block.if_stmt)
        if isinstance(node, TryCatchStmt):
            return any(
                self._contains_loop_break(child) for child in (node.try_block, node.catch_block, node.finally_block)
            )
        return False
