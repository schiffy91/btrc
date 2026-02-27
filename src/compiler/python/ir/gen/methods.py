"""Method call lowering: obj.method(args) → appropriate C call."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import CallExpr, FieldAccessExpr, Identifier, TypeExpr
from ..nodes import (
    IRAddressOf, IRCall, IRExpr, IRFieldAccess, IRLiteral, IRVar,
)
from .types import (
    is_string_type, is_collection_type, mangle_generic_type, type_to_c,
)
from .expressions import lower_expr

if TYPE_CHECKING:
    from .generator import IRGenerator


# String methods that map directly to runtime helpers
_STRING_METHODS = {
    "trim": "__btrc_trim",
    "toUpper": "__btrc_toUpper",
    "toLower": "__btrc_toLower",
    "substring": "__btrc_substring",
    "charAt": "__btrc_charAt",
    "indexOf": "__btrc_indexOf",
    "lastIndexOf": "__btrc_lastIndexOf",
    "replace": "__btrc_replace",
    "split": "__btrc_split",
    "repeat": "__btrc_repeat",
    "reverse": "__btrc_reverse",
    "isEmpty": "__btrc_isEmpty",
    "removePrefix": "__btrc_removePrefix",
    "removeSuffix": "__btrc_removeSuffix",
    "startsWith": "__btrc_startsWith",
    "endsWith": "__btrc_endsWith",
    "contains": "__btrc_strContains",
    "capitalize": "__btrc_capitalize",
    "title": "__btrc_title",
    "swapCase": "__btrc_swapCase",
    "padLeft": "__btrc_padLeft",
    "padRight": "__btrc_padRight",
    "center": "__btrc_center",
    "lstrip": "__btrc_lstrip",
    "rstrip": "__btrc_rstrip",
    "count": "__btrc_count",
    "find": "__btrc_find",
    "isDigit": "__btrc_isDigitStr",
    "isAlpha": "__btrc_isAlphaStr",
    "isBlank": "__btrc_isBlank",
    "isUpper": "__btrc_isUpper",
    "isLower": "__btrc_isLower",
    "isAlnum": "__btrc_isAlnumStr",
    "zfill": "__btrc_zfill",
    "join": "__btrc_join",
    # Aliases (some tests use the helper name directly)
    "isDigitStr": "__btrc_isDigitStr",
    "isAlphaStr": "__btrc_isAlphaStr",
    "isAlnumStr": "__btrc_isAlnumStr",
}

# String methods that return new strings (need str_track wrapping)
_STRING_TRACK_METHODS = {
    "trim", "toUpper", "toLower", "substring", "replace", "repeat",
    "reverse", "removePrefix", "removeSuffix", "capitalize", "title",
    "swapCase", "padLeft", "padRight", "center", "lstrip", "rstrip",
    "zfill", "join",
}

# String conversion methods (stdlib calls, no runtime helpers needed)
_STRING_CONVERSION_METHODS = {
    "toInt": ("atoi", "int"),
    "toFloat": ("atof", "float"),
    "toDouble": ("atof", None),
    "toLong": ("atol", None),
}


def _lower_string_special(gen, obj, method_name, args):
    """Handle special string methods that don't map to helpers."""
    from ..nodes import IRCast, IRBinOp
    if method_name == "equals":
        # s.equals(t) → strcmp(s, t) == 0
        cmp = IRCall(callee="strcmp", args=[obj] + args)
        return IRBinOp(left=cmp, op="==", right=IRLiteral(text="0"))
    if method_name in ("byteLen", "len", "length"):
        return IRCast(target_type="int", expr=IRCall(callee="strlen", args=[obj]))
    if method_name == "charLen":
        gen.use_helper("__btrc_charLen")
        return IRCall(callee="__btrc_charLen", args=[obj], helper_ref="__btrc_charLen")
    return None


def lower_method_call(gen: IRGenerator, node: CallExpr) -> IRExpr:
    """Lower obj.method(args) to the appropriate C call."""
    from ..nodes import IRCast
    assert isinstance(node.callee, FieldAccessExpr)
    obj_node = node.callee.obj
    method_name = node.callee.field

    # Rich enum constructor: Color.RGB(255, 0, 0) → Color_RGB(255, 0, 0)
    if isinstance(obj_node, Identifier) and obj_node.name in gen.analyzed.rich_enum_table:
        args = [lower_expr(gen, a) for a in node.args]
        return IRCall(callee=f"{obj_node.name}_{method_name}", args=args)

    # Static method call: ClassName.method(args) → ClassName_method(args)
    if isinstance(obj_node, Identifier) and obj_node.name in gen.analyzed.class_table:
        args = [lower_expr(gen, a) for a in node.args]
        return IRCall(callee=f"{obj_node.name}_{method_name}", args=args)

    obj = lower_expr(gen, obj_node)
    args = [lower_expr(gen, a) for a in node.args]
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

    # toString on numeric types
    if method_name == "toString":
        return _lower_to_string(gen, obj, obj_type, args)

    # Collection methods (List, Map, Set)
    if obj_type and is_collection_type(obj_type):
        return _lower_collection_method(gen, obj, obj_type, method_name, args)

    # User class method: obj.method(args) → ClassName_method(obj, args)
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


def _lower_collection_method(gen: IRGenerator, obj: IRExpr,
                             obj_type: TypeExpr, method: str,
                             args: list[IRExpr]) -> IRExpr:
    """Lower a collection method call."""
    base = obj_type.base
    mangled = mangle_generic_type(base, obj_type.generic_args)

    # Size/length methods
    if method in ("size", "length", "len"):
        return IRFieldAccess(obj=obj, field="len", arrow=True)

    # isEmpty
    if method == "isEmpty":
        from ..nodes import IRBinOp
        return IRBinOp(
            left=IRFieldAccess(obj=obj, field="len", arrow=True),
            op="==", right=IRLiteral(text="0"),
        )

    # Most collection methods are mangled: btrc_List_int_push(obj, args)
    return IRCall(
        callee=f"{mangled}_{method}",
        args=[obj] + args,
    )


def _obj_text(expr: IRExpr) -> str:
    """Get text from simple expressions."""
    if isinstance(expr, IRVar):
        return expr.name
    if isinstance(expr, IRLiteral):
        return expr.text
    return "/* complex obj */"
