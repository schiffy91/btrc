"""ARC boundaries for calls emitted inside monomorphized generic methods."""

from __future__ import annotations

from ..arguments import bind_arg_nodes_to_params
from ..call_boundary import CallOperand, sequence_call_boundary
from ..evaluation_order import has_observable_effect, operand_c_type
from .user_emitter_call_metadata import _UserGenericCallMetadataMixin
from .user_emitter_ownership import _UserGenericOwnershipMixin

_INFER_RESULT = object()


class _UserGenericArcMixin(_UserGenericCallMetadataMixin, _UserGenericOwnershipMixin):
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
            callee=None,
            force_order=True,
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
        keep_nodes=(),
        pin_nodes=(),
        force=False,
    ):
        """Evaluate eager operands once and stabilize managed values."""
        operands = self._owned_node_operands(
            nodes,
            keep_nodes=keep_nodes,
            pin_nodes=pin_nodes,
            force=force,
        )
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

    def _owned_node_operands(
        self,
        nodes,
        *,
        keep_nodes=(),
        pin_nodes=(),
        force=False,
    ):
        specs = []
        keep_ids = {id(node) for node in keep_nodes}
        pin_ids = {id(node) for node in pin_nodes}
        lifetime_required = False
        for node in nodes:
            type_expr = self._resolve_expr_type(node)
            owned = bool(
                id(node) not in self._arc_overrides and self._is_managed_type(type_expr) and self._owns_expr(node)
            )
            keep = id(node) in keep_ids
            pin = id(node) in pin_ids and not owned
            lifetime_required = lifetime_required or owned or keep or pin
            specs.append((node, type_expr, owned, keep, pin))
        needs_boundary = force or lifetime_required
        if not needs_boundary:
            return None
        if not lifetime_required and any(type_expr is None for _node, type_expr, _owned, _keep, _pin in specs):
            return None
        for _node, type_expr, _owned, _keep, _pin in specs:
            self._require_operand_type(type_expr)
        return [
            CallOperand(
                node=node,
                type_expr=type_expr,
                c_type=operand_c_type(
                    self._gen,
                    node,
                    type_expr,
                    render=self.iter_value_c,
                ),
                keep=keep,
                pin=pin,
                owned=owned,
            )
            for node, type_expr, owned, keep, pin in specs
        ]

    def _call_operands(
        self,
        params,
        ast_args,
        arg_names,
        receiver,
        transferred_params=frozenset(),
        *,
        callee=None,
        force_order=True,
    ):
        if not self._gen:
            return []
        bindings = bind_arg_nodes_to_params(params, ast_args, arg_names)
        specs = []
        for value in (callee, receiver):
            if value is None:
                continue
            value_type = self._resolve_expr_type(value)
            value_owned = bool(self._is_managed_type(value_type) and self._owns_expr(value))
            specs.append((value, value_type, False, value_owned, False))
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
        effects = [
            has_observable_effect(
                self._gen,
                argument,
                type_of=self._resolve_expr_type,
            )
            for argument, _type, _keep, _owned, _transferred in specs
        ]
        ownership_required = any(keep or owned for _argument, _type, keep, owned, _transferred in specs)
        types_complete = all(type_expr is not None for _argument, type_expr, _keep, _owned, _transferred in specs)
        if not ownership_required and not (force_order and len(specs) > 1 and types_complete and any(effects)):
            return []

        operands = []
        final_index = len(specs) - 1
        for index, (argument, argument_type, keep, owned, transferred) in enumerate(specs):
            self._require_operand_type(argument_type)
            pin = bool(
                index < final_index and any(effects[index + 1 :]) and self._is_managed_type(argument_type) and not owned
            )
            operands.append(
                CallOperand(
                    node=argument,
                    type_expr=argument_type,
                    c_type=operand_c_type(
                        self._gen,
                        argument,
                        argument_type,
                        render=self.iter_value_c,
                    ),
                    keep=keep,
                    pin=pin,
                    owned=owned,
                    transferred=transferred,
                )
            )
        return operands


__all__ = ["_UserGenericArcMixin"]
