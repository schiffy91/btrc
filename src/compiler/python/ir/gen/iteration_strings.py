"""Single-evaluation lowering for string ``for-in`` loops."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRBinOp,
    IRFor,
    IRIndex,
    IRLiteral,
    IRStmt,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .iteration_bindings import IterationBinding


def lower_string_for_in(
    gen,
    node,
    iterable,
    var_name,
    type_renderer,
) -> list[IRStmt]:
    """Hoist the string once, then bind each character in body scope."""
    from .statements import _lower_loop_body

    index = gen.fresh_temp("__i")
    temp = gen.fresh_temp("__iter")
    iter_var = IRVar(name=temp)
    prefix = [IRVarDecl(c_type=CType(text="char*"), name=temp, init=iterable)]
    from .iteration_ownership import (
        begin_owned_iterable,
        finish_owned_iterable,
    )

    iterable_type = gen.analyzed.node_types.get(id(node.iterable))
    owner = begin_owned_iterable(
        gen,
        node.iterable,
        iterable_type,
        temp,
        prefix,
    )
    body = _lower_loop_body(
        gen,
        node.body,
        type_renderer,
        iteration_bindings=[
            IterationBinding(
                name=var_name,
                c_type="char",
                type_expr=None,
                value=IRIndex(obj=iter_var, index=IRVar(name=index)),
                owned=False,
            )
        ],
    )
    result = [
        *prefix,
        IRFor(
            init=IRVarDecl(
                c_type=CType(text="int"),
                name=index,
                init=IRLiteral(text="0"),
            ),
            condition=IRBinOp(
                left=IRIndex(obj=iter_var, index=IRVar(name=index)),
                op="!=",
                right=IRLiteral(text="'\\0'"),
            ),
            update=IRUnaryOp(op="++", operand=IRVar(name=index), prefix=False),
            body=body,
        ),
    ]
    result.extend(finish_owned_iterable(gen, owner))
    return result


__all__ = ["lower_string_for_in"]
