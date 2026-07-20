"""Expression lowering: AST expr → IRExpr.

Main dispatch function plus literal/simple expression handling.
Operator, call, field access, and assignment lowering are in sub-modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BoolLiteral,
    BraceInitializer,
    CallExpr,
    CastExpr,
    CharLiteral,
    FieldAccessExpr,
    FloatLiteral,
    FStringLiteral,
    Identifier,
    IndexExpr,
    IntLiteral,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    NullLiteral,
    SelfExpr,
    SizeofExpr,
    SizeofExprOp,
    SizeofType,
    SpawnExpr,
    StringLiteral,
    SuperExpr,
    TernaryExpr,
    TupleLiteral,
    UnaryExpr,
)
from ...source_runtime_symbols import is_source_runtime_helper
from ..nodes import (
    CType,
    IRCast,
    IRCompoundLiteral,
    IRExpr,
    IRFunctionRef,
    IRLiteral,
    IRSizeof,
    IRVar,
)
from .errors import unsupported_node
from .literal_text import format_c_integer_literal
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_expr(gen: IRGenerator, node) -> IRExpr:
    """Lower an AST expression node to an IRExpr."""
    if node is None:
        return IRLiteral(text="0")

    # ARC: owning temporary hoisted into a temp var (see _emit_keep_for_call).
    # The temp has already been declared and initialized; references to the
    # original AST arg node resolve to the temp so it can be released after use.
    if gen is not None:
        override = gen._owning_temp_overrides.get(id(node))
        if override is not None:
            return override

    if isinstance(node, IntLiteral):
        return IRLiteral(text=format_c_integer_literal(node.raw, node.value))

    if isinstance(node, FloatLiteral):
        text = node.raw or str(node.value)
        if getattr(gen, "_gpu_cpu_index", None) and not text.endswith(("f", "F")):
            text += "f"
        return IRLiteral(text=text)

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
        from .arguments_arc import lower_call_with_arc

        return lower_call_with_arc(gen, node)

    if isinstance(node, FieldAccessExpr):
        from .fields import _lower_field_access

        return _lower_field_access(gen, node)

    if isinstance(node, IndexExpr):
        from .fields import _lower_index

        return _lower_index(gen, node)

    if isinstance(node, AssignExpr):
        from .assignments import lower_assignment_expr

        return lower_assignment_expr(gen, node)

    if isinstance(node, CastExpr):
        target_type = type_to_c(node.target_type)
        reference_types = set(gen.analyzed.class_table)
        reference_types.update(getattr(gen.analyzed, "interface_table", {}))
        if node.target_type.base in reference_types and not target_type.endswith("*"):
            target_type += "*"
        return IRCast(target_type=CType(text=target_type), expr=lower_expr(gen, node.expr))

    if isinstance(node, SizeofExpr):
        return _lower_sizeof(gen, node)

    if isinstance(node, TernaryExpr):
        from .ownership import normalize_owned_branch, owns_result
        from .typed_operators import lower_typed_ternary, operator_context

        true_expr = lower_expr(gen, node.true_expr)
        false_expr = lower_expr(gen, node.false_expr)
        if owns_result(gen, node):
            true_expr = normalize_owned_branch(
                gen,
                node.true_expr,
                true_expr,
            )
            false_expr = normalize_owned_branch(
                gen,
                node.false_expr,
                false_expr,
            )
        return lower_typed_ternary(
            lower_expr(gen, node.condition),
            true_expr,
            false_expr,
            gen.analyzed.node_types.get(id(node.true_expr)),
            gen.analyzed.node_types.get(id(node.false_expr)),
            operator_context(gen),
        )

    if isinstance(node, NewExpr):
        from .constructor_calls import lower_new_expr

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
        from .aggregate_initializers import lower_brace_initializer

        return lower_brace_initializer(gen, node)

    raise unsupported_node("expression", node)


def _lower_identifier(gen: IRGenerator, node: Identifier) -> IRExpr:
    """Lower an identifier, handling enum values."""
    name = node.name
    from .default_argument_context import (
        resolve_default_predefined_identifier,
    )

    predefined = resolve_default_predefined_identifier(node)
    if predefined is not None:
        return IRLiteral(text=predefined)
    if gen.local_ownership_declared(name):
        return IRVar(name=gen.source_binding_c_name(name))
    if is_source_runtime_helper(name) and not gen.local_ownership_declared(name):
        gen.use_helper(name)
        return IRFunctionRef(name=name)
    enum_members = getattr(gen, "_enum_lowering_members", ()) or ()
    if name in enum_members:
        owner = getattr(gen, "_enum_lowering_owner", "")
        prefix = f"{owner}_" if owner else ""
        return IRVar(name=f"{prefix}{name}")
    # Check if this is an enum member (e.g., RED → Color_RED)
    for enum_name, values in gen.analyzed.enum_table.items():
        if name in values:
            prefix = f"{enum_name}_" if enum_name else ""
            return IRVar(name=f"{prefix}{name}")
    if name in gen.analyzed.function_table and not gen.local_ownership_declared(name):
        from .function_symbols import source_function_c_name

        return IRFunctionRef(name=source_function_c_name(gen.analyzed, name))
    return IRVar(name=name)


def _lower_sizeof(gen: IRGenerator, node: SizeofExpr) -> IRExpr:
    if isinstance(node.operand, SizeofType):
        return IRSizeof(operand=CType(text=type_to_c(node.operand.type)))
    elif isinstance(node.operand, SizeofExprOp):
        inner = lower_expr(gen, node.operand.expr)
        return IRSizeof(operand=inner)
    return IRSizeof(operand=CType(text="void"))


def _lower_tuple(gen: IRGenerator, node: TupleLiteral) -> IRExpr:
    """Lower tuple literal to C struct initializer."""
    from .aggregate_ownership import reject_owned_elements
    from .types import mangle_tuple_type

    reject_owned_elements(gen, node.elements, "a shallow aggregate")
    elems = [lower_expr(gen, e) for e in node.elements]
    node_type = gen.analyzed.node_types.get(id(node))
    if node_type and node_type.generic_args:
        mangled = mangle_tuple_type(node_type)
    else:
        # Fallback: construct from element count
        mangled = f"btrc_Tuple_{'_'.join(['int'] * len(node.elements))}"
    return IRCompoundLiteral(
        c_type=CType(text=mangled),
        fields=[(f"_{index}", value) for index, value in enumerate(elems)],
    )
