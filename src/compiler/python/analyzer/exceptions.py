"""Exception statement analysis and nullable-flow joins."""

from ..ast_nodes import TypeExpr


class ExceptionAnalysisMixin:
    def _analyze_try_catch(self, statement) -> None:
        before_try = set(self._nonnull_paths)
        try_flow = self._analyze_flow_branch(
            (),
            lambda: self._analyze_block(statement.try_block),
        )

        catch_flow = None
        if statement.catch_block is not None:
            catch_flow = self._analyze_flow_branch(
                (),
                lambda: self._analyze_catch_body(statement),
            )

        if statement.finally_block is not None:
            finally_inputs = [try_flow]
            # An uncaught exception may enter finally before any fact learned
            # in the try body. A catch likewise starts from the pre-try state.
            finally_inputs.append(catch_flow if catch_flow is not None else before_try)
            self._nonnull_paths = self._join_nonnull_flows(finally_inputs)
            self._analyze_block(statement.finally_block)
            return

        continuing_flows = []
        if not self._block_stops_fallthrough(statement.try_block):
            continuing_flows.append(try_flow)
        if catch_flow is not None and not self._block_stops_fallthrough(statement.catch_block):
            continuing_flows.append(catch_flow)
        self._nonnull_paths = self._join_nonnull_flows(continuing_flows)

    def _analyze_catch_body(self, statement) -> None:
        self._push_scope()
        try:
            catch_type = statement.catch_type
            if catch_type is not None:
                catch_type = self._upgrade_class_type(catch_type)
                self._collect_generic_instances(catch_type)
                self._record_node_type(statement, catch_type)
                if not (catch_type.base == "string" and catch_type.pointer_depth == 0):
                    self._error(
                        f"Catch type '{catch_type.base}' is not supported — "
                        "exceptions carry a string message; "
                        f"use 'string {statement.catch_var}' or an untyped "
                        "catch",
                        getattr(catch_type, "line", statement.line),
                        getattr(catch_type, "col", statement.col),
                    )
            if self._claim_local_binding(
                statement.catch_var,
                "catch variable",
                statement.line,
                statement.col,
            ):
                self.scope.define(
                    statement.catch_var,
                    self._local_symbol(
                        statement.catch_var,
                        TypeExpr(base="string"),
                        "catch",
                        statement.line,
                        statement.col,
                        owned_storage=True,
                    ),
                )
            self._analyze_root_block(statement.catch_block)
        finally:
            self._pop_scope()
