"""Function, constructor, and method-call validation."""

from __future__ import annotations

from dataclasses import replace

from ..ast_nodes import FieldAccessExpr, Identifier, LambdaExpr
from ..operator_semantics import GENERIC_INTRINSICS


class CallValidationMixin:
    def _analyze_call(self, expr):
        if isinstance(expr.callee, Identifier):
            self._analyze_identifier_value(expr.callee, direct_callee=True)
        else:
            self._analyze_expr(expr.callee)
        for arg in expr.args:
            self._analyze_expr(arg)
            self._reject_thread_value_escape(arg, "passed as arguments")

        if isinstance(expr.callee, Identifier) and expr.callee.name == "gpu_id":
            if not self.in_gpu_function:
                self._error("gpu_id() can only be called inside @gpu functions", expr.line, expr.col)
            if expr.args:
                self._error("gpu_id() takes no arguments", expr.line, expr.col)

        if isinstance(expr.callee, Identifier):
            self._validate_identifier_call(expr)
        elif isinstance(expr.callee, FieldAccessExpr):
            self._validate_method_call(expr)
        elif isinstance(expr.callee, LambdaExpr):
            self._validate_call_signature("lambda", expr.callee.params, expr.args, expr.arg_names, expr.line, expr.col)
        self._validate_callable_target(expr)
        self._invalidate_nonnull_call(expr)

    def _validate_identifier_call(self, expr):
        name = expr.callee.name
        if name == "Mutex":
            if any(expr.arg_names or []):
                self._error(
                    "'Mutex()' does not accept named arguments",
                    expr.line,
                    expr.col,
                )
            if len(expr.args) != 1:
                self._error(
                    f"'Mutex()' expects 1 argument but got {len(expr.args)}",
                    expr.line,
                    expr.col,
                )
            return
        if name in GENERIC_INTRINSICS:
            self._validate_generic_intrinsic_call(expr)
            return
        if name in self.class_table:
            cls = self.class_table[name]
            if cls.is_abstract:
                self._error(f"Cannot instantiate abstract class '{cls.name}'", expr.line, expr.col)
            inferred = self._infer_constructor_call_type(expr, cls)
            if len(inferred.generic_args) == len(cls.generic_params):
                self._collect_generic_instances(inferred)
            substitutions = None
            if len(inferred.generic_args) == len(cls.generic_params):
                substitutions = dict(zip(cls.generic_params, inferred.generic_args))
            self._validate_constructor_args(cls, expr.args, expr.arg_names, expr.line, expr.col, substitutions)
            return
        if name in self.function_table:
            function = self.function_table[name]
            self._validate_call_signature(
                function.name,
                function.params,
                expr.args,
                expr.arg_names,
                expr.line,
                expr.col,
                gpu_dispatch=function.is_gpu,
            )
            return

        symbol = self.scope.lookup(name)
        signature = self._function_pointer_signature(symbol.type if symbol else None)
        if signature is not None:
            self._validate_fn_ptr_call(name, signature[1:], expr.args, expr.line, expr.col, expr.arg_names)

    def _validate_method_call(self, expr):
        callee = expr.callee
        signature = self._function_pointer_signature(self._infer_type(callee))
        if signature is not None:
            self._validate_fn_ptr_call(
                callee.field,
                signature[1:],
                expr.args,
                expr.line,
                expr.col,
                expr.arg_names,
            )
            return
        receiver_type = self._infer_type(callee.obj)
        if self._validate_builtin_method_call(expr, receiver_type):
            return
        if (
            isinstance(callee.obj, Identifier)
            and self.scope.lookup(callee.obj.name) is None
            and callee.obj.name in self.class_table
        ):
            cls = self.class_table[callee.obj.name]
            method = cls.methods.get(callee.field)
            if method is None:
                self._error(f"Class '{cls.name}' has no class method '{callee.field}'", expr.line, expr.col)
                return
            substitutions = self._method_substitutions(expr, cls, method, receiver_type=None)
            self._validate_call_signature(
                f"{cls.name}.{callee.field}",
                method.params,
                expr.args,
                expr.arg_names,
                expr.line,
                expr.col,
                substitutions,
                (*cls.generic_params, *method.generic_params),
            )
            self._collect_method_instance(expr, cls, method, None, substitutions)
            return

        if not receiver_type or receiver_type.base not in self.class_table:
            return
        cls = self.class_table[receiver_type.base]
        method = cls.methods.get(callee.field)
        if method is None:
            return
        if method.access == "class":
            self._error(
                f"Class method '{callee.field}' must be called on '{cls.name}', not on an instance",
                expr.line,
                expr.col,
            )
            return
        substitutions = self._method_substitutions(expr, cls, method, receiver_type)
        self._validate_call_signature(
            f"{cls.name}.{callee.field}",
            method.params,
            expr.args,
            expr.arg_names,
            expr.line,
            expr.col,
            substitutions,
            (*cls.generic_params, *method.generic_params),
        )
        self._collect_method_instance(expr, cls, method, receiver_type, substitutions)

    def _method_substitutions(self, expr, cls, method, receiver_type):
        substitutions = {}
        if receiver_type and cls.generic_params and receiver_type.generic_args:
            substitutions.update(zip(cls.generic_params, receiver_type.generic_args))
        if method.generic_params:
            inferred = self._infer_method_type_args(expr, method, substitutions)
            if inferred:
                substitutions.update(inferred)
            else:
                self._error(
                    f"Cannot infer consistent type arguments for generic method '{method.name}()'",
                    expr.line,
                    expr.col,
                )
        return substitutions

    def _collect_method_instance(self, expr, cls, method, receiver_type, substitutions):
        ret = method.return_type
        if ret and ret.generic_args and substitutions:
            resolved = self._substitute_type(ret, substitutions)
            if resolved and resolved.generic_args:
                self._collect_generic_instances(resolved)
        if method.generic_params and receiver_type is not None:
            self._collect_generic_method_instance(expr, cls, method, receiver_type)

    def _validate_call_signature(
        self, name, params, args, arg_names, line, col, substitutions=None, unresolved=(), gpu_dispatch=False
    ):
        names = self._arg_names(args, arg_names)
        self._validate_call_arity(name, params, args, names, line, col)
        for param_index, arg_index in self._bound_arguments(params, names):
            if arg_index >= len(args):
                continue
            expected = params[param_index].type
            if substitutions:
                expected = self._substitute_type(expected, substitutions)
            # An unresolved generic parameter cannot be checked until its
            # owning instance/call site supplies a concrete substitution.
            if expected.base in unresolved:
                continue
            argument = args[arg_index]
            argument_line = getattr(argument, "line", line)
            argument_col = getattr(argument, "col", col)
            self._contextualize_generic_constructor(expected, argument)
            self._contextualize_aggregate_initializer(
                expected,
                argument,
                f"Argument '{params[param_index].name}' to '{name}()'",
                argument_line,
                argument_col,
            )
            if self._validate_callable_value(expected, argument, argument_line, argument_col):
                continue
            actual = self._infer_type(argument)
            compatible = actual and (
                self._types_compatible(expected, actual)
                or (gpu_dispatch and self._gpu_buffer_argument_compatible(expected, actual))
            )
            if actual and not compatible:
                self._error(
                    f"Argument '{params[param_index].name}' to '{name}()' "
                    f"expects '{self._format_type(expected)}' but got "
                    f"'{self._format_type(actual)}'",
                    argument_line,
                    argument_col,
                )

    def _gpu_buffer_argument_compatible(self, expected, actual) -> bool:
        return bool(
            expected.is_array
            and actual.base in ("Array", "Vector")
            and len(actual.generic_args) == 1
            and self._types_compatible(
                replace(expected, is_array=False, array_size=None),
                actual.generic_args[0],
            )
        )

    def _validate_constructor_args(self, cls, args, arg_names, line, col, substitutions=None):
        if (
            cls.constructor is not None
            and cls.constructor.access == "private"
            and (self.current_class is None or self.current_class.name != cls.name)
        ):
            self._error(
                f"Cannot call private constructor of class '{cls.name}'",
                line,
                col,
            )
        if cls.constructor is None:
            if args:
                self._error(
                    f"Class '{cls.name}' has no constructor but was called with {len(args)} argument(s)", line, col
                )
            return
        self._validate_call_signature(
            cls.name, cls.constructor.params, args, arg_names, line, col, substitutions, cls.generic_params
        )
