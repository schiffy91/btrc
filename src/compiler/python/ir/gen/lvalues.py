"""Structured load/store plans for assignable expressions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ...ast_nodes import FieldAccessExpr, IndexExpr, TypeExpr
from ...index_protocol import indexed_protocol_info
from ..c_types import qualify_volatile_object
from ..nodes import (
    CType,
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRCommaExpr,
    IRDeref,
    IRExpr,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from .errors import TypedOperatorError
from .types import mangle_generic_type


@dataclass(frozen=True)
class LValueContext:
    """Dependencies needed to turn one AST target into structured IR."""

    lower_expr: Callable[[object], IRExpr]
    type_of: Callable[[object], TypeExpr | None]
    c_type: Callable[[TypeExpr], str]
    fresh_temp: Callable[[str], str]
    register_decl: Callable[[IRVarDecl], None]
    class_table: dict
    direct_property: Callable[[object], bool] | None = None

    def declare(self, prefix: str, type_expr: TypeExpr, *, pointer=False):
        c_type = value_c_type(type_expr, self.class_table, self.c_type)
        if pointer:
            # Direct lvalues may name setjmp-safe managed locals whose IR
            # declarations are made volatile after analysis. Point at a
            # volatile object unconditionally: adding this qualification is
            # valid for ordinary targets and preserves it for cleanup slots.
            if not type_expr.is_volatile:
                c_type = qualify_volatile_object(c_type, True)
            c_type += "*"
        declaration = IRVarDecl(c_type=CType(text=c_type), name=self.fresh_temp(prefix))
        self.register_decl(declaration)
        return declaration


@dataclass
class LValuePlan:
    """One evaluation of a target, followed by reusable load/store operations."""

    context: LValueContext
    value_type: TypeExpr
    load: IRExpr | None
    store: Callable[[IRExpr], IRExpr]
    declarations: list[IRVarDecl] = field(default_factory=list)
    setup: list[IRExpr] = field(default_factory=list)
    store_yields_value: bool = True
    kind: str = "direct"

    def declare_value(self, prefix: str) -> IRVar:
        declaration = self.context.declare(prefix, self.value_type)
        self.declarations.append(declaration)
        return IRVar(name=declaration.name)

    def wrap(self, operations: list[IRExpr]) -> IRExpr:
        expressions = [*self.setup, *operations]
        result = expressions[0] if len(expressions) == 1 else IRCommaExpr(expressions=expressions)
        if not self.declarations:
            return result
        return IRStmtExpr(stmts=self.declarations, result=result)

    def store_result(self, value: IRExpr) -> IRExpr:
        """Store once and yield the assignment expression's value."""
        if self.store_yields_value:
            return self.wrap([self.store(value)])
        result = self.declare_value("__btrc_update_value")
        return self.wrap(
            [
                IRBinOp(left=result, op="=", right=value),
                self.store(result),
                result,
            ]
        )


def build_lvalue_plan(
    context: LValueContext,
    target,
    *,
    require_load: bool,
) -> LValuePlan:
    """Build a single-evaluation plan for a direct, property, or indexed target."""
    value_type = context.type_of(target)
    if value_type is None:
        raise TypedOperatorError("cannot resolve assignment target type")
    if isinstance(target, FieldAccessExpr) and target.optional:
        raise TypedOperatorError("optional-chain expressions are not assignable")

    property_plan = _property_plan(context, target, value_type, require_load)
    if property_plan is not None:
        return property_plan
    collection_plan = _collection_plan(context, target, value_type, require_load)
    if collection_plan is not None:
        return collection_plan
    return _direct_plan(context, target, value_type)


def lvalue_kind(context: LValueContext, target) -> str:
    """Classify a target without evaluating it or allocating temporaries."""
    if context.direct_property is not None and context.direct_property(target):
        return "direct"
    if isinstance(target, FieldAccessExpr):
        receiver_type = context.type_of(target.obj)
        if receiver_type is not None:
            class_info = context.class_table.get(receiver_type.base)
            if class_info is not None and target.field in class_info.properties:
                return "property"
    if isinstance(target, IndexExpr):
        receiver_type = context.type_of(target.obj)
        if indexed_protocol_info(receiver_type, context.class_table) is not None:
            return "collection"
    return "direct"


def _direct_plan(context, target, value_type) -> LValuePlan:
    declaration = context.declare("__btrc_lvalue", value_type, pointer=True)
    pointer = IRVar(name=declaration.name)
    load = IRDeref(expr=pointer)
    return LValuePlan(
        context=context,
        value_type=value_type,
        load=load,
        store=lambda value: IRBinOp(left=load, op="=", right=value),
        declarations=[declaration],
        setup=[
            IRBinOp(
                left=pointer,
                op="=",
                right=IRAddressOf(expr=context.lower_expr(target)),
            )
        ],
    )


def _property_plan(context, target, value_type, require_load):
    if not isinstance(target, FieldAccessExpr):
        return None
    if context.direct_property is not None and context.direct_property(target):
        return None
    receiver_type = context.type_of(target.obj)
    if receiver_type is None:
        return None
    class_info = context.class_table.get(receiver_type.base)
    if class_info is None or target.field not in class_info.properties:
        return None
    prop = class_info.properties[target.field]
    if not prop.has_setter:
        raise TypedOperatorError(f"property '{target.field}' has no setter")
    if require_load and not prop.has_getter:
        raise TypedOperatorError(f"property '{target.field}' has no getter")

    receiver_decl = context.declare("__btrc_property_obj", receiver_type)
    receiver = IRVar(name=receiver_decl.name)
    prefix = _class_prefix(receiver_type, class_info)
    load = IRCall(callee=f"{prefix}_get_{target.field}", args=[receiver]) if require_load else None
    return LValuePlan(
        context=context,
        value_type=value_type,
        load=load,
        store=lambda value: IRCall(callee=f"{prefix}_set_{target.field}", args=[receiver, value]),
        declarations=[receiver_decl],
        setup=[IRBinOp(left=receiver, op="=", right=context.lower_expr(target.obj))],
        store_yields_value=False,
        kind="property",
    )


def _collection_plan(context, target, value_type, require_load):
    if not isinstance(target, IndexExpr):
        return None
    receiver_type = context.type_of(target.obj)
    class_info = indexed_protocol_info(receiver_type, context.class_table)
    if receiver_type is None or class_info is None:
        return None
    if "set" not in class_info.methods:
        raise TypedOperatorError(f"type '{receiver_type.base}' has no indexed setter")
    if require_load and "get" not in class_info.methods:
        raise TypedOperatorError(f"type '{receiver_type.base}' has no indexed getter")
    index_type = context.type_of(target.index)
    if index_type is None:
        raise TypedOperatorError("cannot resolve collection index type")

    receiver_decl = context.declare("__btrc_index_obj", receiver_type)
    index_decl = context.declare("__btrc_index", index_type)
    receiver = IRVar(name=receiver_decl.name)
    index = IRVar(name=index_decl.name)
    prefix = _class_prefix(receiver_type, class_info)
    args = [receiver, index]
    load = IRCall(callee=f"{prefix}_get", args=args) if require_load else None
    return LValuePlan(
        context=context,
        value_type=value_type,
        load=load,
        store=lambda value: IRCall(callee=f"{prefix}_set", args=[*args, value]),
        declarations=[receiver_decl, index_decl],
        setup=[
            IRBinOp(left=receiver, op="=", right=context.lower_expr(target.obj)),
            IRBinOp(left=index, op="=", right=context.lower_expr(target.index)),
        ],
        store_yields_value=False,
        kind="collection",
    )


def value_c_type(type_expr, class_table, render) -> str:
    """C value type, including the implicit pointer representation of classes."""
    text = render(type_expr)
    if type_expr.base in class_table and not text.endswith("*"):
        text += "*"
    return qualify_volatile_object(text, type_expr.is_volatile)


def _class_prefix(receiver_type, class_info) -> str:
    if receiver_type.generic_args and class_info.generic_params:
        return mangle_generic_type(receiver_type.base, receiver_type.generic_args)
    return receiver_type.base


__all__ = [
    "LValueContext",
    "LValuePlan",
    "build_lvalue_plan",
    "lvalue_kind",
    "value_c_type",
]
