"""Method call lowering: obj.method(args) → appropriate C call."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import CallExpr, FieldAccessExpr, Identifier
from ...string_methods import STRING_CONVERSIONS, STRING_METHODS
from ..nodes import (
    IRCall,
    IRCast,
    IRExpr,
    IRLiteral,
    IRVar,
)
from .arguments import arg_names_for, lower_arg_values, order_args_for_params
from .expressions import lower_expr
from .types import (
    is_string_type,
    mangle_generic_type,
    type_to_c,
)

if TYPE_CHECKING:
    from .generator import IRGenerator


# Dispatch views over the shared spec (src/compiler/python/string_methods.py):
# methods that map directly to runtime helpers, the subset whose helper
# returns a new heap string (needs str_track wrapping), and the conversion
# methods lowered to C stdlib calls.
_STRING_METHODS = {name: spec.helper
                   for name, spec in STRING_METHODS.items() if spec.helper}
_STRING_TRACK_METHODS = {name
                         for name, spec in STRING_METHODS.items() if spec.tracked}
_STRING_CONVERSION_METHODS = STRING_CONVERSIONS


def _lower_string_special(gen, obj, method_name, args):
    """Handle special string methods that don't map to helpers."""
    from ..nodes import IRBinOp
    if method_name == "equals":
        # s.equals(t) → strcmp(s, t) == 0
        cmp = IRCall(callee="strcmp", args=[obj] + args)
        return IRBinOp(left=cmp, op="==", right=IRLiteral(text="0"))
    if method_name in ("byteLen", "len", "length"):
        return IRCast(target_type="int", expr=IRCall(callee="strlen", args=[obj]))
    return None


def lower_method_call(gen: IRGenerator, node: CallExpr) -> IRExpr:
    """Lower obj.method(args) to the appropriate C call."""
    assert isinstance(node.callee, FieldAccessExpr)
    obj_node = node.callee.obj
    method_name = node.callee.field

    # Rich enum constructor: Color.RGB(255, 0, 0) → Color_RGB(255, 0, 0)
    if isinstance(obj_node, Identifier) and obj_node.name in gen.analyzed.rich_enum_table:
        args = lower_arg_values(gen, node.args)
        return IRCall(callee=f"{obj_node.name}_{method_name}", args=args)

    # Static method call: ClassName.method(args) → ClassName_method(args)
    if isinstance(obj_node, Identifier) and obj_node.name in gen.analyzed.class_table:
        args = lower_arg_values(gen, node.args)
        cls_info = gen.analyzed.class_table[obj_node.name]
        method = cls_info.methods.get(method_name)
        if method:
            args = order_args_for_params(
                gen, method.params, node.args,
                arg_names_for(node, len(node.args)), args)
        return IRCall(callee=f"{obj_node.name}_{method_name}", args=args)

    obj = lower_expr(gen, obj_node)
    args = lower_arg_values(gen, node.args)
    obj_type = gen.analyzed.node_types.get(id(obj_node))

    # String methods (helper-backed)
    if is_string_type(obj_type) and method_name in _STRING_METHODS:
        return _lower_string_method(gen, obj, method_name, args)

    # String special methods (equals, charLen, etc.)
    if is_string_type(obj_type):
        special = _lower_string_special(gen, obj, method_name, args)
        if special is not None:
            return special

    # String conversion methods (stdlib)
    if is_string_type(obj_type) and method_name in _STRING_CONVERSION_METHODS:
        c_func, cast_to = _STRING_CONVERSION_METHODS[method_name]
        call = IRCall(callee=c_func, args=[obj])
        if cast_to:
            return IRCast(target_type=cast_to, expr=call)
        return call

    # String length
    if is_string_type(obj_type) and method_name in ("length", "len", "byteLen"):
        return IRCast(target_type="int", expr=IRCall(callee="strlen", args=[obj]))

    # toString: if the class defines its own, use class dispatch; else built-in
    if method_name == "toString":
        if obj_type and obj_type.base in gen.analyzed.class_table:
            cls_info = gen.analyzed.class_table[obj_type.base]
            if "toString" in cls_info.methods:
                pass  # fall through to class method dispatch below
            else:
                return _lower_to_string(gen, obj, obj_type, args)
        else:
            return _lower_to_string(gen, obj, obj_type, args)

    # Thread<T> methods: .join() → __btrc_thread_join with unboxing
    if obj_type and obj_type.base == "Thread" and obj_type.generic_args:
        return _lower_thread_method(gen, obj, method_name, obj_type)

    # Mutex<T> methods: .get(), .set(), .destroy()
    if obj_type and obj_type.base == "Mutex" and obj_type.generic_args:
        return _lower_mutex_method(gen, obj, method_name, obj_type, args)

    # Class method: obj.method(args) → ClassName_method(obj, args)
    if obj_type and obj_type.base in gen.analyzed.class_table:
        cls_info = gen.analyzed.class_table[obj_type.base]
        # Use mangled name for generic class instances
        if obj_type.generic_args and cls_info.generic_params:
            callee_prefix = mangle_generic_type(obj_type.base, obj_type.generic_args)
        else:
            callee_prefix = obj_type.base
        # Check if it's a property getter called as method
        if method_name in cls_info.properties:
            return IRCall(callee=f"{callee_prefix}_get_{method_name}", args=[obj])
        method = cls_info.methods.get(method_name)
        if method:
            args = order_args_for_params(
                gen, method.params, node.args,
                arg_names_for(node, len(node.args)), args)
            # Upcast args whose declared param type is a class type parameter
            # (e.g. Vector<Animal>.push(T) where T resolves to Animal): a
            # subclass element pointer must be cast to the resolved element type.
            if (obj_type.generic_args and cls_info.generic_params
                    and len(node.args) == len(args)):
                args = _upcast_generic_method_args(
                    gen, cls_info, obj_type, method, node.args, args)
        # Generic method: dispatch to the monomorphized instance for the method
        # type args inferred at this call site (e.g. mapTo<string>).
        if method and getattr(method, "generic_params", None):
            method_args = gen.analyzed.generic_method_call_args.get(id(node))
            if method_args is not None:
                from .generics.methods_mono import generic_method_instance_name
                class_args = (list(obj_type.generic_args)
                              if (obj_type.generic_args and cls_info.generic_params)
                              else [])
                callee = generic_method_instance_name(
                    obj_type.base, class_args, method_name, method_args)
                return IRCall(callee=callee, args=[obj] + args)
        return IRCall(
            callee=f"{callee_prefix}_{method_name}",
            args=[obj] + args,
        )

    # Fallback: direct field access call (function pointer or unknown)
    return IRCall(
        callee=f"{_obj_text(obj)}.{method_name}" if not (obj_type and obj_type.pointer_depth > 0)
               else f"{_obj_text(obj)}->{method_name}",
        args=args,
    )


def _lower_string_method(gen: IRGenerator, obj: IRExpr,
                         method: str, args: list[IRExpr]) -> IRExpr:
    """Lower a string method call to a helper call."""
    helper = _STRING_METHODS[method]
    gen.use_helper(helper)
    call = IRCall(callee=helper, args=[obj] + args, helper_ref=helper)
    if method in _STRING_TRACK_METHODS:
        gen.use_helper("__btrc_str_track")
        return IRCall(callee="__btrc_str_track", args=[call],
                      helper_ref="__btrc_str_track")
    return call


def _lower_to_string(gen: IRGenerator, obj: IRExpr, obj_type, args) -> IRExpr:
    """Lower .toString() for various types."""
    from ..nodes import IRTernary
    if obj_type is None:
        return IRCall(callee="__btrc_intToString", args=[obj],
                      helper_ref="__btrc_intToString")
    base = obj_type.base
    # Bool → ternary: val ? "true" : "false"
    if base == "bool":
        return IRTernary(
            condition=obj,
            true_expr=IRLiteral(text='"true"'),
            false_expr=IRLiteral(text='"false"'),
        )
    # Enum → EnumName_toString(val)
    if base in gen.analyzed.enum_table:
        return IRCall(callee=f"{base}_toString", args=[obj])
    helper_map = {
        "int": "__btrc_intToString",
        "long": "__btrc_longToString",
        "float": "__btrc_floatToString",
        "double": "__btrc_doubleToString",
        "char": "__btrc_charToString",
    }
    helper = helper_map.get(base, "__btrc_intToString")
    gen.use_helper(helper)
    gen.use_helper("__btrc_str_track")
    call = IRCall(callee=helper, args=[obj], helper_ref=helper)
    return IRCall(callee="__btrc_str_track", args=[call],
                  helper_ref="__btrc_str_track")


_THREAD_PRIMITIVE_TYPES = {"int", "float", "double", "char", "bool", "short", "long"}


def _lower_thread_method(gen, obj, method_name, obj_type):
    """Lower Thread<T> method calls (.join())."""
    if method_name == "join":
        gen.use_helper("__btrc_thread_join")
        ret_type = obj_type.generic_args[0] if obj_type.generic_args else None
        join_call = IRCall(
            callee="__btrc_thread_join", args=[obj],
            helper_ref="__btrc_thread_join",
        )
        if ret_type is None or ret_type.base == "void":
            return join_call
        c_type = type_to_c(ret_type)
        if ret_type.base in _THREAD_PRIMITIVE_TYPES and not ret_type.generic_args:
            return IRCast(target_type=c_type,
                          expr=IRCast(target_type="intptr_t", expr=join_call))
        else:
            return IRCast(target_type=c_type, expr=join_call)
    # Unknown Thread method — fallback
    return IRCall(callee=f"__btrc_thread_{method_name}", args=[obj])


def _lower_mutex_method(gen, obj, method_name, obj_type, args):
    """Lower Mutex<T> method calls (.get(), .set(), .destroy())."""
    val_type = obj_type.generic_args[0] if obj_type.generic_args else None
    if method_name == "get":
        gen.use_helper("__btrc_mutex_val_get")
        get_call = IRCall(callee="__btrc_mutex_val_get", args=[obj],
                          helper_ref="__btrc_mutex_val_get")
        if val_type and val_type.base in _THREAD_PRIMITIVE_TYPES and not val_type.generic_args:
            c_type = type_to_c(val_type)
            return IRCast(target_type=c_type,
                          expr=IRCast(target_type="intptr_t", expr=get_call))
        elif val_type:
            c_type = type_to_c(val_type)
            return IRCast(target_type=c_type, expr=get_call)
        return get_call
    if method_name == "set":
        gen.use_helper("__btrc_mutex_val_set")
        if args:
            if val_type and val_type.base in _THREAD_PRIMITIVE_TYPES and not val_type.generic_args:
                boxed = IRCast(target_type="void*",
                               expr=IRCast(target_type="intptr_t", expr=args[0]))
            else:
                boxed = IRCast(target_type="void*", expr=args[0])
            return IRCall(callee="__btrc_mutex_val_set", args=[obj, boxed],
                          helper_ref="__btrc_mutex_val_set")
        return IRCall(callee="__btrc_mutex_val_set", args=[obj] + args,
                      helper_ref="__btrc_mutex_val_set")
    if method_name == "destroy":
        gen.use_helper("__btrc_mutex_val_destroy")
        return IRCall(callee="__btrc_mutex_val_destroy", args=[obj],
                      helper_ref="__btrc_mutex_val_destroy")
    # Unknown Mutex method — fallback
    return IRCall(callee=f"__btrc_mutex_val_{method_name}", args=[obj] + args)


def _upcast_generic_method_args(gen, cls_info, obj_type, method,
                                ast_args, args):
    """Upcast Derived→Base args for a generic class method.

    The method's declared param types reference the class type parameters (e.g.
    ``push(T val)``). Resolve each type parameter to the receiver's corresponding
    generic argument, then apply a Derived→Base upcast keyed on that resolved
    type. Only positional, non-defaulted calls are handled (``len`` already
    checked by the caller); arg ``i`` aligns with method param ``i``.
    """
    from .upcast import upcast_class_pointer
    type_map = dict(zip(cls_info.generic_params, obj_type.generic_args))
    result = list(args)
    for i, ast_arg in enumerate(ast_args):
        if i >= len(method.params):
            break
        param_type = method.params[i].type
        if not param_type:
            continue
        resolved = type_map.get(param_type.base)
        if resolved is None:
            continue
        source_type = gen.analyzed.node_types.get(id(ast_arg))
        result[i] = upcast_class_pointer(gen, resolved, source_type, result[i])
    return result


def _obj_text(expr: IRExpr) -> str:
    """Get text from simple expressions."""
    if isinstance(expr, IRVar):
        return expr.name
    if isinstance(expr, IRLiteral):
        return expr.text
    return "/* complex obj */"
