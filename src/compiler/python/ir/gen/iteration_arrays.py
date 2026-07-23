"""Structured fixed-array ``for-in`` lowering."""

from __future__ import annotations

from ...ast_nodes import Identifier
from ...type_composition import strip_outer_storage
from ..nodes import (
    CType,
    IRBinOp,
    IRFor,
    IRIndex,
    IRLiteral,
    IRSizeof,
    IRStmt,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .iteration_bindings import IterationBinding
from .types import CTypeRenderer


def lower_fixed_array_for_in(
    gen,
    node,
    array_type,
    type_renderer: CTypeRenderer,
) -> list[IRStmt]:
    """Hoist array backing once and iterate over its preserved C extent."""
    from ...hosted_alias_carriers import hosted_alias_argument
    from .expressions import lower_expr
    from .iteration_ownership import begin_owned_iterable, finish_owned_iterable
    from .managed_values import is_managed_type
    from .projection_storage import (
        evaluate_with_operand_overrides,
        projection_storage_operands,
    )
    from .statements import _lower_loop_body

    storage = projection_storage_operands(
        node.iterable,
        type_of=lambda expression: gen.analyzed.node_types.get(id(expression)),
        is_managed=lambda type_expr: is_managed_type(gen, type_expr),
        owns=lambda expression: gen.ownership.owns_result(expression),
        overridden=lambda expression: id(expression) in gen.context.owning_overrides,
        struct_table=gen.analyzed.struct_table,
        return_alias_argument=lambda expression: hosted_alias_argument(
            expression,
            gen.analyzed.hosted_call_ids,
        ),
    )
    prefix: list[IRStmt] = []
    overrides = {}
    storage_types = {}
    owners = []
    for operand in storage:
        expression = operand.expression
        storage_type = gen.analyzed.node_types.get(id(expression))
        if storage_type is None:
            from .errors import CodegenError

            raise CodegenError("fixed-array projection storage has no concrete type")
        lowered = evaluate_with_operand_overrides(
            overrides,
            values=gen.context.owning_overrides,
            types=storage_types,
            type_values=gen.context.type_overrides,
            operation=lambda expression=expression: lower_expr(
                gen,
                expression,
                type_renderer,
            ),
        )
        name = gen.fresh_temp("__array_storage")
        prefix.append(
            IRVarDecl(
                c_type=CType(text=type_renderer.render(storage_type)),
                name=name,
                init=lowered,
            )
        )
        owner = begin_owned_iterable(
            gen,
            expression,
            storage_type,
            name,
            prefix,
        )
        if owner is not None:
            owners.append(owner)
        overrides[id(expression)] = IRVar(name=name)
        storage_types[id(expression)] = storage_type

    projected = evaluate_with_operand_overrides(
        overrides,
        values=gen.context.owning_overrides,
        types=storage_types,
        type_values=gen.context.type_overrides,
        operation=lambda: lower_expr(gen, node.iterable, type_renderer),
    )
    iterable = gen.fresh_temp("__iter")
    length = gen.fresh_temp("__n")
    index = gen.fresh_temp("__i")
    prefix.extend(
        [
            IRVarDecl(
                c_type=CType(text=type_renderer.render(array_type)),
                name=iterable,
                init=projected,
            ),
            IRVarDecl(
                c_type=CType(text="size_t"),
                name=length,
                init=fixed_array_iteration_length(
                    gen,
                    node.iterable,
                    projected,
                ),
            ),
        ]
    )
    element_type = strip_outer_storage(array_type, array=True)
    body = _lower_loop_body(
        gen,
        node.body,
        type_renderer,
        iteration_bindings=[
            IterationBinding(
                name=node.var_name,
                c_type=type_renderer.render(element_type),
                type_expr=element_type,
                value=IRIndex(
                    obj=IRVar(name=iterable),
                    index=IRVar(name=index),
                ),
                owned=False,
            )
        ],
    )
    result = [
        *prefix,
        IRFor(
            init=IRVarDecl(
                c_type=CType(text="size_t"),
                name=index,
                init=IRLiteral(text="0"),
            ),
            condition=IRBinOp(
                left=IRVar(name=index),
                op="<",
                right=IRVar(name=length),
            ),
            update=IRUnaryOp(
                op="++",
                operand=IRVar(name=index),
                prefix=False,
            ),
            body=body,
        ),
    ]
    for owner in reversed(owners):
        result.extend(finish_owned_iterable(gen, owner))
    return result


def fixed_array_capacity(array):
    """Return ``sizeof(array) / sizeof(array[0])`` as structured IR."""
    return IRBinOp(
        left=IRSizeof(operand=array),
        op="/",
        right=IRSizeof(operand=IRIndex(obj=array, index=IRLiteral(text="0"))),
    )


def fixed_array_iteration_length(context, expression, array):
    """Prefer a GPU result's logical length over its physical safety bound."""
    if isinstance(expression, Identifier):
        from .c_array_scopes import local_gpu_array_length

        # Generic-method emitters own their lexical C-array scopes; smaller
        # hosts may delegate that state to the primary IR generator.
        lookup = context if hasattr(context, "_c_array_scopes") else context._gen
        logical = local_gpu_array_length(lookup, expression.name)
        if logical is not None:
            return logical
    return fixed_array_capacity(array)


__all__ = [
    "fixed_array_capacity",
    "fixed_array_iteration_length",
    "lower_fixed_array_for_in",
]
