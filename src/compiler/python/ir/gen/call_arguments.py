"""Target-directed argument lowering for ordinary calls."""

from __future__ import annotations

from ..nodes import CType, IRCall, IRCast
from .default_argument_context import (
    call_argument_type,
    default_argument_scope,
)
from .default_argument_helpers import ensure_default_helper
from .prepared_values import prepare_value
from .types import type_to_c
from .upcast import upcast_class_pointer


class CallArgumentLowerer:
    """Own default binding, conversion, and source-argument lowering.

    The next IR migration slice must give default helpers and value preparation
    explicit owners and remove this owner's ``lowerer`` reach-through.
    """

    def __init__(
        self,
        lowerer,
        context,
        ownership,
        hosted_results,
        expressions,
    ) -> None:
        self.lowerer = lowerer
        self.context = context
        self.ownership = ownership
        self.hosted_results = hosted_results
        self.expressions = expressions

    def default_builder(
        self,
        call,
        params,
        param_index,
        bound_nodes,
        *,
        receiver_node,
        receiver_value,
    ):
        """Build a default helper from stabilized earlier operands."""

        def build(overrides):
            target, symbol = ensure_default_helper(
                self.lowerer,
                call,
                params,
                param_index,
            )
            args = []
            if target.self_type is not None:
                value = receiver_value
                if value is None and receiver_node is not None:
                    value = overrides.get(id(receiver_node))
                if value is None:
                    self._missing_dependency("method receiver")
                args.append(
                    IRCast(
                        target_type=CType(text=type_to_c(target.self_type)),
                        expr=value,
                    )
                )
            for prior_index in range(param_index):
                prior = bound_nodes[prior_index]
                value = overrides.get(id(prior)) if prior is not None else None
                if value is None:
                    self._missing_dependency(params[prior_index].name)
                prior_param = params[prior_index]
                source_type = (
                    prior_param.type if prior is prior_param.default else call_argument_type(self.lowerer, None, prior)
                )
                args.append(
                    upcast_class_pointer(
                        self.lowerer,
                        prior_param.type,
                        source_type,
                        value,
                    )
                )
            return IRCall(callee=symbol, args=args)

        return build

    def prepare(
        self,
        argument,
        target_type,
        *,
        param,
        is_default,
        owns_result,
    ):
        """Lower one argument and expose its effective ownership contract."""
        return prepare_value(
            self.lowerer,
            argument,
            target_type,
            ownership=self.ownership,
            lower_expr=lambda value: self.lower_argument(
                param,
                value,
                is_default=is_default,
            ),
            type_of=lambda value: call_argument_type(
                self.lowerer,
                param,
                value,
                is_default=is_default,
            ),
            owns_result=owns_result,
            render_type=type_to_c,
            hosted_results=self.hosted_results,
        )

    def lower_argument(self, param, argument, *, is_default):
        with default_argument_scope(param, is_default):
            return self.expressions.lower_expression(argument)

    def order(self, params, ast_args, arg_names, ir_args):
        from .arguments import order_args_for_params

        return order_args_for_params(
            self.lowerer,
            params,
            ast_args,
            arg_names,
            ir_args,
        )

    @staticmethod
    def _missing_dependency(name) -> None:
        from .errors import CodegenError

        raise CodegenError(f"default argument dependency '{name}' was not evaluated before use")


__all__ = ["CallArgumentLowerer"]
