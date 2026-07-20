"""Built-in receiver methods inside generic specializations."""

from ...nodes import CType, IRCall, IRCast, IRLiteral
from ..methods import (
    _STRING_CONVERSION_METHODS,
    _STRING_METHODS,
    _lower_string_method,
    _lower_string_special,
    _lower_to_string,
)
from ..types import is_string_type


def lower_generic_builtin_method(
    emitter,
    receiver,
    receiver_type,
    method_name,
    args,
):
    gen = emitter._gen
    if gen is None:
        return None
    if is_string_type(receiver_type):
        if method_name in _STRING_METHODS:
            return _lower_string_method(gen, receiver, method_name, args)
        special = _lower_string_special(gen, receiver, method_name, args)
        if special is not None:
            return special
        if method_name in _STRING_CONVERSION_METHODS:
            callee, cast_to = _STRING_CONVERSION_METHODS[method_name]
            call_args = [receiver]
            if callee in {"strtof", "strtod"}:
                call_args.append(IRLiteral(text="NULL"))
            helper_ref = callee if callee.startswith("__btrc_") else None
            if helper_ref:
                gen.use_helper(helper_ref)
            call = IRCall(
                callee=callee,
                args=call_args,
                helper_ref=helper_ref,
            )
            if cast_to:
                return IRCast(target_type=CType(text=cast_to), expr=call)
            return call

    if (
        method_name == "toString"
        and receiver_type is not None
        and (receiver_type.base in gen.analyzed.enum_table or receiver_type.base in gen.analyzed.rich_enum_table)
    ):
        return _lower_to_string(
            gen,
            receiver,
            receiver_type,
            args,
        )
    return None


__all__ = ["lower_generic_builtin_method"]
