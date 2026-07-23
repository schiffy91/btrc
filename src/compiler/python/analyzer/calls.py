"""Function, constructor, and method-call validation."""

from __future__ import annotations

from ..ast_nodes import FieldAccessExpr, Identifier, LambdaExpr
from ..operator_semantics import GENERIC_INTRINSICS


class CallValidationMixin:
    def _analyze_call(self, expr):
        self.gpu_dispatch.validate_result_context(expr, self.scope)
        raw_lifetime = self._is_raw_lifetime_call(expr)
        if isinstance(expr.callee, Identifier):
            self._analyze_identifier_value(expr.callee, direct_callee=True)
        elif isinstance(expr.callee, FieldAccessExpr):
            self._analyze_field_access(expr.callee, call_target=True)
        else:
            self._analyze_expr(expr.callee)
        for index, arg in enumerate(expr.args):
            self._analyze_expr(arg)
            if not raw_lifetime or index != 0:
                self._reject_thread_value_escape(arg, "passed as arguments")
        from .raw_projection_calls import (
            validate_conditional_raw_projection_call,
        )

        validate_conditional_raw_projection_call(self, expr)

        if (
            isinstance(expr.callee, Identifier)
            and expr.callee.name == "gpu_id"
            and expr.callee.name not in self.declarations.function_table
            and ((symbol := self.scope.lookup(expr.callee.name)) is None or symbol.kind == "function")
        ):
            if not self.in_gpu_function:
                self.context.error("gpu_id() can only be called inside @gpu functions", expr.line, expr.col)
            if expr.args:
                self.context.error("gpu_id() takes no arguments", expr.line, expr.col)

        if isinstance(expr.callee, Identifier):
            self._validate_source_macro_call(expr)
            self._validate_identifier_call(expr)
        elif isinstance(expr.callee, FieldAccessExpr):
            self._validate_method_call(expr)
        elif isinstance(expr.callee, LambdaExpr):
            self._validate_call_signature(
                "lambda",
                expr.callee.params,
                expr.args,
                expr.arg_names,
                expr.line,
                expr.col,
                declaration=expr.callee,
            )
        self._validate_callable_target(expr)
        self._invalidate_nonnull_call(expr)

    def _validate_identifier_call(self, expr):
        name = expr.callee.name
        if self._is_raw_lifetime_call(expr):
            self._validate_raw_lifetime_call(expr)
        if self.gpu_kernels.call_uses_intrinsic(
            expr,
            self.scope,
            in_gpu_function=self.in_gpu_function,
        ):
            if name in self.declarations.function_table:
                # A canonical bodyless hosted prototype is superseded by the
                # closed GPU intrinsic in this context. Preserve that resolved
                # identity for CPU-fallback lowering.
                self._hosted_call_ids.add(id(expr))
            return
        hosted_call_validated = self._validate_hosted_abi_call(expr)
        if self._hosted_call_bypasses_source_definition(expr):
            return
        if hosted_call_validated:
            return
        symbol = self.scope.lookup(name)
        if symbol is not None and symbol.kind != "function":
            signature = self._function_pointer_signature(symbol.type)
            if signature is not None:
                self._validate_fn_ptr_call(
                    name,
                    signature[1:],
                    expr.args,
                    expr.line,
                    expr.col,
                    expr.arg_names,
                )
            return
        if name in self.declarations.function_table:
            function = self.declarations.function_table[name]
            self._validate_call_signature(
                function.name,
                function.params,
                expr.args,
                expr.arg_names,
                expr.line,
                expr.col,
                gpu_dispatch=function.is_gpu,
                declaration=function,
                bodyless_ffi=function.body is None,
            )
            self._validate_consuming_arguments(
                function,
                expr.args,
                expr.arg_names,
                function.name,
            )
            return
        if name == "Mutex":
            if any(expr.arg_names or []):
                self.context.error(
                    "'Mutex()' does not accept named arguments",
                    expr.line,
                    expr.col,
                )
            if len(expr.args) != 1:
                self.context.error(
                    f"'Mutex()' expects 1 argument but got {len(expr.args)}",
                    expr.line,
                    expr.col,
                )
            return
        if name in GENERIC_INTRINSICS:
            self._validate_generic_intrinsic_call(expr)
            return
        if name in self.declarations.class_table:
            cls = self.declarations.class_table[name]
            if cls.is_abstract:
                self.context.error(f"Cannot instantiate abstract class '{cls.name}'", expr.line, expr.col)
            inferred = self._infer_constructor_call_type(expr, cls)
            if len(inferred.generic_args) == len(cls.generic_params):
                self._collect_generic_instances(inferred)
            substitutions = None
            if len(inferred.generic_args) == len(cls.generic_params):
                substitutions = dict(zip(cls.generic_params, inferred.generic_args))
            self._validate_constructor_args(cls, expr.args, expr.arg_names, expr.line, expr.col, substitutions)
            return

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
            and callee.obj.name in self.declarations.class_table
        ):
            cls = self.declarations.class_table[callee.obj.name]
            method = cls.methods.get(callee.field)
            if method is None:
                self.context.error(f"Class '{cls.name}' has no class method '{callee.field}'", expr.line, expr.col)
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
                declaration=method,
            )
            self._validate_consuming_arguments(
                method,
                expr.args,
                expr.arg_names,
                f"{cls.name}.{callee.field}",
            )
            self._collect_method_instance(expr, cls, method, None, substitutions)
            return

        if not receiver_type or receiver_type.base not in self.declarations.class_table:
            return
        cls = self.declarations.class_table[receiver_type.base]
        method = cls.methods.get(callee.field)
        if method is None:
            return
        if method.access == "class":
            self.context.error(
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
            declaration=method,
        )
        self._validate_consuming_arguments(
            method,
            expr.args,
            expr.arg_names,
            f"{cls.name}.{callee.field}",
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
                self.context.error(
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

    def _validate_constructor_args(self, cls, args, arg_names, line, col, substitutions=None):
        if (
            cls.constructor is not None
            and cls.constructor.access == "private"
            and (self.current_class is None or self.current_class.name != cls.name)
        ):
            self.context.error(
                f"Cannot call private constructor of class '{cls.name}'",
                line,
                col,
            )
        if cls.constructor is None:
            if args:
                self.context.error(
                    f"Class '{cls.name}' has no constructor but was called with {len(args)} argument(s)", line, col
                )
            return
        self._validate_call_signature(
            cls.name,
            cls.constructor.params,
            args,
            arg_names,
            line,
            col,
            substitutions,
            cls.generic_params,
            declaration=cls.constructor,
        )
        self._validate_consuming_arguments(
            cls.constructor,
            args,
            arg_names,
            cls.name,
        )
