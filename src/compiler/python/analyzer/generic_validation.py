"""Generic shape validation and monomorphization target collection."""

from ..ast_nodes import TypeExpr
from ..type_identity import TypeShapeError

_UNREGISTERED_GENERIC_INSTANCE_BASES = frozenset({"Array", "List", "Map", "Mutex", "Set", "Thread", "Vector"})
_RUNTIME_GENERIC_ARITIES = {
    "Array": 1,
    "List": 1,
    "Map": 2,
    "Mutex": 1,
    "Set": 1,
    "Thread": 1,
    "Vector": 1,
}
_RUNTIME_GENERIC_MIN_ARITIES = {"Tuple": 2, "__fn_ptr": 1}


class GenericValidationMixin:
    def _normalize_type_key(self, type_expr: TypeExpr) -> tuple:
        return self.type_identity.shape_key(type_expr)

    def _report_type_shape_error(self, message, type_expr, line=0, col=0):
        error_line = getattr(type_expr, "line", 0) or line
        error_col = getattr(type_expr, "col", 0) or col
        marker = (message, error_line, error_col)
        reported = getattr(self, "_reported_type_shape_errors", set())
        if marker in reported:
            return
        reported.add(marker)
        self._reported_type_shape_errors = reported
        self.context.error(message, error_line, error_col)

    def _validate_generic_arguments(self, owner, args, line=0, col=0):
        valid = True
        for index, argument in enumerate(args, 1):
            problem = self.type_identity.generic_argument_problem(argument)
            if problem is None:
                continue
            message, bad_type = problem
            self._report_type_shape_error(
                f"Generic argument {index} for '{owner}' is invalid: {message}",
                bad_type,
                line,
                col,
            )
            valid = False
        return valid

    def _validate_substitution_shapes(self, owner, declared_types, substitutions, line=0, col=0):
        valid = True
        for declared in declared_types:
            if declared is None:
                continue
            try:
                resolved = self.type_identity.substitute(
                    declared,
                    substitutions,
                    reference_resolver=self._canonical_type,
                )
            except TypeShapeError as error:
                self._report_type_shape_error(
                    f"Generic specialization '{owner}' is invalid: {error}",
                    error.type_expr or declared,
                    line,
                    col,
                )
                valid = False
                continue
            if not self._validate_nested_class_arguments(owner, resolved, line, col):
                valid = False
            if not self._validate_mutex_payloads_in_type(
                resolved,
                line=line,
                col=col,
            ):
                valid = False
        return valid

    def _validate_nested_class_arguments(self, owner, type_expr, line=0, col=0):
        if type_expr is None:
            return True
        valid = True
        cls = self.declarations.class_table.get(type_expr.base)
        if cls is not None and cls.generic_params:
            valid = self._validate_generic_arguments(
                f"{owner} via {type_expr.base}",
                type_expr.generic_args or [],
                line,
                col,
            )
        for argument in type_expr.generic_args or []:
            if not self._validate_nested_class_arguments(owner, argument, line, col):
                valid = False
        return valid

    def _validate_generic_specialization(self, type_expr):
        args = type_expr.generic_args or []
        cls = self.declarations.class_table.get(type_expr.base)
        if cls is None or not cls.generic_params:
            return True
        valid = self._validate_generic_arguments(type_expr.base, args, type_expr.line, type_expr.col)
        if len(args) != len(cls.generic_params):
            return valid
        substitutions = dict(zip(cls.generic_params, args))
        declared_types = [field.type for field in cls.fields.values()]
        declared_types.extend(prop.type for prop in cls.properties.values())
        for method in cls.methods.values():
            declared_types.append(method.return_type)
            declared_types.extend(param.type for param in method.params)
        return (
            self._validate_substitution_shapes(
                type_expr.base,
                declared_types,
                substitutions,
                type_expr.line,
                type_expr.col,
            )
            and valid
        )

    def _collect_generic_instances(self, type_expr, unresolved_names=()):
        if type_expr is None:
            return
        active = set(unresolved_names)
        if self.current_class is not None:
            active.update(self.current_class.generic_params)
        if self.current_method is not None:
            active.update(self.current_method.generic_params)
        base_is_parameter = type_expr.base in active
        self._validate_generic_arity(type_expr, base_is_parameter)
        if type_expr.generic_args:
            self._collect_concrete_specialization(type_expr, active, base_is_parameter)
            for argument in type_expr.generic_args:
                self._collect_generic_instances(argument, unresolved_names)

    def _validate_generic_arity(self, type_expr, base_is_parameter):
        if base_is_parameter:
            return
        declaration = self.declarations.class_table.get(type_expr.base)
        if declaration is None:
            declaration = self.declarations.interface_table.get(type_expr.base)
        expected = (
            len(declaration.generic_params) if declaration is not None else _RUNTIME_GENERIC_ARITIES.get(type_expr.base)
        )
        actual = len(type_expr.generic_args)
        if expected is not None and actual != expected:
            self._report_type_shape_error(
                f"Type '{type_expr.base}' expects {expected} generic argument(s) but got {actual}",
                type_expr,
            )
            return
        minimum = _RUNTIME_GENERIC_MIN_ARITIES.get(type_expr.base)
        if minimum is not None and actual < minimum:
            self._report_type_shape_error(
                f"Type '{type_expr.base}' expects at least {minimum} generic argument(s) but got {actual}",
                type_expr,
            )

    def _collect_concrete_specialization(self, type_expr, active, base_is_parameter):
        args = tuple(type_expr.generic_args)
        key = type_expr.base
        cls = self.declarations.class_table.get(key)
        registered = bool(cls and cls.generic_params and not base_is_parameter)
        runtime = (
            cls is None and key not in self.declarations.interface_table and key in _UNREGISTERED_GENERIC_INSTANCE_BASES
        )
        unresolved = any(self.type_identity.references_names(argument, active) for argument in args)
        instances = self.generic_instances.setdefault(key, []) if registered or runtime else []
        normalized = tuple(self._normalize_type_key(argument) for argument in args)
        if registered and not unresolved and cls is not None and len(args) == len(cls.generic_params):
            if any(
                tuple(self._normalize_type_key(argument) for argument in existing) == normalized
                for existing in instances
            ):
                return
        valid = self._validate_generic_specialization(type_expr) if registered else True
        if not ((registered or runtime) and valid and not unresolved):
            return
        if cls is not None and len(args) != len(cls.generic_params):
            return
        if not any(
            tuple(self._normalize_type_key(argument) for argument in existing) == normalized for existing in instances
        ):
            instances.append(args)
        if cls and cls.generic_params:
            substitutions = dict(zip(cls.generic_params, type_expr.generic_args))
            for method in cls.methods.values():
                result = method.return_type
                if result and result.generic_args:
                    resolved = self._substitute_type(result, substitutions)
                    if resolved and resolved.generic_args and resolved.base != key:
                        self._collect_generic_instances(resolved, method.generic_params)


__all__ = ["GenericValidationMixin"]
