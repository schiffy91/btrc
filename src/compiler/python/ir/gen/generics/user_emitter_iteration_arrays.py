"""Fixed-array iteration inside generic specializations."""

from __future__ import annotations

from ....type_composition import strip_outer_storage
from ...nodes import (
    CType,
    IRBinOp,
    IRBlock,
    IRFor,
    IRIndex,
    IRLiteral,
    IRStmt,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from ..iteration_arrays import fixed_array_iteration_length
from ..iteration_bindings import IterationBinding


def lower_fixed_array_forin(emitter, statement, array_type) -> list[IRStmt]:
    """Preserve concrete storage and extent for a generic-method loop."""
    from ....hosted_alias_carriers import hosted_alias_argument
    from ..projection_storage import (
        evaluate_with_operand_overrides,
        projection_storage_operands,
    )
    from .user_emitter_iteration_arc import (
        begin_owned_iterable,
        finish_owned_iterable,
    )

    storage = projection_storage_operands(
        statement.iterable,
        type_of=emitter._resolve_expr_type,
        is_managed=emitter._is_managed_type,
        owns=emitter._owns_expr,
        overridden=lambda expression: id(expression) in emitter._arc_overrides,
        struct_table=emitter._gen.analyzed.struct_table,
        return_alias_argument=lambda expression: hosted_alias_argument(
            expression,
            emitter._gen.analyzed.hosted_call_ids,
        ),
    )
    prefix: list[IRStmt] = []
    overrides = {}
    storage_types = {}
    owners = []
    for operand in storage:
        expression = operand.expression
        storage_type = emitter._resolve_expr_type(expression)
        emitter._require_operand_type(storage_type)
        lowered = evaluate_with_operand_overrides(
            overrides,
            values=emitter._arc_overrides,
            types=storage_types,
            type_values=emitter._arc_type_overrides,
            operation=lambda expression=expression: emitter._expr(expression),
        )
        name = emitter._fresh_temp("__array_storage")
        prefix.append(
            IRVarDecl(
                c_type=CType(text=emitter.iter_value_c(storage_type)),
                name=name,
                init=lowered,
            )
        )
        owner = begin_owned_iterable(
            emitter,
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
        values=emitter._arc_overrides,
        types=storage_types,
        type_values=emitter._arc_type_overrides,
        operation=lambda: emitter._expr(statement.iterable),
    )
    iterable = emitter._fresh_temp("__iter")
    length = emitter._fresh_temp("__n")
    index = emitter._fresh_temp("__i")
    prefix.extend(
        [
            IRVarDecl(
                c_type=CType(text=emitter.iter_value_c(array_type)),
                name=iterable,
                init=projected,
            ),
            IRVarDecl(
                c_type=CType(text="size_t"),
                name=length,
                init=fixed_array_iteration_length(
                    emitter,
                    statement.iterable,
                    projected,
                ),
            ),
        ]
    )
    element_type = strip_outer_storage(array_type, array=True)
    body = emitter._loop_stmts(
        statement.body.statements,
        iteration_bindings=[
            IterationBinding(
                name=statement.var_name,
                c_type=emitter.iter_value_c(element_type),
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
            body=IRBlock(stmts=body),
        ),
    ]
    for owner in reversed(owners):
        result.extend(finish_owned_iterable(emitter, owner))
    return result


__all__ = ["lower_fixed_array_forin"]
