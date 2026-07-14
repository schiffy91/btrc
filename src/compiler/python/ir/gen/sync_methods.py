"""Lowering for Thread<T> and Mutex<T> method calls."""

from ..nodes import IRCall
from .errors import CodegenError
from .mutex_values import (
    consume_mutex_handle,
    get_mutex_value,
    set_mutex_value,
)
from .thread_values import consume_thread_handle, unbox_thread_result


def lower_thread_method(gen, obj, method_name, obj_type):
    if method_name != "join":
        return IRCall(callee=f"__btrc_thread_{method_name}", args=[obj])
    gen.use_helper("__btrc_thread_join")
    return_type = obj_type.generic_args[0] if obj_type.generic_args else None
    call = IRCall(
        callee="__btrc_thread_join",
        args=[consume_thread_handle(gen, obj)],
        helper_ref="__btrc_thread_join",
    )
    if return_type is None or return_type.base == "void":
        return call
    return unbox_thread_result(gen, call, return_type)


def lower_mutex_method(gen, obj, method_name, obj_type, args):
    value_type = obj_type.generic_args[0] if obj_type.generic_args else None
    if method_name == "get":
        return get_mutex_value(gen, obj, value_type)
    if method_name == "set":
        if args:
            return set_mutex_value(gen, obj, args[0], value_type)
        raise CodegenError("Mutex.set() requires one value")
    if method_name == "destroy":
        gen.use_helper("__btrc_mutex_val_destroy")
        return IRCall(
            callee="__btrc_mutex_val_destroy",
            args=[consume_mutex_handle(gen, obj)],
            helper_ref="__btrc_mutex_val_destroy",
        )
    return IRCall(callee=f"__btrc_mutex_val_{method_name}", args=[obj] + args)
