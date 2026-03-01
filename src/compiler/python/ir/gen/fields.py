"""Field access, indexing, and assignment lowering → IR."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    AssignExpr,
    BraceInitializer,
    FieldAccessExpr,
    Identifier,
    IndexExpr,
    SelfExpr,
)
from ..nodes import (
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRIf,
    IRIndex,
    IRLiteral,
    IRStmt,
    IRTernary,
    IRUnaryOp,
    IRVar,
)
from .types import is_generic_class_type, is_string_type, mangle_generic_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def _lower_field_access(gen: IRGenerator, node: FieldAccessExpr) -> IRExpr:
    """Lower field access, handling optional chaining and special types."""
    from .expressions import lower_expr

    obj = lower_expr(gen, node.obj)
    obj_type = gen.analyzed.node_types.get(id(node.obj))

    # String field access: s.len, s.length → (int)strlen(s)
    if is_string_type(obj_type) and node.field in ("len", "length"):
        return IRCast(target_type="int", expr=IRCall(callee="strlen", args=[obj]))

    # Generic class field access: coll.len → coll->len
    if (obj_type and is_generic_class_type(obj_type, gen.analyzed.class_table)
            and node.field in ("len", "length", "size")):
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
    from .expressions import lower_expr

    obj = lower_expr(gen, node.obj)
    index = lower_expr(gen, node.index)
    obj_type = gen.analyzed.node_types.get(id(node.obj))
    if obj_type and is_generic_class_type(obj_type, gen.analyzed.class_table):
        mangled = mangle_generic_type(obj_type.base, obj_type.generic_args)
        return IRCall(callee=f"{mangled}_get", args=[obj, index])
    return IRIndex(obj=obj, index=index)


def get_field_assign_arc_stmts(gen: IRGenerator, node: AssignExpr
                                ) -> tuple[list[IRStmt], list[IRStmt]]:
    """Return (pre_stmts, post_stmts) for ARC on field assignment.

    When assigning `obj.field = value` where field is a class-type:
    - pre_stmts: release old value (if old != NULL, --rc, destroy at zero)
    - post_stmts: rc++ on new value, register source var as managed

    Returns ([], []) if the field isn't a class type or value is null.
    """
    from ...ast_nodes import NewExpr, NullLiteral
    from .expressions import lower_expr
    if node.op != "=" or not isinstance(node.target, FieldAccessExpr):
        return [], []
    # Skip if assigning null — no ARC needed
    if isinstance(node.value, NullLiteral):
        return [], []
    obj_type = gen.analyzed.node_types.get(id(node.target.obj))
    if not obj_type or obj_type.base not in gen.analyzed.class_table:
        return [], []
    cls_info = gen.analyzed.class_table[obj_type.base]
    field_name = node.target.field
    # Look up the field type
    fd = cls_info.fields.get(field_name)
    if not fd or not fd.type:
        return [], []
    ft = fd.type
    # Only class-instance fields need keep/release
    if ft.base not in gen.analyzed.class_table:
        return [], []

    pre: list[IRStmt] = []
    post: list[IRStmt] = []

    obj_ir = lower_expr(gen, node.target.obj)
    old_field = IRFieldAccess(obj=obj_ir, field=field_name, arrow=True)

    # Determine destroy function for old value
    if ft.generic_args and is_generic_class_type(ft, gen.analyzed.class_table):
        mangled = mangle_generic_type(ft.base, ft.generic_args)
        field_cls = gen.analyzed.class_table.get(ft.base)
        dtor = "free" if field_cls and "free" in field_cls.methods else "destroy"
        destroy_fn = f"{mangled}_{dtor}"
    else:
        destroy_fn = f"{ft.base}_destroy"

    # PRE: release old field value
    pre.append(IRIf(
        condition=IRBinOp(left=old_field, op="!=", right=IRLiteral(text="NULL")),
        then_block=IRBlock(stmts=[IRIf(
            condition=IRBinOp(
                left=IRUnaryOp(op="--", operand=IRFieldAccess(
                    obj=old_field, field="__rc", arrow=True), prefix=True),
                op="<=", right=IRLiteral(text="0")),
            then_block=IRBlock(stmts=[IRExprStmt(
                expr=IRCall(callee=destroy_fn, args=[old_field]))]),
        )]),
    ))

    # POST: rc++ on new value — skip if value is `new` (already rc=1 from ctor)
    if not isinstance(node.value, NewExpr):
        value_ir = lower_expr(gen, node.value)
        post.append(IRExprStmt(expr=IRUnaryOp(
            op="++",
            operand=IRFieldAccess(obj=value_ir, field="__rc", arrow=True),
            prefix=False,
        )))

    # NOTE: We do NOT register the source variable as managed here.
    # Managed var registration happens at the CALL SITE via keep params,
    # not inside the method where the field assignment occurs.

    return pre, post


def _lower_assign(gen: IRGenerator, node: AssignExpr) -> IRExpr:
    """Lower assignment expression (compound assignments too)."""
    from .expressions import lower_expr

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
        if obj_type and is_generic_class_type(obj_type, gen.analyzed.class_table):
            mangled = mangle_generic_type(obj_type.base, obj_type.generic_args)
            obj = lower_expr(gen, node.target.obj)
            index = lower_expr(gen, node.target.index)
            value = lower_expr(gen, node.value)
            return IRCall(callee=f"{mangled}_set", args=[obj, index, value])

    # Empty {} or [] assigned to collection-typed field → collection_new()
    if node.op == "=" and isinstance(node.value, BraceInitializer) and not node.value.elements:
        target_type = gen.analyzed.node_types.get(id(node.target))
        if target_type and is_generic_class_type(target_type, gen.analyzed.class_table):
            mangled = mangle_generic_type(target_type.base, target_type.generic_args)
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
