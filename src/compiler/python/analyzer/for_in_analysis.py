"""For-in binding and iterable ownership analysis."""

from ..ast_nodes import CallExpr, Identifier, TypeExpr


class ForInAnalysisMixin:
    def _analyze_for_in(self, stmt):
        if self._is_range_call(stmt.iterable):
            # Range is a structural counting-loop form, even when a user
            # function named range exists in expression position.
            for arg in stmt.iterable.args:
                self._analyze_expr(arg)
                self._reject_thread_value_escape(
                    arg,
                    "passed as range arguments",
                )
            self.loop_depth += 1
            self.break_depth += 1
            elem_type = TypeExpr(base="int")
            self._push_scope()
            if self._claim_local_binding(
                stmt.var_name,
                "loop variable",
                stmt.line,
                stmt.col,
            ):
                self.scope.define(
                    stmt.var_name,
                    self._local_symbol(
                        stmt.var_name,
                        elem_type,
                        "loop",
                        stmt.line,
                        stmt.col,
                    ),
                )
            self._analyze_nullable_loop_body(stmt.body)
            self._pop_scope()
            self.loop_depth -= 1
            self.break_depth -= 1
            return
        self._analyze_expr(stmt.iterable)
        self.loop_depth += 1
        self.break_depth += 1
        iter_type = self._infer_type(stmt.iterable)
        if iter_type and iter_type.is_array:
            if self._array_target_has_capacity(stmt.iterable, iter_type):
                self.array_iteration_capacity_ids.add(id(stmt.iterable))
            else:
                self._error(
                    "Array for-in iterable has no provable element capacity",
                    stmt.line,
                    stmt.col,
                )
        elem_type = self._get_element_type(iter_type, stmt.line, stmt.col)
        value_type = None
        if stmt.var_name2:
            value_type = self._get_iter_value_type(
                iter_type,
                stmt.line,
                stmt.col,
            )
        if self._contains_thread_storage(elem_type) or self._contains_thread_storage(value_type):
            self._error(
                "for-in loop variables cannot own a Thread handle; declare a fresh local owner inside the loop",
                stmt.line,
                stmt.col,
            )
        class_info = self.class_table.get(iter_type.base) if iter_type else None
        owned_first = bool(class_info and "iterLen" in class_info.methods and "iterGet" in class_info.methods)
        owned_second = bool(owned_first and "iterValueAt" in class_info.methods)
        self._push_scope()
        if elem_type and self._claim_local_binding(
            stmt.var_name,
            "loop variable",
            stmt.line,
            stmt.col,
        ):
            self.scope.define(
                stmt.var_name,
                self._local_symbol(
                    stmt.var_name,
                    elem_type,
                    "loop",
                    stmt.line,
                    stmt.col,
                    owned_storage=owned_first,
                ),
            )
        if (
            stmt.var_name2
            and value_type
            and self._claim_local_binding(
                stmt.var_name2,
                "loop variable",
                stmt.line,
                stmt.col,
            )
        ):
            self.scope.define(
                stmt.var_name2,
                self._local_symbol(
                    stmt.var_name2,
                    value_type,
                    "loop",
                    stmt.line,
                    stmt.col,
                    owned_storage=owned_second,
                ),
            )
        self._analyze_nullable_loop_body(stmt.body)
        self._pop_scope()
        self.loop_depth -= 1
        self.break_depth -= 1

    def _is_range_call(self, expr) -> bool:
        return isinstance(expr, CallExpr) and isinstance(expr.callee, Identifier) and expr.callee.name == "range"


__all__ = ["ForInAnalysisMixin"]
