"""Borrowed receiver stabilization rules shared by call lowerers."""

from .evaluation_order import borrowed_value_can_be_pinned


def receiver_pin_required(
    gen,
    receiver,
    *,
    declared_call: bool = False,
    later_effect: bool = False,
    type_of=None,
    owned_local_type=None,
) -> bool:
    """Whether a borrowed receiver needs a call-scoped owning guard."""
    if receiver is None or not borrowed_value_can_be_pinned(receiver):
        return False
    from ...ast_nodes import Identifier

    if (
        isinstance(receiver, Identifier)
        and owned_local_type is not None
        and owned_local_type(receiver.name) is not None
        and not later_effect
    ):
        return False
    if declared_call or later_effect:
        return True

    resolve_type = type_of or (lambda node: gen.analyzed.node_types.get(id(node)))
    return gen.managed_values.is_mutex(resolve_type(receiver))


__all__ = ["receiver_pin_required"]
