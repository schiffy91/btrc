"""ARC boundaries for calls emitted inside monomorphized generic methods."""

from __future__ import annotations

from ..call_boundary import CallOperand, sequence_call_boundary
from ..evaluation_order import borrowed_value_can_be_pinned, operand_c_type
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
                from .user_constructor_calls import new_constructor_parameters

                params = new_constructor_parameters(
                    self,
                    expression,
                    class_info,
                    resolved,
                )
            elif resolved.base == "Mutex" and resolved.generic_args:
                from ....ast_nodes import Param

                params = [
                    Param(
                        type=resolved.generic_args[0],
                        name="value",
                    )
                ]
        from ..call_effects import owned_transfer_param_indices

        operands = self._call_operands(
            params,
            expression.args,
            getattr(expression, "arg_names", []) or [],
            None,
            owned_transfer_param_indices(constructor),
            callee=None,
            force_order=True,
            call=expression,
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
        result_type_override=None,
        result_owned_override=None,
    ):
        result_type = (
            result_type_override
            if result_type_override is not None
            else self._resolve_expr_type(expression)
            if expression is not None
            else None
        )
        if result_c_type is _INFER_RESULT:
            result_c_type = self.iter_value_c(result_type) if result_type is not None else None

        def build_with_overrides(overrides):
            previous = {key: self._arc_overrides.get(key) for key in overrides}
            previous_types = {key: self._arc_type_overrides.get(key) for key in overrides}
            self._arc_overrides.update(overrides)
            self._arc_type_overrides.update({id(operand.node): operand.type_expr for operand in operands})
            try:
                return build()
            finally:
                for key, value in previous.items():
                    if value is None:
                        self._arc_overrides.pop(key, None)
                    else:
                        self._arc_overrides[key] = value
                for key, value in previous_types.items():
                    if value is None:
                        self._arc_type_overrides.pop(key, None)
                    else:
                        self._arc_type_overrides[key] = value

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
            result_owned=(
                result_owned_override
                if result_owned_override is not None
                else bool(promote_result or (expression is not None and self._owns_expr(expression)))
            ),
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
        prepared_values=None,
    ):
        """Evaluate eager operands once and stabilize managed values."""
        operands = self._owned_node_operands(
            nodes,
            keep_nodes=keep_nodes,
            pin_nodes=pin_nodes,
            force=force,
            prepared_values=prepared_values,
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
        prepared_values=None,
    ):
        specs = []
        prepared_values = prepared_values or {}
        keep_ids = {id(node) for node in keep_nodes}
        pin_ids = {id(node) for node in pin_nodes}
        for node in nodes:
            prepared = prepared_values.get(id(node))
            type_expr = prepared.effective_type if prepared is not None else self._resolve_expr_type(node)
            owned = bool(
                prepared.owned
                if prepared is not None
                else id(node) not in self._arc_overrides and self._is_managed_type(type_expr) and self._owns_expr(node)
            )
            keep = id(node) in keep_ids
            pin = id(node) in pin_ids and not owned and borrowed_value_can_be_pinned(node)
            specs.append((node, type_expr, owned, keep, pin, prepared))
        from ..evaluation_order import source_order_pin_flags

        automatic_pins = source_order_pin_flags(
            self._gen,
            nodes,
            [type_expr for _node, type_expr, _owned, _keep, _pin, _prepared in specs],
            [owned for _node, _type_expr, owned, _keep, _pin, _prepared in specs],
            type_of=self._resolve_expr_type,
            is_managed=self._is_managed_type,
        )
        specs = [
            (node, type_expr, owned, keep, pin or automatic_pins[index], prepared)
            for index, (node, type_expr, owned, keep, pin, prepared) in enumerate(specs)
        ]
        lifetime_required = any(owned or keep or pin for _node, _type_expr, owned, keep, pin, _prepared in specs)
        needs_boundary = force or lifetime_required
        if not needs_boundary:
            return None
        if not lifetime_required and any(
            type_expr is None for _node, type_expr, _owned, _keep, _pin, _prepared in specs
        ):
            return None
        for _node, type_expr, _owned, _keep, _pin, _prepared in specs:
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
                lowered=prepared.value if prepared is not None else None,
            )
            for node, type_expr, owned, keep, pin, prepared in specs
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
        pin_receiver=False,
        force_order=True,
        call=None,
    ):
        from .user_call_operands import generic_call_operands

        return generic_call_operands(
            self,
            params,
            ast_args,
            arg_names,
            receiver,
            transferred_params,
            callee=callee,
            pin_receiver=pin_receiver,
            force_order=force_order,
            call=call,
        )


__all__ = ["_UserGenericArcMixin"]
