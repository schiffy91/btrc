"""Method call lowering: obj.method(args) → appropriate C call."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import CallExpr, FieldAccessExpr, Identifier
from ...string_methods import STRING_CONVERSIONS, STRING_METHODS
from ..nodes import (
    CType,
    IRCall,
    IRCast,
    IRExpr,
    IRFieldAccess,
    IRLiteral,
)
from .arguments import arg_names_for, lower_arg_values, order_args_for_params
from .expressions import lower_expr
from .sync_methods import lower_mutex_method, lower_thread_method
from .type_resolution import canonical_type
from .types import (
    is_string_type,
    mangle_generic_type,
)

if TYPE_CHECKING:
    from .generator import IRGenerator


# Dispatch views over the shared string-method specification.
_STRING_METHODS = {name: spec.helper for name, spec in STRING_METHODS.items() if spec.helper}
_STRING_TRACK_METHODS = {name for name, spec in STRING_METHODS.items() if spec.tracked}
_STRING_CONVERSION_METHODS = STRING_CONVERSIONS


def _lower_string_special(gen, obj, method_name, args):
    """Handle special string methods that don't map to helpers."""
    from ..nodes import IRBinOp

    if method_name == "equals":
        # s.equals(t) → strcmp(s, t) == 0
        cmp = IRCall(callee="strcmp", args=[obj] + args)
        return IRBinOp(left=cmp, op="==", right=IRLiteral(text="0"))
    if method_name in ("byteLen", "len", "length"):
        return IRCast(
            target_type=CType(text="int"),
            expr=IRCall(callee="strlen", args=[obj]),
        )
    return None


def lower_method_call(gen: IRGenerator, node: CallExpr) -> IRExpr:
    """Lower obj.method(args) to the appropriate C call."""
    assert isinstance(node.callee, FieldAccessExpr)
    if node.callee.optional:
        from .optional_calls import lower_optional_method_call

        return lower_optional_method_call(gen, node)
    obj_node = node.callee.obj
    method_name = node.callee.field

    # A callable field/property is an expression followed by a call, not a
    # method dispatch.  Resolve typedef aliases before deciding which ABI to
    # lower so ``obj.callback(args)`` invokes the stored function pointer.
    from .callable_fields import callable_field_signature

    if callable_field_signature(gen, node.callee) is not None:
        return IRCall(
            callee=lower_expr(gen, node.callee),
            args=lower_arg_values(gen, node.args),
        )

    # Rich enum constructor: Color.RGB(255, 0, 0) → Color_RGB(255, 0, 0)
    if (
        isinstance(obj_node, Identifier)
        and obj_node.name in gen.analyzed.rich_enum_table
        and not gen.local_ownership_declared(obj_node.name)
    ):
        args = lower_arg_values(gen, node.args)
        return IRCall(callee=f"{obj_node.name}_{method_name}", args=args)

    # Static method call: ClassName.method(args) → ClassName_method(args)
    if (
        isinstance(obj_node, Identifier)
        and obj_node.name in gen.analyzed.class_table
        and not gen.local_ownership_declared(obj_node.name)
    ):
        args = lower_arg_values(gen, node.args)
        cls_info = gen.analyzed.class_table[obj_node.name]
        method = cls_info.methods.get(method_name)
        if method:
            args = order_args_for_params(gen, method.params, node.args, arg_names_for(node, len(node.args)), args)
        return IRCall(callee=f"{obj_node.name}_{method_name}", args=args)

    obj = lower_expr(gen, obj_node)
    args = lower_arg_values(gen, node.args)
    obj_type = gen.analyzed.node_types.get(id(obj_node))
    resolved_obj_type = canonical_type(
        obj_type,
        gen.analyzed.typedef_table,
    )

    if is_string_type(resolved_obj_type) and method_name in _STRING_METHODS:
        return _lower_string_method(gen, obj, method_name, args)

    if is_string_type(resolved_obj_type):
        special = _lower_string_special(gen, obj, method_name, args)
        if special is not None:
            return special

    if is_string_type(resolved_obj_type) and method_name in _STRING_CONVERSION_METHODS:
        c_func, cast_to = _STRING_CONVERSION_METHODS[method_name]
        args = [obj]
        if c_func in {"strtof", "strtod"}:
            args.append(IRLiteral(text="NULL"))
        helper_ref = c_func if c_func.startswith("__btrc_") else None
        if helper_ref:
            gen.use_helper(helper_ref)
        call = IRCall(callee=c_func, args=args, helper_ref=helper_ref)
        if cast_to:
            return IRCast(target_type=CType(text=cast_to), expr=call)
        return call

    if is_string_type(resolved_obj_type) and method_name in ("length", "len", "byteLen"):
        return IRCast(
            target_type=CType(text="int"),
            expr=IRCall(callee="strlen", args=[obj]),
        )

    # toString: if the class defines its own, use class dispatch; else built-in
    if method_name == "toString":
        if resolved_obj_type and resolved_obj_type.base in gen.analyzed.class_table:
            cls_info = gen.analyzed.class_table[resolved_obj_type.base]
            if "toString" in cls_info.methods:
                pass  # fall through to class method dispatch below
            else:
                return _lower_to_string(gen, obj, resolved_obj_type, args)
        else:
            return _lower_to_string(gen, obj, resolved_obj_type, args)

    # Thread<T> methods: .join() → __btrc_thread_join with unboxing
    if resolved_obj_type and resolved_obj_type.base == "Thread" and resolved_obj_type.generic_args:
        return lower_thread_method(gen, obj, method_name, resolved_obj_type)

    # Mutex<T> methods: .get(), .set(), .destroy()
    if resolved_obj_type and resolved_obj_type.base == "Mutex" and resolved_obj_type.generic_args:
        return lower_mutex_method(
            gen,
            obj,
            method_name,
            resolved_obj_type,
            args,
        )

    # Class method: obj.method(args) → ClassName_method(obj, args)
    if resolved_obj_type and resolved_obj_type.base in gen.analyzed.class_table:
        cls_info = gen.analyzed.class_table[resolved_obj_type.base]
        # Use mangled name for generic class instances
        if resolved_obj_type.generic_args and cls_info.generic_params:
            callee_prefix = mangle_generic_type(
                resolved_obj_type.base,
                resolved_obj_type.generic_args,
            )
        else:
            callee_prefix = resolved_obj_type.base
        # Check if it's a property getter called as method
        if method_name in cls_info.properties:
            return IRCall(callee=f"{callee_prefix}_get_{method_name}", args=[obj])
        method = cls_info.methods.get(method_name)
        if method:
            args = order_args_for_params(gen, method.params, node.args, arg_names_for(node, len(node.args)), args)
            # Upcast args whose declared param type is a class type parameter
            # (e.g. Vector<Animal>.push(T) where T resolves to Animal): a
            # subclass element pointer must be cast to the resolved element type.
            if resolved_obj_type.generic_args and cls_info.generic_params and len(node.args) == len(args):
                args = _upcast_generic_method_args(
                    gen,
                    cls_info,
                    resolved_obj_type,
                    method,
                    node.args,
                    args,
                )
        # Generic method: dispatch to the monomorphized instance for the method
        # type args inferred at this call site (e.g. mapTo<string>).
        if method and getattr(method, "generic_params", None):
            method_args = gen.analyzed.generic_method_call_args.get(id(node))
            if method_args is not None:
                from .generics.methods_mono import generic_method_instance_name

                class_args = (
                    list(resolved_obj_type.generic_args)
                    if (resolved_obj_type.generic_args and cls_info.generic_params)
                    else []
                )
                callee = generic_method_instance_name(
                    resolved_obj_type.base,
                    class_args,
                    method_name,
                    method_args,
                )
                return IRCall(callee=callee, args=[obj] + args)
        return IRCall(
            callee=f"{callee_prefix}_{method_name}",
            args=[obj] + args,
        )

    # Fallback: direct field access call (function pointer or unknown)
    return IRCall(
        callee=IRFieldAccess(
            obj=obj,
            field=method_name,
            arrow=bool(resolved_obj_type and resolved_obj_type.pointer_depth > 0),
        ),
        args=args,
    )


def _lower_string_method(gen: IRGenerator, obj: IRExpr, method: str, args: list[IRExpr]) -> IRExpr:
    """Lower a string method call to a helper call."""
    helper = _STRING_METHODS[method]
    gen.use_helper(helper)
    call = IRCall(callee=helper, args=[obj] + args, helper_ref=helper)
    if method in _STRING_TRACK_METHODS:
        gen.use_helper("__btrc_str_track")
        return IRCall(callee="__btrc_str_track", args=[call], helper_ref="__btrc_str_track")
    return call


def _lower_to_string(gen: IRGenerator, obj: IRExpr, obj_type, args) -> IRExpr:
    """Lower .toString() for various types."""
    from ..nodes import IRTernary

    if obj_type is None:
        return IRCall(callee="__btrc_intToString", args=[obj], helper_ref="__btrc_intToString")
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
    helper = _to_string_helper(base)
    gen.use_helper(helper)
    gen.use_helper("__btrc_str_track")
    call = IRCall(callee=helper, args=[obj], helper_ref=helper)
    return IRCall(callee="__btrc_str_track", args=[call], helper_ref="__btrc_str_track")


def _to_string_helper(base: str) -> str:
    if base in {"unsigned long long", "unsigned long long int", "size_t"}:
        return "__btrc_ulongLongToString"
    if base in {"long long", "long long int", "signed long long", "signed long long int"}:
        return "__btrc_longLongToString"
    if base in {"unsigned long", "unsigned long int"}:
        return "__btrc_ulongToString"
    if base in {"long", "long int", "signed long", "signed long int"}:
        return "__btrc_longToString"
    if base in {"uint", "byte", "unsigned int", "unsigned short", "unsigned short int", "unsigned char"}:
        return "__btrc_uintToString"
    return {
        "float": "__btrc_floatToString",
        "double": "__btrc_doubleToString",
        "long double": "__btrc_longDoubleToString",
        "char": "__btrc_charToString",
    }.get(base, "__btrc_intToString")


def _upcast_generic_method_args(gen, cls_info, obj_type, method, ast_args, args):
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
