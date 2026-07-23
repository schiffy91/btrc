"""Semantic contracts for protocol-based indexed mutation."""

from ..ast_nodes import IndexExpr


class IndexedUpdateContractsMixin:
    def _validate_indexed_update(
        self,
        target,
        *,
        require_getter,
        value,
        line,
        col,
    ) -> None:
        if not isinstance(target, IndexExpr):
            return
        receiver_type = self._infer_type(target.obj)
        protocol = self.index_protocols.resolve(
            receiver_type,
            active_type_params=self._active_storage_type_parameters(),
        )
        if protocol is None:
            return
        setter = protocol.setter
        getter = protocol.getter
        if setter is None:
            self.context.error(
                f"Type '{self._format_type(receiver_type)}' has no indexed setter; "
                "it has no void instance set(index, value) method",
                line,
                col,
            )
        if require_getter and getter is None:
            self.context.error(
                f"Type '{self._format_type(receiver_type)}' has no indexed getter; "
                "indexing requires an instance get(index) method",
                line,
                col,
            )
        if setter is None or (require_getter and getter is None):
            return
        self._validate_indexed_method_access(protocol, setter, line, col)
        if require_getter:
            self._validate_indexed_method_access(protocol, getter, line, col)

        substitutions = protocol.substitutions(receiver_type)
        actual_index = self._infer_type(target.index)
        methods = (getter, setter) if require_getter else (setter,)
        for method in methods:
            expected_index = self._substitute_type(
                method.params[0].type,
                substitutions,
            )
            if actual_index is not None and not self._types_compatible(
                expected_index,
                actual_index,
            ):
                self.context.error(
                    f"Indexed {method.name} expects index type "
                    f"'{self._format_type(expected_index)}' but got "
                    f"'{self._format_type(actual_index)}'",
                    target.index.line,
                    target.index.col,
                )

        expected_value = self._substitute_type(
            setter.params[1].type,
            substitutions,
        )
        if require_getter:
            actual_value = self._substitute_type(getter.return_type, substitutions)
        else:
            actual_value = self._infer_type(value)
            self._record_node_type(target, expected_value)
        if actual_value is not None and not self._types_compatible(
            expected_value,
            actual_value,
        ):
            self.context.error(
                f"Indexed setter expects value type "
                f"'{self._format_type(expected_value)}' but got "
                f"'{self._format_type(actual_value)}'",
                line,
                col,
            )

    def _validate_indexed_method_access(self, protocol, method, line, col) -> None:
        if method is None or method.access != "private":
            return
        owner = protocol.class_info.method_owners.get(
            method.name,
            protocol.class_info.name,
        )
        if self.current_class is None or self.current_class.name != owner:
            self.context.error(
                f"Cannot access private indexed method '{method.name}' of class '{owner}'",
                line,
                col,
            )


__all__ = ["IndexedUpdateContractsMixin"]
