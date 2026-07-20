"""Call-site construction for declaration-scoped default evaluators."""

from __future__ import annotations

from ..nodes import CType, IRCall, IRCast
from .default_argument_context import call_argument_type
from .default_argument_helpers import ensure_default_helper
from .types import type_to_c
from .upcast import upcast_class_pointer


def bound_nodes_by_parameter(params, bindings):
    """Return the explicit or default AST node supplying each parameter."""

    result = [None] * len(params)
    for param_index, node, _is_default in bindings:
        if param_index is not None and 0 <= param_index < len(result):
            result[param_index] = node
    return result


def default_call_builder(
    gen,
    call,
    params,
    param_index,
    bound_nodes,
    *,
    receiver_node=None,
    receiver_value=None,
    resolve_argument_type=None,
):
    """Build a helper call from already-stabilized earlier operands."""

    def ordinary_argument_type(node):
        return call_argument_type(
            gen,
            None,
            node,
        )

    argument_type_resolver = resolve_argument_type or ordinary_argument_type

    def build(overrides):
        target, symbol = ensure_default_helper(
            gen,
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
                _missing_dependency("method receiver")
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
                _missing_dependency(params[prior_index].name)
            prior_param = params[prior_index]
            source_type = prior_param.type if prior is prior_param.default else argument_type_resolver(prior)
            args.append(
                upcast_class_pointer(
                    gen,
                    prior_param.type,
                    source_type,
                    value,
                )
            )
        return IRCall(callee=symbol, args=args)

    return build


def _missing_dependency(name):
    from .errors import CodegenError

    raise CodegenError(f"default argument dependency '{name}' was not evaluated before use")


__all__ = ["bound_nodes_by_parameter", "default_call_builder"]
