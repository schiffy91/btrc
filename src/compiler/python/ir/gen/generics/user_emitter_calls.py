"""Call and argument lowering for monomorphized generic methods."""

from ...nodes import IRCall, IRLiteral, IRVar
from ..call_builtins import lower_len, lower_typed_print
from ..generic_intrinsics import lower_generic_intrinsic
from ..typed_operators import operator_context
from ..types import is_string_type
from .user_emitter_arc import _UserGenericArcMixin


class _UserGenericCallMixin(_UserGenericArcMixin):
    def _call(self, expression):
        """Lower a call through the shared managed-operand boundary."""
        declaration = self._callable_for_call(expression)
        params = self._params_for_call(expression)
        from ..call_effects import owned_transfer_param_indices
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
            callee=expression.callee if callable_field else self._evaluated_callee(expression),
            pin_receiver=receiver_pin_required(
                self._gen,
                receiver,
                declared_call=declaration is not None,
                type_of=self._resolve_expr_type,
                owned_local_type=lambda name: managed_local_type(self, name),
            ),
            force_order=self._language_ordered_call(
                expression,
                declaration,
            ),
        )
        if not operands:
            return self._plain_call(expression)
        return self._sequence_call(
            operands,
            expression,
            lambda: self._plain_call(expression),
        )

    @staticmethod
    def _evaluated_callee(expression):
        from ....ast_nodes import FieldAccessExpr, Identifier, LambdaExpr

        callee = expression.callee
        if isinstance(callee, (Identifier, FieldAccessExpr, LambdaExpr)):
            return None
        return callee

    def _language_ordered_call(self, expression, declaration):
        if declaration is not None:
            return True
        from ....ast_nodes import FieldAccessExpr, Identifier

        if isinstance(expression.callee, Identifier):
            if expression.callee.name in {"print", "printf", "Mutex"}:
                return True
        if isinstance(expression.callee, FieldAccessExpr):
            if (
                isinstance(expression.callee.obj, Identifier)
                and expression.callee.obj.name in self._gen.analyzed.rich_enum_table
            ):
                return True
            from ....string_methods import STRING_METHODS
            from ..type_resolution import canonical_type

            receiver_type = canonical_type(
                self._resolve_expr_type(expression.callee.obj),
                self._gen.analyzed.typedef_table,
            )
            if is_string_type(receiver_type) and expression.callee.field in STRING_METHODS:
                return True
            if receiver_type is not None and receiver_type.base == "Mutex":
                return True
        callee_type = self._resolve_expr_type(expression.callee)
        return bool(callee_type is not None and callee_type.base == "__fn_ptr")

    def _plain_call(self, expression):
        from ....ast_nodes import FieldAccessExpr, Identifier, SelfExpr

        if isinstance(expression.callee, Identifier) and self._gen:
            name = expression.callee.name
            is_builtin = name not in self._gen.analyzed.function_table
            if is_builtin and name == "print":
                return lower_typed_print(
                    self._gen,
                    expression.args,
                    lower_value=self._expr,
                    resolve_type=self._resolve_expr_type,
                )
            if is_builtin and name == "len" and expression.args:
                argument = expression.args[0]
                return lower_len(
                    self._gen,
                    self._expr(argument),
                    self._resolve_expr_type(argument),
                )

        args = [self._expr(arg) for arg in expression.args]
        arg_names = getattr(expression, "arg_names", []) or []

        if isinstance(expression.callee, Identifier):
            name = expression.callee.name
            if self._gen and name == "Mutex":
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

                return create_mutex_value(self._gen, args[0], value_type)
            intrinsic = lower_generic_intrinsic(
                name,
                args,
                [self._resolve_expr_type(arg) for arg in expression.args],
                operator_context(self._gen, fresh_temp=self._fresh_temp),
            )
            if intrinsic is not None:
                return intrinsic
            if self._gen and name in self._gen.analyzed.class_table:
                class_info = self._gen.analyzed.class_table[name]
                if class_info.constructor:
                    args = self._order_args_for_params(
                        class_info.constructor.params,
                        expression.args,
                        arg_names,
                        args,
                    )
                if class_info.generic_params:
                    return IRCall(callee=f"{self.mangled}_new", args=args)
            if self._gen and name in (
                "__btrc_safe_calloc",
                "__btrc_safe_realloc",
                "__btrc_str_track",
                "__btrc_string_adopt",
                "__btrc_string_alloc",
                "__btrc_string_length",
                "__btrc_string_or_empty",
            ):
                self._gen.use_helper(name)
            if self._gen and name in self._gen.analyzed.function_table and name not in self._var_types:
                function = self._gen.analyzed.function_table[name]
                args = self._order_args_for_params(function.params, expression.args, arg_names, args)
                from ..function_symbols import source_function_c_name

                name = source_function_c_name(self._gen.analyzed, name)
            return IRCall(callee=name, args=args)

        if isinstance(expression.callee, FieldAccessExpr):
            receiver = expression.callee.obj
            method_name = expression.callee.field
            if self._callable_field(expression):
                return IRCall(
                    callee=self._expr(expression.callee),
                    args=args,
                )
            if isinstance(receiver, SelfExpr):
                if self._cls_info:
                    method = self._cls_info.methods.get(method_name)
                    if method:
                        args = self._order_args_for_params(
                            method.params,
                            expression.args,
                            arg_names,
                            args,
                        )
                return IRCall(
                    callee=f"{self.mangled}_{method_name}",
                    args=[IRVar(name="self"), *args],
                )
            if self._gen and isinstance(receiver, Identifier):
                receiver_type = self._var_types.get(receiver.name)
                if receiver_type and receiver_type.base in self._gen.analyzed.class_table:
                    class_info = self._gen.analyzed.class_table[receiver_type.base]
                    method = class_info.methods.get(method_name)
                    if method:
                        args = self._order_args_for_params(
                            method.params,
                            expression.args,
                            arg_names,
                            args,
                        )

            receiver_ir = self._expr(receiver)
            receiver_type = self._resolve_expr_type(receiver)
            if self._gen and is_string_type(receiver_type):
                from ..methods import (
                    _STRING_CONVERSION_METHODS,
                    _STRING_METHODS,
                    _lower_string_method,
                    _lower_string_special,
                )

                if method_name in _STRING_METHODS:
                    return _lower_string_method(self._gen, receiver_ir, method_name, args)
                special = _lower_string_special(self._gen, receiver_ir, method_name, args)
                if special is not None:
                    return special
                if method_name in _STRING_CONVERSION_METHODS:
                    callee, cast_to = _STRING_CONVERSION_METHODS[method_name]
                    call_args = [receiver_ir]
                    if callee in {"strtof", "strtod"}:
                        call_args.append(IRLiteral(text="NULL"))
                    helper_ref = callee if callee.startswith("__btrc_") else None
                    if helper_ref:
                        self._gen.use_helper(helper_ref)
                    call = IRCall(callee=callee, args=call_args, helper_ref=helper_ref)
                    if cast_to:
                        from ...nodes import CType, IRCast

                        return IRCast(target_type=CType(text=cast_to), expr=call)
                    return call

            if self._gen:
                from ..sync_methods import lower_sync_method

                sync = lower_sync_method(
                    self._gen,
                    receiver,
                    receiver_ir,
                    method_name,
                    receiver_type,
                    args,
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

        return IRCall(
            callee=self._expr(expression.callee),
            args=args,
        )

    def _order_args_for_params(self, params, ast_args, arg_names, ir_args):
        if not params:
            return ir_args
        names = list(arg_names)
        names.extend([""] * (len(ast_args) - len(names)))
        if not any(names):
            result = list(ir_args)
            for index in range(len(result), len(params)):
                default = params[index].default
                result.append(self._expr(default) if default is not None else IRLiteral(text="0"))
            return result

        param_indices = {param.name: index for index, param in enumerate(params)}
        result = [None] * len(params)
        positional_index = 0
        for index, arg in enumerate(ir_args):
            name = names[index]
            if name:
                param_index = param_indices.get(name)
                if param_index is not None:
                    result[param_index] = arg
                continue
            if positional_index < len(params):
                result[positional_index] = arg
                positional_index += 1
        for index, param in enumerate(params):
            if result[index] is None:
                default = param.default
                result[index] = self._expr(default) if default is not None else IRLiteral(text="0")
        return [arg for arg in result if arg is not None]
