"""Semantic contracts for indexed reads and index operand types."""


class IndexExpressionContractsMixin:
    def _validate_index_expr(self, expression):
        from ..index_protocol import indexed_protocol

        object_type = self._canonical_type(self._infer_type(expression.obj))
        index_type = self._infer_type(expression.index)
        if object_type is None:
            return
        if object_type.base == "Tuple":
            self.context.error(
                "Tuple values are not dynamically indexable; use ._N fields",
                expression.line,
                expression.col,
            )
            return
        expected_index = None
        if object_type.base == "Map" and len(object_type.generic_args) == 2:
            expected_index = object_type.generic_args[0]
        protocol = indexed_protocol(
            object_type,
            self.declarations.class_table,
            active_type_params=self._active_storage_type_parameters(),
        )
        if expected_index is None and protocol is not None:
            assigning = self._assignment_target_depth > 0
            # Mutation validation checks the exact getter/setter operations.
            # Reads alone consume the getter contract here.
            method = None if assigning else protocol.getter
            if method is not None:
                expected_index = method.params[0].type
                if object_type.generic_args:
                    substitutions = protocol.substitutions(object_type)
                    expected_index = self._substitute_type(expected_index, substitutions)
            if not assigning and protocol.getter is None:
                self.context.error(
                    f"Type '{self._format_type(object_type)}' has no indexed getter; "
                    "indexing requires an instance get(index) method",
                    expression.line,
                    expression.col,
                )
            elif not assigning:
                self._validate_indexed_method_access(
                    protocol,
                    protocol.getter,
                    expression.line,
                    expression.col,
                )

        integral_index = (
            object_type.base in ("string", "Vector", "List", "Array")
            or self._is_raw_pointer_value(object_type)
            or object_type.is_array
        )
        if expected_index is not None and index_type:
            if not self._types_compatible(expected_index, index_type):
                self.context.error(
                    f"Index expression expects "
                    f"'{self._format_type(expected_index)}' but got "
                    f"'{self._format_type(index_type)}'",
                    expression.index.line,
                    expression.index.col,
                )
        elif integral_index and index_type and not self._is_integral_value(index_type):
            self.context.error(
                "Index expression must have an integral type",
                expression.index.line,
                expression.index.col,
            )

        indexable = expected_index is not None or integral_index or protocol is not None
        if not indexable:
            if object_type.base in self.declarations.class_table:
                self.context.error(
                    f"Type '{self._format_type(object_type)}' has no indexed getter; "
                    "indexing requires an instance get(index) method",
                    expression.line,
                    expression.col,
                )
            else:
                self.context.error(
                    f"Type '{self._format_type(object_type)}' is not indexable",
                    expression.line,
                    expression.col,
                )


__all__ = ["IndexExpressionContractsMixin"]
