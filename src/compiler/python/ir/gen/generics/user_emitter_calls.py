"""Call and argument lowering for monomorphized generic methods."""

from ....source_runtime_symbols import is_source_runtime_helper
from ...nodes import IRCall, IRVar
from ..call_builtins import lower_len, lower_typed_print
from ..generic_intrinsics import lower_generic_intrinsic
from ..type_resolution import function_pointer_signature
from ..typed_operators import operator_context
from .user_builtin_methods import lower_generic_builtin_method
from .user_call_arguments import order_generic_call_arguments
from .user_call_ordering import evaluated_callee, language_ordered_call
from .user_constructor_calls import lower_class_constructor_call
from .user_emitter_arc import _UserGenericArcMixin
from .user_static_calls import lower_ordinary_static_call


class _UserGenericCallMixin(_UserGenericArcMixin):
    def _call(self, expression):
        """Lower a call through the shared managed-operand boundary."""
        from ..aggregate_ownership import reject_rich_enum_owned_args
        from ..callable_boundaries import reject_unsafe_managed_callback_arguments
        from .user_callable_provenance import generic_callable_return_abi

        if self._gen is not None:
            reject_rich_enum_owned_args(
                self._gen,
                expression,
                self._default_arguments,
            )
        params = self._params_for_call(expression)
        reject_unsafe_managed_callback_arguments(
            self._gen,
            expression,
            params=params,
            callable_abi=lambda value: generic_callable_return_abi(
                self,
                value,
            ),
        )
        from .user_gpu_dispatch import is_direct_generic_gpu_call

        if is_direct_generic_gpu_call(self, expression):
            return self._plain_call(expression)
        from ..hosted_result_conversion import (
            lower_hosted_string_conversion,
            requested_hosted_string_conversion,
        )

        result_conversion = requested_hosted_string_conversion(
            self._gen,
            expression,
        )

        def build():
            call = self._plain_call(expression)
            if result_conversion is not None:
                call = lower_hosted_string_conversion(
                    self._gen,
                    call,
                    result_conversion[0],
                )
            return call

        declaration = self._callable_for_call(expression)
        from ....ownership_effects import owned_transfer_param_indices
        from ..receiver_pinning import receiver_pin_required
        from .user_emitter_scopes import managed_local_type

        callable_field = self._callable_field(expression)
        receiver = None if callable_field else self._instance_receiver(expression)
        operands = self._call_operands(
            params,
            expression.args,
            getattr(expression, "arg_names", []) or [],
            receiver,
            owned_transfer_param_indices(declaration),
            callee=(expression.callee if callable_field else evaluated_callee(self, expression)),
            pin_receiver=receiver_pin_required(
                self._gen,
                receiver,
                declared_call=declaration is not None,
                type_of=self._resolve_expr_type,
                owned_local_type=lambda name: managed_local_type(self, name),
            ),
            force_order=language_ordered_call(
                self,
                expression,
                declaration,
            ),
            call=expression,
        )
        if not operands:
            return build()
        return self._sequence_call(
            operands,
            expression,
            build,
            result_type_override=(result_conversion[1] if result_conversion is not None else None),
            result_owned_override=(True if result_conversion is not None else None),
        )

    def _plain_call(self, expression):
        from ....ast_nodes import FieldAccessExpr, Identifier, SelfExpr

        if isinstance(expression.callee, Identifier) and self._gen:
            name = expression.callee.name
            is_variable = name in self._var_types or name in self._gen.analyzed.global_var_types
            is_builtin = not is_variable and name not in self._gen.analyzed.function_table
            if is_builtin and name == "print":
                return lower_typed_print(
                    self._gen,
                    expression.args,
                    lower_value=self._expr,
                    resolve_type=self._resolve_expr_type,
                    type_renderer=self._type_renderer,
                )
            if is_builtin and name == "len" and expression.args:
                argument = expression.args[0]
                return lower_len(
                    self._gen,
                    self._expr(argument),
                    self._resolve_expr_type(argument),
                )

        arg_names = getattr(expression, "arg_names", []) or []
        params = self._params_for_call(expression)

        if isinstance(expression.callee, Identifier):
            from .user_gpu_dispatch import (
                is_direct_generic_gpu_call,
                lower_generic_gpu_call,
            )

            if is_direct_generic_gpu_call(self, expression):
                return lower_generic_gpu_call(self, expression, None)

        args = [self._expr(arg) for arg in expression.args]

        if isinstance(expression.callee, Identifier):
            name = expression.callee.name
            variable_callee = name in self._var_types or bool(self._gen and name in self._gen.analyzed.global_var_types)
            if variable_callee:
                return self._callable_expression_call(
                    expression.callee,
                    args,
                )
            if self._gen and name == "Mutex" and name not in self._gen.analyzed.function_table:
                if len(args) != 1:
                    from ..errors import CodegenError

                    raise CodegenError("Mutex construction requires one initial value")
                mutex_type = self._resolve_expr_type(expression)
                value_type = (
                    mutex_type.generic_args[0]
                    if mutex_type is not None and mutex_type.generic_args
                    else self._resolve_expr_type(expression.args[0])
                )
                from ..mutex_values import create_mutex_value

                return create_mutex_value(
                    self._gen,
                    args[0],
                    value_type,
                    self._type_renderer,
                )
            intrinsic = lower_generic_intrinsic(
                name,
                args,
                [self._resolve_expr_type(arg) for arg in expression.args],
                operator_context(
                    self._gen,
                    self._type_renderer,
                    fresh_temp=self._fresh_temp,
                ),
            )
            if intrinsic is not None:
                return intrinsic
            constructor_call = lower_class_constructor_call(
                self,
                expression,
                name,
                args,
                arg_names,
                params,
            )
            if constructor_call is not None:
                return constructor_call
            if self._gen and is_source_runtime_helper(name):
                self._gen.helpers.use(name)
            if self._gen and name in self._gen.analyzed.function_table and name not in self._var_types:
                if id(expression) not in self._gen.analyzed.hosted_call_ids:
                    args = order_generic_call_arguments(
                        self,
                        params,
                        expression.args,
                        arg_names,
                        args,
                    )
                from ..function_symbols import source_function_c_name

                name = source_function_c_name(self._gen.analyzed, name, expression)
            return IRCall(callee=name, args=args)

        if isinstance(expression.callee, FieldAccessExpr):
            receiver = expression.callee.obj
            method_name = expression.callee.field
            if self._callable_field(expression):
                return self._callable_expression_call(
                    expression.callee,
                    args,
                )
            from ..rich_enum_calls import lower_generic_rich_enum_call

            variant_call = lower_generic_rich_enum_call(
                self,
                expression,
                params,
                args,
                arg_names,
            )
            if variant_call is not None:
                return variant_call
            static_call = lower_ordinary_static_call(
                self,
                expression,
                args,
                arg_names,
                params,
            )
            if static_call is not None:
                return static_call
            if isinstance(receiver, SelfExpr):
                if self._cls_info:
                    if self._cls_info.methods.get(method_name):
                        args = order_generic_call_arguments(
                            self,
                            params,
                            expression.args,
                            arg_names,
                            args,
                        )
                return IRCall(
                    callee=f"{self.mangled}_{method_name}",
                    args=[IRVar(name="self"), *args],
                )
            receiver_ir = self._expr(receiver)
            receiver_type = self._resolve_expr_type(receiver)
            if self._gen and receiver_type is not None:
                class_info = self._gen.analyzed.class_table.get(receiver_type.base)
                if class_info and class_info.methods.get(method_name):
                    args = order_generic_call_arguments(
                        self,
                        params,
                        expression.args,
                        arg_names,
                        args,
                    )
            builtin = lower_generic_builtin_method(
                self,
                receiver_ir,
                receiver_type,
                method_name,
                args,
            )
            if builtin is not None:
                return builtin

            if self._gen:
                from ..sync_methods import lower_sync_method

                sync = lower_sync_method(
                    self._gen,
                    receiver,
                    receiver_ir,
                    method_name,
                    receiver_type,
                    args,
                    self._type_renderer,
                )
                if sync is not None:
                    return sync

            target = self._mangle_type(receiver_type)
            if target:
                return IRCall(
                    callee=f"{target}_{method_name}",
                    args=[receiver_ir, *args],
                )
            return IRCall(callee=method_name, args=[receiver_ir, *args])

        return self._callable_expression_call(expression.callee, args)

    def _callable_expression_call(self, callee_node, args):
        callee = self._expr(callee_node)
        if self._gen is None:
            return IRCall(callee=callee, args=args)
        signature = function_pointer_signature(
            self._resolve_expr_type(callee_node),
            self._typedefs(),
        )
        if signature is None:
            return IRCall(callee=callee, args=args)
        return self._gen.calls.resolver.materialize_callee(
            callee_node,
            callee,
            signature,
            args,
            callee_materialized=id(callee_node) in self._arc_overrides,
            fresh_temp=self._fresh_temp,
            record_decl=self._func_var_decls.append,
            overridden=lambda node: id(node) in self._arc_overrides,
        )
