"""Expression lowering: AST expr → IRExpr."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import (
    AssignExpr, BinaryExpr, BoolLiteral, BraceInitializer, CallExpr,
    CastExpr, CharLiteral, FieldAccessExpr, FloatLiteral, FStringExpr,
    FStringLiteral, FStringText, Identifier, IndexExpr, IntLiteral,
    LambdaExpr, ListLiteral, MapEntry, MapLiteral, NewExpr, NullLiteral,
    SelfExpr, SizeofExpr, SizeofExprOp, SizeofType, StringLiteral,
    SuperExpr, TernaryExpr, TupleLiteral, TypeExpr, UnaryExpr,
)
from ..nodes import (
    IRAddressOf, IRBinOp, IRCall, IRCast, IRDeref, IRExpr,
    IRFieldAccess, IRIndex, IRLiteral, IRRawExpr, IRSizeof,
    IRTernary, IRUnaryOp, IRVar,
)
from .types import type_to_c, is_string_type, is_numeric_type, is_collection_type, format_spec_for_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_expr(gen: IRGenerator, node) -> IRExpr:
    """Lower an AST expression node to an IRExpr."""
    if node is None:
        return IRLiteral(text="0")

    if isinstance(node, IntLiteral):
        raw = node.raw or str(node.value)
        # Convert btrc octal 0o... to C octal 0...
        if raw.startswith("0o") or raw.startswith("0O"):
            return IRLiteral(text="0" + raw[2:])
        return IRLiteral(text=raw)

    if isinstance(node, FloatLiteral):
        return IRLiteral(text=node.raw or str(node.value))

    if isinstance(node, StringLiteral):
        # Parser stores value WITH quotes, e.g. '"hello"'
        return IRLiteral(text=node.value)

    if isinstance(node, CharLiteral):
        # Parser stores value WITH quotes, e.g. "'A'"
        return IRLiteral(text=node.value)

    if isinstance(node, BoolLiteral):
        return IRLiteral(text="true" if node.value else "false")

    if isinstance(node, NullLiteral):
        return IRLiteral(text="NULL")

    if isinstance(node, Identifier):
        return _lower_identifier(gen, node)

    if isinstance(node, SelfExpr):
        return IRVar(name="self")

    if isinstance(node, SuperExpr):
        return IRVar(name="self")

    if isinstance(node, BinaryExpr):
        return _lower_binary(gen, node)

    if isinstance(node, UnaryExpr):
        return _lower_unary(gen, node)

    if isinstance(node, CallExpr):
        return _lower_call(gen, node)

    if isinstance(node, FieldAccessExpr):
        return _lower_field_access(gen, node)

    if isinstance(node, IndexExpr):
        return _lower_index(gen, node)

    if isinstance(node, AssignExpr):
        return _lower_assign(gen, node)

    if isinstance(node, CastExpr):
        return IRCast(target_type=type_to_c(node.target_type),
                      expr=lower_expr(gen, node.expr))

    if isinstance(node, SizeofExpr):
        return _lower_sizeof(gen, node)

    if isinstance(node, TernaryExpr):
        return IRTernary(condition=lower_expr(gen, node.condition),
                         true_expr=lower_expr(gen, node.true_expr),
                         false_expr=lower_expr(gen, node.false_expr))

    if isinstance(node, NewExpr):
        from .classes import lower_new_expr
        return lower_new_expr(gen, node)

    if isinstance(node, ListLiteral):
        from .collections import lower_list_literal
        return lower_list_literal(gen, node)

    if isinstance(node, MapLiteral):
        from .collections import lower_map_literal
        return lower_map_literal(gen, node)

    if isinstance(node, FStringLiteral):
        from .fstrings import lower_fstring
        return lower_fstring(gen, node)

    if isinstance(node, LambdaExpr):
        from .lambdas import lower_lambda
        return lower_lambda(gen, node)

    if isinstance(node, TupleLiteral):
        return _lower_tuple(gen, node)

    if isinstance(node, BraceInitializer):
        if not node.elements:
            # Check if analyzer annotated this with a collection type
            node_type = gen.analyzed.node_types.get(id(node))
            if node_type and is_collection_type(node_type):
                from .types import mangle_generic_type
                mangled = mangle_generic_type(node_type.base, node_type.generic_args)
                return IRCall(callee=f"{mangled}_new", args=[])
            # Empty brace init → NULL for pointer types, {0} for structs
            return IRLiteral(text="NULL")
        elems = ", ".join(_expr_text(lower_expr(gen, e)) for e in node.elements)
        return IRRawExpr(text=f"{{{elems}}}")

    return IRLiteral(text=f"/* unhandled expr: {type(node).__name__} */")


def _lower_identifier(gen: IRGenerator, node: Identifier) -> IRExpr:
    """Lower an identifier, handling enum values."""
    name = node.name
    # Check if this is an enum member (e.g., RED → Color_RED)
    for enum_name, values in gen.analyzed.enum_table.items():
        if name in values:
            return IRLiteral(text=f"{enum_name}_{name}")
    return IRVar(name=name)


def _lower_binary(gen: IRGenerator, node: BinaryExpr) -> IRExpr:
    """Lower a binary expression, handling special operators."""
    left = lower_expr(gen, node.left)
    right = lower_expr(gen, node.right)

    # Infer types for special handling
    left_type = gen.analyzed.node_types.get(id(node.left))
    right_type = gen.analyzed.node_types.get(id(node.right))

    op = node.op

    # String concatenation: a + b → __btrc_str_track(__btrc_strcat(a, b))
    if op == "+" and is_string_type(left_type):
        gen.use_helper("__btrc_strcat")
        gen.use_helper("__btrc_str_track")
        cat = IRCall(callee="__btrc_strcat", args=[left, right],
                     helper_ref="__btrc_strcat")
        return IRCall(callee="__btrc_str_track", args=[cat],
                      helper_ref="__btrc_str_track")

    # String comparison: a == b → strcmp(a, b) == 0
    if op in ("==", "!=") and is_string_type(left_type):
        cmp = IRCall(callee="strcmp", args=[left, right])
        cmp_val = "0" if op == "==" else "0"
        cmp_op = "==" if op == "==" else "!="
        return IRBinOp(left=cmp, op=cmp_op, right=IRLiteral(text="0"))

    # Division: a / b → __btrc_div_int(a, b)
    if op == "/" and is_numeric_type(left_type):
        if left_type and left_type.base in ("float", "double"):
            gen.use_helper("__btrc_div_double")
            return IRCall(callee="__btrc_div_double", args=[left, right],
                          helper_ref="__btrc_div_double")
        gen.use_helper("__btrc_div_int")
        return IRCall(callee="__btrc_div_int", args=[left, right],
                      helper_ref="__btrc_div_int")

    # Modulo: a % b → __btrc_mod_int(a, b)
    if op == "%" and is_numeric_type(left_type):
        gen.use_helper("__btrc_mod_int")
        return IRCall(callee="__btrc_mod_int", args=[left, right],
                      helper_ref="__btrc_mod_int")

    # Null coalescing: a ?? b → (a != NULL ? a : b)
    if op == "??":
        return IRTernary(
            condition=IRBinOp(left=left, op="!=", right=IRLiteral(text="NULL")),
            true_expr=left,
            false_expr=right,
        )

    # Operator overloading on class types: a + b → ClassName___add__(a, b)
    if left_type and left_type.base in gen.analyzed.class_table:
        op_map = {
            "+": "__add__", "-": "__sub__", "*": "__mul__",
            "/": "__div__", "%": "__mod__",
            "==": "__eq__", "!=": "__ne__",
            "<": "__lt__", ">": "__gt__",
            "<=": "__le__", ">=": "__ge__",
        }
        if op in op_map:
            cls_info = gen.analyzed.class_table[left_type.base]
            magic = op_map[op]
            if magic in cls_info.methods:
                return IRCall(callee=f"{left_type.base}_{magic}",
                              args=[left, right])

    return IRBinOp(left=left, op=op, right=right)


def _lower_unary(gen: IRGenerator, node: UnaryExpr) -> IRExpr:
    operand = lower_expr(gen, node.operand)
    op = node.op
    if op == "&":
        return IRAddressOf(expr=operand)
    if op == "*":
        return IRDeref(expr=operand)
    # Operator overloading: -obj where obj is class with __neg__
    if op == "-" and node.prefix:
        operand_type = gen.analyzed.node_types.get(id(node.operand))
        if operand_type and operand_type.base in gen.analyzed.class_table:
            cls_info = gen.analyzed.class_table[operand_type.base]
            if "__neg__" in cls_info.methods:
                return IRCall(callee=f"{operand_type.base}___neg__",
                              args=[operand])
    return IRUnaryOp(op=op, operand=operand, prefix=node.prefix)


def _lower_call(gen: IRGenerator, node: CallExpr) -> IRExpr:
    """Lower a function/method call."""
    # Method call: obj.method(args)
    if isinstance(node.callee, FieldAccessExpr):
        from .methods import lower_method_call
        return lower_method_call(gen, node)

    # Regular function call
    if isinstance(node.callee, Identifier):
        name = node.callee.name
        args = [lower_expr(gen, a) for a in node.args]

        # Constructor call: ClassName(args) where ClassName is a known class
        if name in gen.analyzed.class_table:
            return _lower_constructor_call(gen, name, node.args)

        # Built-in functions
        if name == "print":
            return _lower_print(gen, node.args)
        if name == "printf":
            return IRCall(callee="printf", args=args)
        if name == "sizeof":
            if node.args:
                return IRSizeof(operand=_expr_text(args[0]))
            return IRSizeof(operand="void")
        if name == "len":
            if node.args:
                arg_type = gen.analyzed.node_types.get(id(node.args[0]))
                if arg_type and is_string_type(arg_type):
                    return IRCast(target_type="int",
                                  expr=IRCall(callee="strlen", args=args))
                return IRFieldAccess(obj=args[0], field="len", arrow=True)

        # Fill in default parameter values if call has fewer args than params
        args = _fill_defaults(gen, name, node.args, args)

        return IRCall(callee=name, args=args)

    # Generic/complex callee
    args = [lower_expr(gen, a) for a in node.args]
    callee_text = _expr_text(lower_expr(gen, node.callee))
    return IRCall(callee=callee_text, args=args)


def _fill_defaults(gen: IRGenerator, name: str, ast_args: list,
                    ir_args: list[IRExpr]) -> list[IRExpr]:
    """Fill in default parameter values for function calls with missing args."""
    func_decl = gen.analyzed.function_table.get(name)
    if not func_decl or not func_decl.params:
        return ir_args
    if len(ir_args) >= len(func_decl.params):
        return ir_args
    # Fill missing args with defaults
    result = list(ir_args)
    for i in range(len(ir_args), len(func_decl.params)):
        param = func_decl.params[i]
        if param.default is not None:
            result.append(lower_expr(gen, param.default))
        else:
            result.append(IRLiteral(text="0"))
    return result


def _lower_constructor_call(gen: IRGenerator, class_name: str,
                            args: list) -> IRExpr:
    """Lower ClassName(args) → ClassName_new(args) or btrc_ClassName_T_new(args)."""
    from .types import mangle_generic_type
    ir_args = [lower_expr(gen, a) for a in args]
    cls_info = gen.analyzed.class_table.get(class_name)
    if cls_info:
        # Fill constructor defaults
        if cls_info.constructor and cls_info.constructor.params:
            ctor_params = cls_info.constructor.params
            if len(ir_args) < len(ctor_params):
                for i in range(len(ir_args), len(ctor_params)):
                    p = ctor_params[i]
                    if p.default is not None:
                        ir_args.append(lower_expr(gen, p.default))
                    else:
                        ir_args.append(IRLiteral(text="0"))
        # Generic class: need to find mangled name
        if cls_info.generic_params:
            # Try to infer from context (node_types may have the resolved type)
            # For now, return mangled_new if we can find the instance
            # The caller will need to patch this in VarDecl context
            pass
    return IRCall(callee=f"{class_name}_new", args=ir_args)


def _lower_print(gen: IRGenerator, args: list) -> IRExpr:
    """Lower print(...) to printf with appropriate format string."""
    if not args:
        return IRCall(callee="printf", args=[IRLiteral(text='"\\n"')])

    parts = []
    ir_args = []
    for i, arg in enumerate(args):
        ir_arg = lower_expr(gen, arg)
        arg_type = gen.analyzed.node_types.get(id(arg))
        fmt = format_spec_for_type(arg_type)

        if arg_type and arg_type.base == "bool":
            # bool → ternary: val ? "true" : "false"
            ir_arg = IRTernary(
                condition=ir_arg,
                true_expr=IRLiteral(text='"true"'),
                false_expr=IRLiteral(text='"false"'),
            )
            fmt = "%s"

        parts.append(fmt)
        ir_args.append(ir_arg)

    fmt_str = " ".join(parts) + "\\n"
    return IRCall(callee="printf",
                  args=[IRLiteral(text=f'"{fmt_str}"')] + ir_args)


def _lower_field_access(gen: IRGenerator, node: FieldAccessExpr) -> IRExpr:
    """Lower field access, handling optional chaining and special types."""
    obj = lower_expr(gen, node.obj)
    obj_type = gen.analyzed.node_types.get(id(node.obj))

    # String field access: s.len, s.length → (int)strlen(s)
    if is_string_type(obj_type) and node.field in ("len", "length"):
        return IRCast(target_type="int", expr=IRCall(callee="strlen", args=[obj]))

    # Collection field access: list.len → list->len
    if obj_type and is_collection_type(obj_type) and node.field in ("len", "length", "size"):
        return IRFieldAccess(obj=obj, field="len", arrow=True)

    # Rich enum variant tag: Color.RGB → Color_RGB_TAG
    if isinstance(node.obj, Identifier) and node.obj.name in gen.analyzed.rich_enum_table:
        return IRVar(name=f"{node.obj.name}_{node.field}_TAG")

    # Static method/field on a class name: ClassName.field
    if isinstance(node.obj, Identifier) and node.obj.name in gen.analyzed.class_table:
        # This is a static reference — will be handled by method call lowering
        # if it's a call, but for field-only access emit ClassName_field
        return IRVar(name=f"{node.obj.name}_{node.field}")

    # Property access on class instances
    if obj_type and obj_type.base in gen.analyzed.class_table:
        cls_info = gen.analyzed.class_table[obj_type.base]
        # Use mangled name for generic class instances
        if obj_type.generic_args and cls_info.generic_params:
            from .types import mangle_generic_type
            callee_prefix = mangle_generic_type(obj_type.base, obj_type.generic_args)
        else:
            callee_prefix = obj_type.base
        if node.field in cls_info.properties:
            # self.prop inside the class → use backing field directly
            if isinstance(node.obj, SelfExpr):
                return IRFieldAccess(obj=obj, field=f"_prop_{node.field}", arrow=True)
            return IRCall(callee=f"{callee_prefix}_get_{node.field}", args=[obj])

    if node.optional:
        # a?.b → (a != NULL ? a->b : default)
        access = IRFieldAccess(obj=obj, field=node.field, arrow=True)
        return IRTernary(
            condition=IRBinOp(left=obj, op="!=",
                              right=IRLiteral(text="NULL")),
            true_expr=access,
            false_expr=IRLiteral(text="0"),
        )

    arrow = node.arrow
    # Determine if we need -> based on the object type
    if obj_type and (obj_type.pointer_depth > 0 or
                     obj_type.base in gen.analyzed.class_table):
        arrow = True

    return IRFieldAccess(obj=obj, field=node.field, arrow=arrow)


def _lower_index(gen: IRGenerator, node: IndexExpr) -> IRExpr:
    """Lower index expression: list[i] → List_get(list, i), map[k] → Map_get(map, k)."""
    from .types import mangle_generic_type
    obj = lower_expr(gen, node.obj)
    index = lower_expr(gen, node.index)
    obj_type = gen.analyzed.node_types.get(id(node.obj))
    if obj_type and is_collection_type(obj_type):
        mangled = mangle_generic_type(obj_type.base, obj_type.generic_args)
        return IRCall(callee=f"{mangled}_get", args=[obj, index])
    return IRIndex(obj=obj, index=index)


def _lower_assign(gen: IRGenerator, node: AssignExpr) -> IRExpr:
    """Lower assignment expression (compound assignments too)."""
    from .types import mangle_generic_type

    # Property setter: obj.prop = value → ClassName_set_prop(obj, value)
    if node.op == "=" and isinstance(node.target, FieldAccessExpr):
        obj_type = gen.analyzed.node_types.get(id(node.target.obj))
        if obj_type and obj_type.base in gen.analyzed.class_table:
            cls_info = gen.analyzed.class_table[obj_type.base]
            if node.target.field in cls_info.properties:
                obj = lower_expr(gen, node.target.obj)
                value = lower_expr(gen, node.value)
                # self.prop = value inside class → backing field
                if isinstance(node.target.obj, SelfExpr):
                    backing = IRFieldAccess(obj=obj,
                                            field=f"_prop_{node.target.field}",
                                            arrow=True)
                    return IRBinOp(left=backing, op="=", right=value)
                return IRCall(
                    callee=f"{obj_type.base}_set_{node.target.field}",
                    args=[obj, value])

    # Collection index assignment: list[i] = value → List_set(list, i, value)
    if node.op == "=" and isinstance(node.target, IndexExpr):
        obj_type = gen.analyzed.node_types.get(id(node.target.obj))
        if obj_type and is_collection_type(obj_type):
            mangled = mangle_generic_type(obj_type.base, obj_type.generic_args)
            obj = lower_expr(gen, node.target.obj)
            index = lower_expr(gen, node.target.index)
            value = lower_expr(gen, node.value)
            return IRCall(callee=f"{mangled}_set", args=[obj, index, value])

    # Empty {} or [] assigned to collection-typed field → collection_new()
    if node.op == "=" and isinstance(node.value, BraceInitializer) and not node.value.elements:
        target_type = gen.analyzed.node_types.get(id(node.target))
        if target_type and is_collection_type(target_type):
            from .types import mangle_generic_type as _mgt
            mangled = _mgt(target_type.base, target_type.generic_args)
            target = lower_expr(gen, node.target)
            return IRBinOp(left=target, op="=",
                           right=IRCall(callee=f"{mangled}_new", args=[]))

    target = lower_expr(gen, node.target)
    value = lower_expr(gen, node.value)

    # String += → target = __btrc_str_track(__btrc_strcat(target, value))
    if node.op == "+=" and is_string_type(gen.analyzed.node_types.get(id(node.target))):
        gen.use_helper("__btrc_strcat")
        gen.use_helper("__btrc_str_track")
        cat = IRCall(callee="__btrc_strcat", args=[target, value],
                     helper_ref="__btrc_strcat")
        tracked = IRCall(callee="__btrc_str_track", args=[cat],
                         helper_ref="__btrc_str_track")
        return IRBinOp(left=target, op="=", right=tracked)

    if node.op == "=":
        return IRBinOp(left=target, op="=", right=value)
    # Compound: +=, -=, *=, etc.
    return IRBinOp(left=target, op=node.op, right=value)


def _lower_sizeof(gen: IRGenerator, node: SizeofExpr) -> IRExpr:
    if isinstance(node.operand, SizeofType):
        return IRSizeof(operand=type_to_c(node.operand.type))
    elif isinstance(node.operand, SizeofExprOp):
        inner = lower_expr(gen, node.operand.expr)
        return IRSizeof(operand=_expr_text(inner))
    return IRSizeof(operand="void")


def _lower_tuple(gen: IRGenerator, node: TupleLiteral) -> IRExpr:
    """Lower tuple literal to C struct initializer."""
    from .types import mangle_tuple_type
    from .statements import _quick_text
    elems = [lower_expr(gen, e) for e in node.elements]
    node_type = gen.analyzed.node_types.get(id(node))
    if node_type and node_type.generic_args:
        mangled = mangle_tuple_type(node_type)
    else:
        # Fallback: construct from element count
        mangled = f"btrc_Tuple_{'_'.join(['int'] * len(node.elements))}"
    field_inits = ", ".join(f"._{i} = {_quick_text(e)}" for i, e in enumerate(elems))
    return IRRawExpr(text=f"({mangled}){{{field_inits}}}")


def _expr_text(expr: IRExpr) -> str:
    """Quick helper to get text representation of simple expressions."""
    if isinstance(expr, IRLiteral):
        return expr.text
    if isinstance(expr, IRVar):
        return expr.name
    if isinstance(expr, IRRawExpr):
        return expr.text
    # Fallback — the emitter will handle complex expressions
    return f"/* complex expr */"
