"""Storage-duration, array-bound, and class-field contracts."""

from ..ast_nodes import BraceInitializer, CallExpr, Identifier, ListLiteral


class StorageContractsMixin:
    def _validate_variable_storage(self, declaration, *, is_global) -> None:
        type_expr = declaration.type
        if type_expr is None:
            return
        subject = f"Global '{declaration.name}'" if is_global else f"Variable '{declaration.name}'"
        self._validate_declared_type(
            type_expr,
            subject,
            declaration.line,
            declaration.col,
            role="object",
            active_type_params=self._active_storage_type_parameters(),
        )
        canonical = self._canonical_type(type_expr)
        contains_thread = self._contains_thread_storage(type_expr)
        outer = self.scope.parent.lookup(declaration.name) if not is_global and self.scope.parent else None
        if contains_thread and outer is not None:
            self._error(
                f"Thread owner '{declaration.name}' cannot shadow another active binding",
                declaration.line,
                declaration.col,
            )
        if contains_thread and (is_global or bool(canonical and (canonical.is_static or canonical.is_extern))):
            self._error(
                f"{subject} cannot own a Thread handle with static storage; "
                "Thread<T> must be an initialized local owner",
                declaration.line,
                declaration.col,
            )
        elif contains_thread and (canonical is None or canonical.base != "Thread"):
            self._error(
                f"{subject} cannot embed a Thread handle; Thread<T> must be the variable's direct type",
                declaration.line,
                declaration.col,
            )
        elif canonical and canonical.base == "Thread" and declaration.initializer is None and not canonical.is_extern:
            self._error(
                f"{subject} must initialize its Thread<T> owner",
                declaration.line,
                declaration.col,
            )
        if not (type_expr.is_extern and declaration.initializer is None):
            self._validate_complete_aggregate_use(
                type_expr,
                subject,
                declaration.line,
                declaration.col,
            )
        bound_context = "global" if is_global else "static" if type_expr.is_static else "local"
        self._validate_array_bound(type_expr, subject, bound_context)
        if type_expr.is_extern and declaration.initializer is not None:
            self._error(
                f"{subject} cannot have an initializer with extern storage",
                declaration.line,
                declaration.col,
            )
        initializer_list = isinstance(declaration.initializer, (BraceInitializer, ListLiteral))
        if (
            type_expr.is_array
            and type_expr.array_size is None
            and initializer_list
            and not declaration.initializer.elements
        ):
            self._error(
                f"{subject} cannot infer an array bound from an empty initializer",
                declaration.line,
                declaration.col,
            )
        if (
            type_expr.is_array
            and type_expr.array_size is not None
            and declaration.initializer is not None
            and not self._is_gpu_array_initializer(declaration.initializer)
        ):
            constant_bound, _ = self._integer_constant_expression(type_expr.array_size)
            if not constant_bound:
                self._error(
                    f"{subject} is a variable-length array and cannot have an initializer",
                    declaration.line,
                    declaration.col,
                )
        has_static_storage = is_global or type_expr.is_static
        if (
            has_static_storage
            and declaration.initializer is not None
            and not type_expr.is_extern
            and not self._is_static_storage_initializer(
                declaration.initializer,
                type_expr,
            )
        ):
            self._error(
                f"{subject} requires a C constant/address initializer for static storage",
                declaration.line,
                declaration.col,
            )

    def _is_gpu_array_initializer(self, expression) -> bool:
        if not isinstance(expression, CallExpr) or not isinstance(expression.callee, Identifier):
            return False
        function = self.function_table.get(expression.callee.name)
        return bool(function and function.is_gpu and function.return_type.is_array)

    def _validate_array_bound(self, type_expr, subject, context) -> None:
        if type_expr is None:
            return
        for argument in type_expr.generic_args or []:
            self._validate_array_bound(argument, subject, context)
        bound = type_expr.array_size
        if not type_expr.is_array or bound is None:
            return
        marker = id(bound)
        if marker not in getattr(self, "_analyzed_array_bounds", set()):
            self._analyzed_array_bounds.add(marker)
            self._analyze_expr(bound)
        bound_type = self._infer_type(bound)
        if bound_type is not None and not self._is_integral_value(bound_type):
            self._error(
                f"Array bound for {subject} must be integral",
                getattr(bound, "line", type_expr.line),
                getattr(bound, "col", type_expr.col),
            )
        constant, numeric = self._integer_constant_expression(bound)
        if numeric is not None and numeric <= 0:
            self._error(
                f"Array bound for {subject} must be positive",
                getattr(bound, "line", type_expr.line),
                getattr(bound, "col", type_expr.col),
            )
        if context in {"field", "global", "static"} and not constant:
            self._error(
                f"Array bound for {subject} must be a constant expression",
                getattr(bound, "line", type_expr.line),
                getattr(bound, "col", type_expr.col),
            )

    def _validate_class_field_contract(self, class_decl, field) -> None:
        subject = f"Field '{class_decl.name}.{field.name}'"
        if field.access == "class" and class_decl.generic_params:
            self._error(
                f"Static {subject.lower()} is not supported on a generic class",
                field.line,
                field.col,
            )
        context = "static" if field.access == "class" else "field"
        self._validate_array_bound(field.type, subject, context)
        canonical = self._canonical_type(field.type)
        if (
            field.access != "class"
            and field.initializer is not None
            and canonical
            and canonical.is_const
            and not self._is_pointer_value(canonical)
        ):
            self._error(
                f"{subject} cannot initialize a scalar const class field after allocation",
                field.line,
                field.col,
            )
        if (
            field.access == "class"
            and field.initializer is not None
            and not self._is_static_storage_initializer(field.initializer, field.type)
        ):
            self._error(
                f"Static {subject.lower()} requires a C constant/address initializer",
                field.line,
                field.col,
            )

    def _validate_property_storage(self, class_decl, prop) -> None:
        subject = f"Property '{class_decl.name}.{prop.name}'"
        if prop.access == "class":
            self._error(f"Static {subject.lower()} is not supported", prop.line, prop.col)
        canonical = self._canonical_type(prop.type)
        if prop.has_setter and canonical and canonical.is_const and not self._is_pointer_value(canonical):
            self._error(
                f"{subject} cannot have a setter for scalar const storage",
                prop.line,
                prop.col,
            )
        self._validate_array_bound(prop.type, subject, "field")

    def _validate_parameter_bounds(self, params, owner) -> None:
        """Validate parameter VLAs with earlier parameters in lexical scope."""
        self._push_scope()
        try:
            for parameter in params:
                self._validate_array_bound(
                    parameter.type,
                    f"parameter '{owner}.{parameter.name}'",
                    "parameter",
                )
                self.scope.define(
                    parameter.name,
                    self._local_symbol(
                        parameter.name,
                        parameter.type,
                        "param",
                        parameter.name_line or parameter.line,
                        parameter.name_col or parameter.col,
                    ),
                )
        finally:
            self._pop_scope()

    def _active_storage_type_parameters(self):
        active = set(self.current_class.generic_params if self.current_class else ())
        if self.current_method:
            active.update(self.current_method.generic_params)
        return active


__all__ = ["StorageContractsMixin"]
