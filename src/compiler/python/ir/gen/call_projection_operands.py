"""Backing-storage operands for borrowed call-argument projections."""

from ...ast_nodes import Identifier


def readonly_hosted_borrow_needs_no_guard(
    call,
    parameter_index,
    *,
    has_later_effects,
    hosted_call_ids,
):
    """Recognize a borrow whose owner cannot be invalidated before return."""
    if has_later_effects or call is None or parameter_index is None:
        return False
    if id(call) not in hosted_call_ids or not isinstance(call.callee, Identifier):
        return False
    from ...hosted_abi import hosted_parameter_is_read_only_borrow

    return hosted_parameter_is_read_only_borrow(
        call.callee.name,
        parameter_index,
    )


def expand_projection_owner_specs(
    specs,
    *,
    owners_for,
    type_of,
    omit_borrowed_guard=lambda _spec, _index: False,
):
    """Insert projection storage before its dependent call operand."""
    expanded = []
    deferred = set()
    for index, spec in enumerate(specs):
        expression = spec[0]
        owners = [] if spec[-2] else owners_for(expression)
        if omit_borrowed_guard(spec, index):
            owners = [owner for owner in owners if owner.owned]
        if owners:
            deferred.add(id(expression))
        expanded.extend(
            (
                owner.expression,
                type_of(owner.expression),
                None,
                owner.keep,
                owner.owned,
                False,
                None,
                False,
                None,
            )
            for owner in owners
        )
        expanded.append(spec)
    return expanded, deferred


__all__ = [
    "expand_projection_owner_specs",
    "readonly_hosted_borrow_needs_no_guard",
]
