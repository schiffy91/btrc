"""Generic constructor-call result inference and contextual resolution."""

from ..ast_nodes import CallExpr, Identifier, TernaryExpr, TypeExpr


class ConstructorInferenceMixin:
    def _contextualize_generic_constructor(self, expected, expression) -> bool:
        """Stamp generic constructor calls with an exact expected type."""
        if expected is None:
            return False
        if isinstance(expression, TernaryExpr):
            left = self._contextualize_generic_constructor(expected, expression.true_expr)
            right = self._contextualize_generic_constructor(expected, expression.false_expr)
            return left or right
        if not (isinstance(expression, CallExpr) and isinstance(expression.callee, Identifier)):
            return False
        cls = self.declarations.class_table.get(expression.callee.name)
        if not (
            cls
            and cls.generic_params
            and expected.base == cls.name
            and len(expected.generic_args) == len(cls.generic_params)
        ):
            return False
        self._record_node_type(expression, expected)
        self._collect_generic_instances(expected)
        if cls.constructor:
            substitutions = dict(zip(cls.generic_params, expected.generic_args))
            names = self._arg_names(expression.args, expression.arg_names)
            for param_index, arg_index in self._bound_arguments(cls.constructor.params, names):
                if arg_index >= len(expression.args):
                    continue
                argument_type = self._substitute_type(
                    cls.constructor.params[param_index].type,
                    substitutions,
                )
                self._contextualize_generic_constructor(argument_type, expression.args[arg_index])
        return True

    def _infer_constructor_call_type(self, expression, cls):
        """Infer ``Box<T>`` from constructor arguments to ``Box(...)``."""
        if not cls.generic_params:
            return TypeExpr(base=cls.name, pointer_depth=1)

        substitutions = self._infer_constructor_type_args(expression, cls)
        if substitutions is not None:
            return TypeExpr(
                base=cls.name,
                generic_args=[substitutions[name] for name in cls.generic_params],
                pointer_depth=1,
            )

        # A constructor call in its own generic class still has the owning
        # instance's type parameters even when its signature cannot infer all
        # of them from arguments.
        if self.current_class is cls:
            return self._current_self_type()
        return TypeExpr(base=cls.name, pointer_depth=1)

    def _infer_constructor_type_args(self, expression, cls):
        constructor = cls.constructor
        if constructor is None:
            return None
        type_params = set(cls.generic_params)
        substitutions = {}
        names = self._arg_names(expression.args, expression.arg_names)
        for param_index, arg_index in self._bound_arguments(constructor.params, names):
            if arg_index >= len(expression.args):
                continue
            declared = constructor.params[param_index].type
            actual = self._arg_type_for_inference(expression.args[arg_index])
            if (
                declared is not None
                and actual is not None
                and not self._unify_type_param(declared, actual, type_params, substitutions)
            ):
                return None
        if any(name not in substitutions for name in cls.generic_params):
            return None
        return substitutions
