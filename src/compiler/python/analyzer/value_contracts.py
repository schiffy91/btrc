"""Spawn, thread-handle, and ownership value contracts."""

from ..ast_nodes import (
    CallExpr,
    DeleteStmt,
    FieldAccessExpr,
    Identifier,
    IndexExpr,
    KeepStmt,
    LambdaExpr,
    NullLiteral,
    SpawnExpr,
    TernaryExpr,
)


class ValueContractsMixin:
    _FRESH_THREAD_RESULT_DIAGNOSTIC = (
        "Fresh Thread result must be joined, returned, discarded directly, or bound to a direct Thread<T> owner"
    )

    def _validate_thread_handle_copy(self, target_type, value, line, col) -> bool:
        """Reject aliases to the raw, single-consumer pthread handle."""
        target = self._canonical_type(target_type)
        source = self._canonical_type(self._infer_type(value))
        if (
            target is None
            or target.base != "Thread"
            or source is None
            or source.base != "Thread"
            or not self._thread_copy_source(value)
        ):
            return False
        self._error(
            "Thread handles cannot be copied; transfer a fresh spawn() or function-call result instead",
            line,
            col,
        )
        return True

    def _thread_copy_source(self, value) -> bool:
        if isinstance(value, (SpawnExpr, CallExpr, NullLiteral)):
            return False
        if isinstance(value, TernaryExpr):
            return self._thread_copy_source(value.true_expr) or self._thread_copy_source(value.false_expr)
        return True

    def _is_fresh_thread_result(self, expression) -> bool:
        result_type = self._canonical_type(self._infer_type(expression))
        return bool(result_type and result_type.base == "Thread" and not self._thread_copy_source(expression))

    def _is_thread_value(self, expression) -> bool:
        value_type = self._canonical_type(self._infer_type(expression))
        return bool(value_type and value_type.base == "Thread")

    def _reject_fresh_thread_result(self, expression) -> bool:
        if expression is None or not self._is_fresh_thread_result(expression):
            return False
        self._error(
            self._FRESH_THREAD_RESULT_DIAGNOSTIC,
            expression.line,
            expression.col,
        )
        return True

    def _reject_thread_observation(self, expression) -> bool:
        if expression is None or not self._is_thread_value(expression):
            return False
        if isinstance(expression, Identifier):
            return False
        if self._reject_fresh_thread_result(expression):
            return True
        self._error(
            "Thread-producing expression must be a direct spawn() or Thread-returning call before it can be consumed",
            expression.line,
            expression.col,
        )
        return True

    def _validate_thread_transfer_source(self, expression) -> None:
        if (
            not self._is_thread_value(expression)
            or isinstance(expression, Identifier)
            or self._is_fresh_thread_result(expression)
        ):
            return
        self._error(
            "Thread transfer must use one unique local owner or a direct fresh result",
            expression.line,
            expression.col,
        )

    def _validate_thread_expression_discard(self, expression) -> None:
        if (
            not self._is_thread_value(expression)
            or isinstance(expression, Identifier)
            or self._is_fresh_thread_result(expression)
        ):
            return
        self._error(
            "Only a direct fresh Thread result can be discarded safely",
            expression.line,
            expression.col,
        )

    def _reject_thread_value_escape(self, expression, destination) -> bool:
        if not self._is_thread_value(expression):
            return False
        self._error(
            f"Thread handles cannot be {destination}; join or return the unique owner instead",
            expression.line,
            expression.col,
        )
        return True

    def _validate_thread_join_receiver(self, expression) -> None:
        """Require a receiver whose unique handle is consumed exactly once."""
        callee = expression.callee
        receiver = callee.obj
        consumable = isinstance(receiver, (Identifier, SpawnExpr, CallExpr))
        if isinstance(receiver, TernaryExpr):
            consumable = not self._thread_copy_source(receiver)
        if callee.optional or not consumable:
            self._error(
                "Thread.join() receiver must be a unique local owner or a fresh Thread result",
                expression.line,
                expression.col,
            )

    def _validate_spawn_expr(self, expression):
        callable_type = self._canonical_type(self._infer_type(expression.fn))
        if not isinstance(expression.fn, LambdaExpr) and not (callable_type and callable_type.base == "__fn_ptr"):
            self._error("spawn expects a lambda or function pointer", expression.line, expression.col)
        elif not isinstance(expression.fn, LambdaExpr) and self._captures_environment(expression.fn):
            self._error(
                "A capturing lambda alias cannot be spawned; pass the lambda literal directly",
                expression.line,
                expression.col,
            )
        elif not isinstance(expression.fn, LambdaExpr) and not self._is_pthread_entry_type(callable_type):
            self._error(
                "Non-lambda spawn requires __fn_ptr<void*, void*>; use a lambda adapter for other signatures",
                expression.line,
                expression.col,
            )
        if isinstance(expression.fn, LambdaExpr):
            self._validate_spawn_captures(expression)

    def _validate_spawn_captures(self, expression) -> None:
        for capture in expression.fn.captures:
            capture_type = self._canonical_type(capture.type)
            if (capture_type and capture_type.is_array) or self._thread_result_contains_unsized_array(capture.type):
                self._error(
                    f"spawn cannot capture array storage through '{capture.name}'; "
                    "copy it into a scalar-only struct or managed collection",
                    expression.line,
                    expression.col,
                )
                continue
            if not self._is_direct_managed_thread_result(
                capture.type
            ) and self._thread_result_aggregate_contains_managed_reference(capture.type):
                self._error(
                    f"spawn cannot capture shallow aggregate '{capture.name}' "
                    "containing string or class references; capture managed values directly",
                    expression.line,
                    expression.col,
                )

    @classmethod
    def _is_pthread_entry_type(cls, callable_type):
        arguments = callable_type.generic_args if callable_type else []
        return bool(
            callable_type
            and callable_type.base == "__fn_ptr"
            and len(arguments) == 2
            and cls._is_void_pointer(arguments[0])
            and cls._is_void_pointer(arguments[1])
        )

    @staticmethod
    def _is_void_pointer(type_expr):
        return bool(
            type_expr
            and type_expr.base == "void"
            and type_expr.pointer_depth == 1
            and not type_expr.is_array
            and not type_expr.generic_args
        )

    def _validate_ownership_operand(self, statement):
        expression = statement.expr
        operand_type = self._canonical_type(self._infer_type(expression))
        if not self._is_lvalue(expression):
            self._error("Ownership operation requires an assignable value", statement.line, statement.col)
            return
        if isinstance(statement, DeleteStmt):
            operation = "delete"
        elif isinstance(statement, KeepStmt):
            operation = "keep"
        else:
            operation = "release"
        indirect = (isinstance(expression, FieldAccessExpr) and self._is_property_projection(expression)) or (
            isinstance(expression, IndexExpr) and self._is_protocol_index_projection(expression)
        )
        if not isinstance(statement, KeepStmt) and indirect:
            self._error(
                f"{operation} cannot target a property or protocol index; store it in a direct lvalue first",
                statement.line,
                statement.col,
            )
            return
        if not isinstance(statement, KeepStmt) and not self._is_lifetime_stable_storage(expression):
            self._error(
                f"{operation} requires storage rooted in a stable owner; bind temporary owners to a local first",
                statement.line,
                statement.col,
            )
            return
        if not isinstance(statement, KeepStmt) and not self._validate_mutable_target(
            expression, statement.line, statement.col
        ):
            return
        if operand_type and operand_type.base in {"Mutex", "Thread"}:
            self._error(
                f"{operation} is not valid for type '{self._format_type(operand_type)}'",
                statement.line,
                statement.col,
            )
            return
        if operand_type and operand_type.base not in self.class_table and not operand_type.generic_args:
            type_params = set(
                (self.current_class.generic_params if self.current_class else [])
                + (self.current_method.generic_params if self.current_method else [])
            )
            if operand_type.base in type_params:
                return
            self._error(
                f"Ownership operation is not valid for '{self._format_type(operand_type)}'",
                statement.line,
                statement.col,
            )
