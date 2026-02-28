"""Expression lowering: AST expr → IRExpr.

Main dispatch function plus literal/simple expression handling.
Operator, call, field access, and assignment lowering are in sub-modules.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import (
    AssignExpr, BinaryExpr, BoolLiteral, BraceInitializer, CallExpr,
    CastExpr, CharLiteral, FieldAccessExpr, FloatLiteral, FStringLiteral,
    Identifier, IndexExpr, IntLiteral, LambdaExpr, ListLiteral, MapLiteral,
    NewExpr, NullLiteral, SelfExpr, SizeofExpr, SizeofExprOp, SizeofType,
    SpawnExpr, StringLiteral, SuperExpr, TernaryExpr, TupleLiteral, UnaryExpr,
)
from ..nodes import (
    IRCall, IRCast, IRExpr, IRLiteral, IRRawExpr, IRSizeof,
    IRSpawnThread, IRTernary, IRVar,
)
from .types import type_to_c, is_generic_class_type

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
        from .operators import _lower_binary
        return _lower_binary(gen, node)

    if isinstance(node, UnaryExpr):
        from .operators import _lower_unary
        return _lower_unary(gen, node)

    if isinstance(node, CallExpr):
        from .calls import _lower_call
        return _lower_call(gen, node)

    if isinstance(node, FieldAccessExpr):
        from .fields import _lower_field_access
        return _lower_field_access(gen, node)

    if isinstance(node, IndexExpr):
        from .fields import _lower_index
        return _lower_index(gen, node)

    if isinstance(node, AssignExpr):
        from .fields import _lower_assign
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

    if isinstance(node, SpawnExpr):
        from .threads import lower_spawn
        return lower_spawn(gen, node)

    if isinstance(node, BraceInitializer):
        if not node.elements:
            # Check if analyzer annotated this with a collection type
            node_type = gen.analyzed.node_types.get(id(node))
            if node_type and is_generic_class_type(node_type, gen.analyzed.class_table):
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
