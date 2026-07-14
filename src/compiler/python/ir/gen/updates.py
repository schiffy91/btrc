"""Shared assignment and increment/decrement lowering over lvalue plans."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ...ast_nodes import AssignExpr, FieldAccessExpr, Identifier, TypeExpr, UnaryExpr
from ..nodes import (
    IRAddressOf,
    IRBinOp,
    IRCommaExpr,
    IRExpr,
    IRFieldAccess,
    IRLiteral,
    IRStmtExpr,
    IRUnaryOp,
    IRVar,
)
from .lvalues import LValueContext, LValuePlan, build_lvalue_plan, lvalue_kind
from .operator_context import OperatorLoweringContext
from .typed_operators import lower_typed_binary


@dataclass(frozen=True)
class UpdateContext:
    """Expression-specific dependencies for a shared lvalue update."""

    lvalues: LValueContext
    operators: OperatorLoweringContext
    lower_overload: Callable[
        [TypeExpr | None, TypeExpr | None, str, IRExpr, IRExpr],
        IRExpr | None,
    ]
    coerce_assignment: Callable[[TypeExpr | None, TypeExpr | None, IRExpr], IRExpr]
    lower_value: Callable[[TypeExpr | None, object], IRExpr]
    store_boundary: Callable[[AssignExpr, LValuePlan], IRExpr | None] | None = None
    allow_unresolved_c_operands: bool = False


def lower_assignment(context: UpdateContext, node: AssignExpr) -> IRExpr:
    """Lower simple or compound assignment with one target/RHS evaluation."""
    target_type = context.lvalues.type_of(node.target)
    kind = lvalue_kind(context.lvalues, node.target)
    if node.op == "=" and kind == "direct" and isinstance(node.target, Identifier):
        right = context.lower_value(target_type, node.value)
        right_type = context.lvalues.type_of(node.value)
        value = context.coerce_assignment(target_type, right_type, right)
        return IRBinOp(
            left=context.lvalues.lower_expr(node.target),
            op="=",
            right=value,
        )
    if node.op == "=" and target_type is None:
        unresolved = _lower_unresolved_field_store(context, node)
        if unresolved is not None:
            return unresolved
    plan = build_lvalue_plan(context.lvalues, node.target, require_load=node.op != "=")
    if node.op == "=" and context.store_boundary is not None:
        bounded = context.store_boundary(node, plan)
        if bounded is not None:
            return bounded
    right = context.lower_value(plan.value_type, node.value)
    right_type = context.lvalues.type_of(node.value)
    if node.op == "=":
        value = context.coerce_assignment(plan.value_type, right_type, right)
        return plan.store_result(value)

    assert plan.load is not None
    old = plan.declare_value("__btrc_update_old")
    operator = node.op[:-1]
    value = context.lower_overload(plan.value_type, right_type, operator, old, right)
    if value is None:
        value = lower_typed_binary(
            operator,
            old,
            right,
            plan.value_type,
            right_type,
            context.operators,
            allow_unresolved_c_operands=(context.allow_unresolved_c_operands),
        )
    if value is None:
        value = IRBinOp(left=old, op=operator, right=right)
    value = context.coerce_assignment(plan.value_type, right_type, value)
    return plan.wrap(
        [
            IRBinOp(left=old, op="=", right=plan.load),
            *plan.store_result_operations(value),
        ]
    )


def _lower_unresolved_field_store(context: UpdateContext, node: AssignExpr):
    """Sequence a foreign-struct field store without knowing the field type."""
    target = node.target
    if not isinstance(target, FieldAccessExpr) or target.optional:
        return None
    fields = []
    base = target
    while isinstance(base, FieldAccessExpr) and not base.optional:
        fields.append((base.field, base.arrow))
        base = base.obj
    fields.reverse()
    base_type = context.lvalues.type_of(base)
    if base_type is None:
        return None
    receiver_decl = context.lvalues.declare(
        "__btrc_lvalue_obj",
        base_type,
        pointer=not fields[0][1],
    )
    receiver = IRVar(name=receiver_decl.name)
    lowered_receiver = context.lvalues.lower_expr(base)
    if not fields[0][1]:
        lowered_receiver = IRAddressOf(expr=lowered_receiver)
    right_type = context.lvalues.type_of(node.value)
    value = context.coerce_assignment(
        None,
        right_type,
        context.lower_value(None, node.value),
    )
    field = receiver
    for index, (field_name, arrow) in enumerate(fields):
        field = IRFieldAccess(
            obj=field,
            field=field_name,
            arrow=True if index == 0 else arrow,
        )
    return IRStmtExpr(
        stmts=[receiver_decl],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(left=receiver, op="=", right=lowered_receiver),
                IRBinOp(left=field, op="=", right=value),
            ]
        ),
    )


def lower_incdec(context: UpdateContext, node: UnaryExpr) -> IRExpr:
    """Lower prefix/postfix updates with one load and one store."""
    if lvalue_kind(context.lvalues, node.operand) == "direct":
        return IRUnaryOp(
            op=node.op,
            operand=context.lvalues.lower_expr(node.operand),
            prefix=node.prefix,
        )
    plan = build_lvalue_plan(context.lvalues, node.operand, require_load=True)
    assert plan.load is not None
    old_value = plan.declare_value("__btrc_update_old")
    new_value = plan.declare_value("__btrc_update_new")
    operator = "+" if node.op == "++" else "-"
    one = IRLiteral(text="1")
    computed = lower_typed_binary(
        operator,
        old_value,
        one,
        plan.value_type,
        TypeExpr(base="int"),
        context.operators,
        allow_unresolved_c_operands=context.allow_unresolved_c_operands,
    )
    if computed is None:
        computed = IRBinOp(left=old_value, op=operator, right=one)
    return plan.wrap(
        [
            IRBinOp(left=old_value, op="=", right=plan.load),
            IRBinOp(left=new_value, op="=", right=computed),
            plan.store(new_value),
            new_value if node.prefix else old_value,
        ]
    )


def generator_update_context(gen) -> UpdateContext:
    """Build the normal IR generator's update dependency bundle."""
    from ...ast_nodes import FieldAccessExpr, SelfExpr
    from .expressions import lower_expr
    from .operator_context import operator_context
    from .operators import lower_overloaded_values
    from .types import type_to_c
    from .upcast import upcast_class_pointer

    analyzed = gen.analyzed
    lvalues = LValueContext(
        lower_expr=lambda node: lower_expr(gen, node),
        type_of=lambda node: analyzed.node_types.get(id(node)),
        c_type=type_to_c,
        fresh_temp=gen.fresh_temp,
        register_decl=gen._func_var_decls.append,
        class_table=analyzed.class_table,
        direct_property=lambda target: bool(
            isinstance(target, FieldAccessExpr)
            and isinstance(target.obj, SelfExpr)
            and gen.current_property_backing == target.field
        ),
    )
    return UpdateContext(
        lvalues=lvalues,
        operators=operator_context(gen),
        lower_overload=lambda left_type, right_type, operator, left, right: lower_overloaded_values(
            gen, left_type, right_type, operator, left, right
        ),
        coerce_assignment=lambda target_type, source_type, value: upcast_class_pointer(
            gen, target_type, source_type, value
        ),
        lower_value=lambda target_type, value: _lower_assignment_value(gen, target_type, value),
        store_boundary=lambda node, plan: _lower_virtual_store_boundary(
            gen,
            node,
            plan,
            lower_value=lambda target_type, value: _lower_assignment_value(gen, target_type, value),
            coerce=lambda target_type, source_type, value: upcast_class_pointer(gen, target_type, source_type, value),
        ),
        allow_unresolved_c_operands=True,
    )


def _lower_virtual_store_boundary(gen, node, plan, *, lower_value, coerce):
    """Give setter sugar the same owned-argument boundary as a call."""
    if plan.kind not in {"collection", "property"}:
        return None
    from ...index_protocol import indexed_protocol
    from ..nodes import IRCommaExpr
    from .call_boundary import CallOperand, sequence_call_boundary
    from .managed_values import is_managed_type
    from .ownership import owns_result
    from .types import type_to_c

    setter = None
    if plan.kind == "collection":
        receiver_type = gen.analyzed.node_types.get(id(node.target.obj))
        protocol = indexed_protocol(receiver_type, gen.analyzed.class_table)
        setter = protocol.setter if protocol is not None else None
        if setter is None:
            return None
    source_type = gen.analyzed.node_types.get(id(node.value)) or plan.value_type
    managed = is_managed_type(gen, source_type)
    owned = bool(managed and owns_result(gen, node.value))
    keep = bool(managed and setter is not None and setter.params[1].keep)
    if not owned and not keep:
        return None

    operand = CallOperand(
        node=node.value,
        type_expr=source_type,
        c_type=type_to_c(source_type),
        keep=keep,
        owned=owned,
        transferred=owned,
    )

    def build_store(overrides):
        source = overrides[id(node.value)]
        value = coerce(plan.value_type, source_type, source)
        return IRCommaExpr(expressions=[plan.store(value), value])

    boundary = sequence_call_boundary(
        gen,
        [operand],
        lower_expr=lambda value: lower_value(plan.value_type, value),
        build_call=build_store,
        result_c_type=type_to_c(plan.value_type),
        result_type=plan.value_type,
        fresh_temp=gen.fresh_temp,
        cleanup_active=gen.exception_cleanup_active(),
        record_decl=gen._func_var_decls.append,
    )
    return plan.wrap([boundary])


def _lower_assignment_value(gen, target_type, value) -> IRExpr:
    """Use assignment context to select the concrete collection literal."""
    from ...ast_nodes import BraceInitializer, ListLiteral, MapLiteral
    from .collections import lower_list_literal, lower_map_literal
    from .expressions import lower_expr
    from .types import is_direct_generic_instance_reference

    if is_direct_generic_instance_reference(target_type, gen.analyzed.class_table):
        if isinstance(value, (BraceInitializer, ListLiteral)):
            return lower_list_literal(gen, value)
        if isinstance(value, MapLiteral):
            return lower_map_literal(gen, value)
    return lower_expr(gen, value)


__all__ = [
    "UpdateContext",
    "generator_update_context",
    "lower_assignment",
    "lower_incdec",
]
