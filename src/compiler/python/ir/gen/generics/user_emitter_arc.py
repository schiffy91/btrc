"""ARC boundaries for calls emitted inside monomorphized generic methods."""

from __future__ import annotations

from ..arguments import bind_arg_nodes_to_params
from ..call_boundary import CallOperand, sequence_call_boundary
from .user_emitter_ownership import _UserGenericOwnershipMixin

_INFER_RESULT = object()


class _UserGenericArcMixin(_UserGenericOwnershipMixin):
    def _new_with_arc(self, expression):
        """Lower ``new`` with the same boundary used for ordinary calls."""
        params = []
        constructor = None
        if self._gen:
            resolved = self._resolve(expression.type)
            class_info = self._gen.analyzed.class_table.get(resolved.base)
            if class_info and class_info.constructor:
                constructor = class_info.constructor
                params = constructor.params
        from ..call_effects import owned_transfer_param_indices

        operands = self._call_operands(
            params,
            expression.args,
            getattr(expression, "arg_names", []) or [],
            None,
            owned_transfer_param_indices(constructor),
        )
        if not operands:
            return self._new_expr_plain(expression)
        return self._sequence_call(
            operands,
            expression,
            lambda: self._new_expr_plain(expression),
        )

    def _sequence_call(
        self,
        operands,
        expression,
        build,
        *,
        promote_result=False,
        result_c_type=_INFER_RESULT,
        lower_expr=None,
    ):
        result_type = self._resolve_expr_type(expression) if expression is not None else None
        if result_c_type is _INFER_RESULT:
            result_c_type = self.iter_value_c(result_type) if result_type is not None else None

        def build_with_overrides(overrides):
            previous = {key: self._arc_overrides.get(key) for key in overrides}
            self._arc_overrides.update(overrides)
            try:
                return build()
            finally:
                for key, value in previous.items():
                    if value is None:
                        self._arc_overrides.pop(key, None)
                    else:
                        self._arc_overrides[key] = value

        return sequence_call_boundary(
            self._gen,
            operands,
            lower_expr=lower_expr or self._expr,
            build_call=build_with_overrides,
            result_c_type=result_c_type,
            result_type=result_type,
            fresh_temp=self._fresh_temp,
            cleanup_active=self._exception_cleanup_active(),
            record_decl=self._func_var_decls.append,
            promote_result=promote_result,
            activate_cleanup=self._activate_cleanup_registration,
        )

    def _activate_cleanup_registration(self):
        from .user_emitter_scopes import mark_cleanup_registration

        mark_cleanup_registration(self)

    def _exception_cleanup_active(self):
        from .user_emitter_scopes import exception_cleanup_active

        return exception_cleanup_active(self)

    def _sequence_owned_nodes(
        self,
        nodes,
        expression,
        build,
        *,
        promote_result=False,
    ):
        """Evaluate source operands once when any operand is caller-owned."""
        operands = self._owned_node_operands(nodes)
        if operands is None:
            return None
        return self._sequence_call(
            operands,
            expression,
            build,
            promote_result=promote_result,
        )

    def _sequence_owned_effect(self, nodes, build):
        """Sequence owned operands around a side-effecting void operation."""
        operands = self._owned_node_operands(nodes)
        if operands is None:
            return build()
        return self._sequence_call(
            operands,
            None,
            build,
            result_c_type="void",
        )

    def _owned_node_operands(self, nodes):
        specs = []
        any_owned = False
        for node in nodes:
            type_expr = self._resolve_expr_type(node)
            owned = bool(
                id(node) not in self._arc_overrides and self._is_managed_type(type_expr) and self._owns_expr(node)
            )
            any_owned = any_owned or owned
            specs.append((node, type_expr, owned))
        if not any_owned:
            return None
        for _node, type_expr, _owned in specs:
            self._require_operand_type(type_expr)
        return [
            CallOperand(
                node=node,
                type_expr=type_expr,
                c_type=self.iter_value_c(type_expr),
                owned=owned,
            )
            for node, type_expr, owned in specs
        ]

    def _call_operands(
        self,
        params,
        ast_args,
        arg_names,
        receiver,
        transferred_params=frozenset(),
    ):
        if not self._gen:
            return []
        bindings = bind_arg_nodes_to_params(params, ast_args, arg_names)
        receiver_type = self._resolve_expr_type(receiver) if receiver is not None else None
        receiver_owned = bool(self._is_managed_type(receiver_type) and self._owns_expr(receiver))
        specs = []
        for param_index, argument, _is_default in bindings:
            param = params[param_index] if param_index is not None and param_index < len(params) else None
            argument_type = self._resolve_expr_type(argument)
            if argument_type is None and param is not None:
                argument_type = self._resolve(param.type)
            managed = self._is_managed_type(argument_type)
            owned = bool(managed and self._owns_expr(argument))
            specs.append(
                (
                    argument,
                    argument_type,
                    bool(managed and param is not None and param.keep),
                    owned,
                    bool(owned and param_index in transferred_params),
                )
            )
        if not receiver_owned and not any(keep or owned for _argument, _type, keep, owned, _transferred in specs):
            return []

        operands = []
        if receiver is not None:
            self._require_operand_type(receiver_type)
            operands.append(
                CallOperand(
                    node=receiver,
                    type_expr=receiver_type,
                    c_type=self.iter_value_c(receiver_type),
                    owned=receiver_owned,
                )
            )
        for argument, argument_type, keep, owned, transferred in specs:
            self._require_operand_type(argument_type)
            operands.append(
                CallOperand(
                    node=argument,
                    type_expr=argument_type,
                    c_type=self.iter_value_c(argument_type),
                    keep=keep,
                    owned=owned,
                    transferred=transferred,
                )
            )
        return operands

    def _callable_for_call(self, expression):
        from ....ast_nodes import FieldAccessExpr, Identifier, SelfExpr

        if not self._gen:
            return None
        callee = expression.callee
        if isinstance(callee, Identifier):
            class_info = self._gen.analyzed.class_table.get(callee.name)
            if class_info is not None:
                return class_info.constructor
            return self._gen.analyzed.function_table.get(callee.name)
        if not isinstance(callee, FieldAccessExpr):
            return None
        if isinstance(callee.obj, SelfExpr):
            return self._cls_info.methods.get(callee.field) if self._cls_info else None
        if isinstance(callee.obj, Identifier):
            class_info = self._gen.analyzed.class_table.get(callee.obj.name)
            if class_info is not None:
                method = class_info.methods.get(callee.field)
                if method is not None:
                    return method
        receiver_type = self._resolve_expr_type(callee.obj)
        class_info = self._gen.analyzed.class_table.get(receiver_type.base) if receiver_type is not None else None
        return class_info.methods.get(callee.field) if class_info else None

    def _params_for_call(self, expression):
        declaration = self._callable_for_call(expression)
        return declaration.params if declaration is not None else []

    def _instance_receiver(self, expression):
        from ....ast_nodes import FieldAccessExpr, Identifier, SelfExpr

        callee = expression.callee
        if not isinstance(callee, FieldAccessExpr):
            return None
        if isinstance(callee.obj, SelfExpr):
            return None
        if isinstance(callee.obj, Identifier) and self._gen:
            if callee.obj.name in self._gen.analyzed.class_table:
                return None
        return callee.obj


__all__ = ["_UserGenericArcMixin"]
