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
from .types import CTypeRenderer

if TYPE_CHECKING:
    from .default_arguments import DefaultArgumentLoweringContext
    from .lowerer import IRLowerer


def lower_expr(
    gen: IRLowerer,
    node,
    type_renderer: CTypeRenderer,
    default_arguments: DefaultArgumentLoweringContext | None = None,
) -> IRExpr:
    """Lower an AST expression node to an IRExpr."""
    if node is None:
        return IRLiteral(text="0")

    # ARC: owning temporary hoisted into a temp var (see _emit_keep_for_call).
    # The temp has already been declared and initialized; references to the
    # original AST arg node resolve to the temp so it can be released after use.
    if gen is not None:
        override = gen.context.owning_overrides.get(id(node))
        if override is not None:
            return override

    if isinstance(node, IntLiteral):
        return IRLiteral(text=format_c_integer_literal(node.raw, node.value))

    if isinstance(node, FloatLiteral):
        text = node.raw or str(node.value)
        if gen.context.gpu_cpu_index and not text.endswith(("f", "F")):
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
        return _lower_identifier(
            gen,
            node,
            default_arguments,
        )

    if isinstance(node, SelfExpr):
        return IRVar(name="self")

    if isinstance(node, SuperExpr):
        parent_type = gen.analyzed.node_types.get(id(node))
        if parent_type is None:
            from .errors import CodegenError

            raise CodegenError("unresolved super expression")
        return IRCast(
            target_type=CType(text=type_renderer.render(parent_type)),
            expr=IRVar(name="self"),
        )

    if isinstance(node, BinaryExpr):
        from .operators import _lower_binary

        return _lower_binary(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, UnaryExpr):
        from .operators import _lower_unary

        return _lower_unary(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, CallExpr):
        return gen.calls.lower(node)

    if isinstance(node, FieldAccessExpr):
        from .fields import _lower_field_access

        return _lower_field_access(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, IndexExpr):
        from .fields import _lower_index

        return _lower_index(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, AssignExpr):
        from .assignments import lower_assignment_expr

        return lower_assignment_expr(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, CastExpr):
        target_type = type_renderer.render(node.target_type)
        reference_types = set(gen.analyzed.class_table)
        reference_types.update(getattr(gen.analyzed, "interface_table", {}))
        if node.target_type.base in reference_types and not target_type.endswith("*"):
            target_type += "*"
        return IRCast(
            target_type=CType(text=target_type),
            expr=lower_expr(
                gen,
                node.expr,
                type_renderer,
                default_arguments,
            ),
        )

    if isinstance(node, SizeofExpr):
        return _lower_sizeof(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, TernaryExpr):
        from .operator_context import OperatorLoweringContext
        from .typed_operators import lower_typed_ternary

        true_expr = lower_expr(
            gen,
            node.true_expr,
            type_renderer,
            default_arguments,
        )
        false_expr = lower_expr(
            gen,
            node.false_expr,
            type_renderer,
            default_arguments,
        )
        if gen.ownership.owns_result(node):
            true_expr = gen.ownership.normalize_branch(
                node.true_expr,
                true_expr,
            )
            false_expr = gen.ownership.normalize_branch(
                node.false_expr,
                false_expr,
            )
        return lower_typed_ternary(
            lower_expr(
                gen,
                node.condition,
                type_renderer,
                default_arguments,
            ),
            true_expr,
            false_expr,
            gen.analyzed.node_types.get(id(node.true_expr)),
            gen.analyzed.node_types.get(id(node.false_expr)),
            OperatorLoweringContext.from_lowerer(gen, type_renderer),
        )

    if isinstance(node, NewExpr):
        from .constructor_calls import lower_new_expr

        return lower_new_expr(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, ListLiteral):
        from .collections import lower_list_literal

        return lower_list_literal(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, MapLiteral):
        from .collections import lower_map_literal

        return lower_map_literal(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, FStringLiteral):
        from .fstrings import lower_fstring

        return lower_fstring(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, LambdaExpr):
        from .lambdas import lower_lambda

        return lower_lambda(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, TupleLiteral):
        return _lower_tuple(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, SpawnExpr):
        from .threads import lower_spawn

        return lower_spawn(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, BraceInitializer):
        from .aggregate_initializers import lower_brace_initializer

        return lower_brace_initializer(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    raise unsupported_node("expression", node)


def _lower_identifier(
    gen: IRLowerer,
    node: Identifier,
    default_arguments: DefaultArgumentLoweringContext | None,
) -> IRExpr:
    """Lower an identifier, handling enum values."""
    name = node.name
    predefined = default_arguments.predefined_identifier(node) if default_arguments is not None else None
    if predefined is not None:
        return IRLiteral(text=predefined)
    if gen.local_ownership_declared(name):
        return _source_identifier_var(gen, node, gen.source_binding_c_name(name))
    if is_source_runtime_helper(name) and not gen.local_ownership_declared(name):
        gen.helpers.use(name)
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
    return _source_identifier_var(gen, node, name)


def _source_identifier_var(gen, node, c_name):
    from ..storage_provenance import record_array_value

    return record_array_value(
        IRVar(name=c_name),
        gen.analyzed.node_types.get(id(node)),
    )


def _lower_sizeof(
    gen: IRLowerer,
    node: SizeofExpr,
    type_renderer: CTypeRenderer,
    default_arguments: DefaultArgumentLoweringContext,
) -> IRExpr:
    if isinstance(node.operand, SizeofType):
        return IRSizeof(operand=CType(text=type_renderer.render(node.operand.type)))
    elif isinstance(node.operand, SizeofExprOp):
        expression = node.operand.expr
        expression_type = gen.analyzed.node_types.get(id(expression))
        # Non-array expression size depends only on its semantic C type. This
        # also keeps intrinsically statement-shaped values (f-strings,
        # collection literals, ownership conversions) out of strict-C sizeof.
        if expression_type is not None and not expression_type.is_array and not isinstance(expression, StringLiteral):
            return IRSizeof(operand=CType(text=type_renderer.render(expression_type)))
        gen.context.unevaluated_depth += 1
        try:
            return IRSizeof(
                operand=lower_expr(
                    gen,
                    expression,
                    type_renderer,
                    default_arguments,
                )
            )
        finally:
            gen.context.unevaluated_depth -= 1
    return IRSizeof(operand=CType(text="void"))


def _lower_tuple(
    gen: IRLowerer,
    node: TupleLiteral,
    type_renderer: CTypeRenderer,
    default_arguments: DefaultArgumentLoweringContext,
) -> IRExpr:
    """Lower tuple literal to C struct initializer."""
    from .aggregate_ownership import reject_owned_elements

    reject_owned_elements(gen, node.elements, "a shallow aggregate")
    elems = [
        lower_expr(
            gen,
            element,
            type_renderer,
            default_arguments,
        )
        for element in node.elements
    ]
    node_type = gen.analyzed.node_types.get(id(node))
    if node_type and node_type.generic_args:
        mangled = gen.type_identity.generic_symbol("Tuple", node_type.generic_args)
    else:
        # Fallback: construct from element count
        mangled = f"btrc_Tuple_{'_'.join(['int'] * len(node.elements))}"
    return IRCompoundLiteral(
        c_type=CType(text=mangled),
        fields=[(f"_{index}", value) for index, value in enumerate(elems)],
    )
