"""Source-order and lifetime planning for ordinary call operands."""

from .call_boundary import CallOperand
from .call_operand_diagnostics import missing_default_target, missing_operand_type
from .default_argument_context import (
    default_argument_scope,
    in_call_argument_context,
    resolve_default_type,
)
from .evaluation_order import borrowed_value_can_be_pinned
from .projection_storage import evaluate_with_operand_overrides
from .types import CTypeRenderer


class CallOperandPlanner:
    """Plan and lower one call's source operands exactly once."""

    def __init__(
        self,
        context,
        ownership,
        resolver,
        arguments,
        hosted_results,
        type_renderer: CTypeRenderer,
    ) -> None:
        self.context = context
        self.ownership = ownership
        self.resolver = resolver
        self.arguments = arguments
        self.hosted_results = hosted_results
        self.type_renderer = type_renderer

    def plan(
        self,
        params,
        ast_args,
        arg_names,
        *,
        receiver=None,
        callee=None,
        transferred_params=frozenset(),
        pin_receiver: bool = False,
        force_order: bool = True,
        call=None,
        default_receiver_value=None,
    ):
        if self.context.is_unevaluated:
            return [], False
        from .arguments import bind_arg_nodes_to_params
        from .default_argument_calls import bound_nodes_by_parameter

        bindings = bind_arg_nodes_to_params(params, ast_args, arg_names)
        bound_nodes = bound_nodes_by_parameter(params, bindings)
        specs = self._leading_specs(callee, receiver, pin_receiver)
        specs.extend(
            self._argument_specs(
                bindings,
                params,
                transferred_params,
            )
        )
        effects = [self._spec_has_effect(spec) for spec in specs]
        specs, deferred = self._expand_projection_owners(
            specs,
            effects,
            call,
            callee,
            default_receiver_value,
        )
        effects = [self._spec_has_effect(spec) for spec in specs]
        ownership_required = bool(deferred) or any(
            keep or owned for _argument, _type, _target, keep, owned, *_rest in specs
        )
        ordered = force_order and self.ownership.order.operands_require_order([spec[0] for spec in specs])
        has_default = any(spec[-2] for spec in specs)
        if not (ownership_required or ordered or has_default):
            return [], False
        return (
            self._lower(
                specs,
                effects,
                deferred,
                call=call,
                params=params,
                bound_nodes=bound_nodes,
                receiver=receiver,
                default_receiver_value=default_receiver_value,
            ),
            True,
        )

    def _leading_specs(self, callee, receiver, pin_receiver):
        specs = []
        for value in (callee, receiver):
            if value is None:
                continue
            type_expr = self.context.type_of(value) or self.resolver.callable_type(value)
            managed = self.ownership.types.is_managed(type_expr)
            specs.append(
                (
                    value,
                    type_expr,
                    None,
                    bool(value is receiver and pin_receiver),
                    bool(managed and self.ownership.owns_result(value)),
                    False,
                    None,
                    False,
                    None,
                )
            )
        return specs

    def _argument_specs(self, bindings, params, transferred_params):
        from .hosted_result_conversion import REJECT

        specs = []
        for param_index, argument, is_default in bindings:
            param = params[param_index] if param_index is not None and 0 <= param_index < len(params) else None
            if is_default and param is not None:
                target_type = param.type
                managed = self.ownership.types.is_managed(target_type)
                specs.append(
                    (
                        argument,
                        target_type,
                        target_type,
                        bool(managed and param.keep),
                        bool(managed),
                        bool(managed and param_index in transferred_params),
                        param,
                        True,
                        param_index,
                    )
                )
                continue
            source_type = self._call_argument_type(
                param,
                argument,
                is_default=is_default,
            )
            target_type = param.type if param is not None else source_type
            if (
                self.hosted_results.conversion_mode(
                    argument,
                    target_type,
                    source_type,
                )
                == REJECT
                and param is not None
                and not param.keep
                and param_index not in transferred_params
            ):
                target_type = source_type
            converted = self.hosted_results.requires_target_conversion(
                argument,
                target_type,
                source_type,
            )
            effective_type = target_type if converted else (source_type or target_type)
            managed = self.ownership.types.is_managed(effective_type)
            owned = bool(
                managed
                and (
                    converted
                    or in_call_argument_context(
                        param,
                        is_default,
                        lambda argument=argument: self.ownership.owns_result(argument),
                    )
                )
            )
            specs.append(
                (
                    argument,
                    effective_type,
                    target_type,
                    bool(managed and param is not None and param.keep),
                    owned,
                    bool(owned and param_index in transferred_params),
                    param,
                    is_default,
                    param_index,
                )
            )
        return specs

    def _spec_has_effect(self, spec):
        argument, _type, target_type, _keep, _owned, _transfer, param, is_default, _index = spec
        return bool(
            is_default
            or (
                target_type is not None
                and self.hosted_results.requires_target_conversion(
                    argument,
                    target_type,
                    self._call_argument_type(
                        param,
                        argument,
                        is_default=is_default,
                    ),
                )
            )
            or self.ownership.order.has_effect(argument)
        )

    def _expand_projection_owners(
        self,
        specs,
        effects,
        call,
        callee,
        default_receiver_value,
    ):
        from ...hosted_alias_carriers import hosted_alias_argument
        from .call_projection_operands import (
            expand_projection_owner_specs,
            readonly_hosted_borrow_needs_no_guard,
        )
        from .projection_storage import projection_storage_operands

        def owners(expression):
            if default_receiver_value is not None and expression is callee:
                return []
            return projection_storage_operands(
                expression,
                type_of=self.context.type_of,
                is_managed=self.ownership.types.is_managed,
                owns=self.ownership.owns_result,
                overridden=lambda value: id(value) in self.context.owning_overrides,
                struct_table=self.context.analyzed.struct_table,
                return_alias_argument=lambda value: hosted_alias_argument(
                    value,
                    self.context.analyzed.hosted_call_ids,
                ),
            )

        return expand_projection_owner_specs(
            specs,
            owners_for=owners,
            type_of=self.context.type_of,
            omit_borrowed_guard=lambda spec, index: readonly_hosted_borrow_needs_no_guard(
                call,
                spec[-1],
                has_later_effects=any(effects[index + 1 :]),
                hosted_call_ids=self.context.analyzed.hosted_call_ids,
            ),
        )

    def _lower(
        self,
        specs,
        effects,
        deferred,
        *,
        call,
        params,
        bound_nodes,
        receiver,
        default_receiver_value,
    ):
        operands = []
        final_index = len(specs) - 1
        spec_types = {id(node): type_expr for node, type_expr, *_rest in specs}
        for index, spec in enumerate(specs):
            (
                argument,
                type_expr,
                target_type,
                keep,
                owned,
                transferred,
                param,
                is_default,
                param_index,
            ) = spec
            if type_expr is None:
                if index == final_index and index > 0 and not (keep or owned):
                    continue
                missing_operand_type(argument)
            pin = bool(
                borrowed_value_can_be_pinned(argument)
                and index < final_index
                and any(effects[index + 1 :])
                and self.ownership.types.is_managed(type_expr)
                and not owned
            )
            prepared = None
            lower_with_overrides = None
            if is_default:
                if call is None or param_index is None:
                    missing_default_target()
                lower_with_overrides = self.arguments.default_builder(
                    call,
                    params,
                    param_index,
                    bound_nodes,
                    receiver_node=receiver,
                    receiver_value=default_receiver_value,
                )
                type_expr = target_type
                owned = self.ownership.types.is_managed(type_expr)
            elif target_type is not None:
                prepare = self._prepared_value_builder(
                    argument,
                    param,
                    is_default,
                    target_type,
                )
                if id(argument) in deferred:

                    def lower_prepared(overrides, prepare=prepare):
                        return self._evaluate_with_overrides(
                            overrides,
                            spec_types,
                            lambda: prepare().value,
                        )

                    lower_with_overrides = lower_prepared
                else:
                    prepared = prepare()
                    type_expr = prepared.effective_type
                    owned = prepared.owned
            elif id(argument) in deferred:

                def lower_direct(
                    overrides,
                    argument=argument,
                    param=param,
                    is_default=is_default,
                ):
                    return self._evaluate_with_overrides(
                        overrides,
                        spec_types,
                        lambda: self._lower_call_argument(
                            param,
                            argument,
                            is_default=is_default,
                        ),
                    )

                lower_with_overrides = lower_direct
            operands.append(
                CallOperand(
                    node=argument,
                    type_expr=type_expr,
                    c_type=(
                        self.type_renderer.render(type_expr)
                        if prepared is not None or lower_with_overrides is not None
                        else self.ownership.order.operand_c_type(
                            argument,
                            type_expr,
                            render=self.type_renderer.render,
                        )
                    ),
                    keep=keep,
                    pin=pin,
                    owned=owned,
                    transferred=transferred,
                    lowered=prepared.value if prepared is not None else None,
                    lower_with_overrides=lower_with_overrides,
                )
            )
        return operands

    def _prepared_value_builder(self, argument, param, is_default, target_type):
        return lambda: self.arguments.prepare(
            argument,
            target_type,
            param=param,
            is_default=is_default,
            owns_result=lambda value: bool(
                id(value) not in self.context.owning_overrides
                and in_call_argument_context(
                    param,
                    is_default,
                    lambda: self.ownership.owns_result(value),
                )
            ),
        )

    def _call_argument_type(self, param, argument, *, is_default):
        with default_argument_scope(param, is_default):
            return resolve_default_type(self.context.type_of(argument))

    def _lower_call_argument(self, param, argument, *, is_default):
        return self.arguments.lower_argument(
            param,
            argument,
            is_default=is_default,
        )

    def _evaluate_with_overrides(self, overrides, spec_types, operation):
        return evaluate_with_operand_overrides(
            overrides,
            values=self.context.owning_overrides,
            types=spec_types,
            type_values=self.context.type_overrides,
            operation=operation,
        )


__all__ = ["CallOperandPlanner"]
