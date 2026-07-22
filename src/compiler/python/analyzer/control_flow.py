"""Loop/switch analysis and all-path termination checks."""

from ..ast_nodes import (
    FieldAccessExpr,
    ForInitExpr,
    ForInitVar,
    Identifier,
    TypeExpr,
)
from ..control_termination import (
    block_must_terminate,
    contains_loop_break,
    statement_must_terminate,
    statement_sequence_must_terminate,
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
            if val_type and val_type.base in self.declarations.enum_table:
                enum_values = set(self.declarations.enum_table[val_type.base])
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
                    self.context.error(
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
            self.context.error(
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
                declaration = stmt.init.var_decl
                self._analyze_var_decl(declaration)
                if declaration.type and (declaration.type.is_static or declaration.type.is_extern):
                    self.context.error(
                        "C-style for initializer cannot use static or extern storage",
                        declaration.line,
                        declaration.col,
                    )
                if declaration.type and declaration.type.is_array:
                    self.context.error(
                        "C-style for initializer cannot declare an array",
                        declaration.line,
                        declaration.col,
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
        return block_must_terminate(block)

    def _statement_must_terminate(self, statement) -> bool:
        return statement_must_terminate(statement)

    def _statement_sequence_must_terminate(self, statements) -> bool:
        return statement_sequence_must_terminate(statements)

    def _contains_loop_break(self, node) -> bool:
        return contains_loop_break(node)
