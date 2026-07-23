"""Iterable-protocol lowering inside generic specializations."""

from __future__ import annotations

from ...nodes import (
    CType,
    IRBinOp,
    IRBlock,
    IRCall,
    IRFor,
    IRIndex,
    IRLiteral,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from ..iteration_bindings import IterationBinding

_BUILTIN_ITERABLE_METHODS = {
    "Array": frozenset(("iterLen", "iterGet")),
    "List": frozenset(("iterLen", "iterGet")),
    "Map": frozenset(("iterLen", "iterGet", "iterValueAt")),
    "Set": frozenset(("iterLen", "iterGet")),
    "Vector": frozenset(("iterLen", "iterGet")),
}


def lower_iterable_forin(emitter, statement) -> list:
    from ..errors import CodegenError

    iter_type = emitter._resolve_expr_type(statement.iterable)
    if id(statement.iterable) in emitter._gen.analyzed.array_iteration_capacity_ids:
        from .user_emitter_iteration_arrays import lower_fixed_array_forin

        return lower_fixed_array_forin(emitter, statement, iter_type)
    if iter_type and iter_type.base == "string":
        return lower_string_forin(emitter, statement)
    if not (iter_type and emitter._gen):
        raise CodegenError("unsupported generic-method for-in iterable")
    cls = emitter._gen.analyzed.class_table.get(iter_type.base)
    methods = frozenset(cls.methods) if cls else _BUILTIN_ITERABLE_METHODS.get(iter_type.base, frozenset())
    if not {"iterLen", "iterGet"}.issubset(methods):
        raise CodegenError(f"type '{iter_type.base}' does not implement iterable protocol")

    mangled = (
        emitter.type_identity.specialization_symbol(iter_type.base, iter_type.generic_args)
        if iter_type.generic_args
        else iter_type.base
    )
    iterable = emitter._fresh_temp("__iter")
    length = emitter._fresh_temp("__n")
    index = emitter._fresh_temp("__i")
    iter_c = emitter._ttc(iter_type)
    if not iter_c.endswith("*"):
        iter_c += "*"
    result = [
        IRVarDecl(
            c_type=CType(text=iter_c),
            name=iterable,
            init=emitter._expr(statement.iterable),
        )
    ]
    from .user_emitter_iteration_arc import (
        begin_owned_iterable,
        finish_owned_iterable,
    )

    owner = begin_owned_iterable(emitter, statement.iterable, iter_type, iterable, result)
    element_type = _iter_method_return_type(emitter, cls, iter_type, "iterGet", 0)
    bindings = [
        IterationBinding(
            name=statement.var_name,
            c_type=emitter.iter_value_c(element_type),
            type_expr=element_type,
            value=IRCall(
                callee=f"{mangled}_iterGet",
                args=[IRVar(name=iterable), IRVar(name=index)],
            ),
            owned=True,
        )
    ]
    second_name = getattr(statement, "var_name2", None)
    if second_name and "iterValueAt" not in methods:
        raise CodegenError(f"type '{iter_type.base}' does not support key/value iteration")
    if second_name:
        value_type = _iter_method_return_type(emitter, cls, iter_type, "iterValueAt", 1)
        bindings.append(
            IterationBinding(
                name=second_name,
                c_type=emitter.iter_value_c(value_type),
                type_expr=value_type,
                value=IRCall(
                    callee=f"{mangled}_iterValueAt",
                    args=[IRVar(name=iterable), IRVar(name=index)],
                ),
                owned=True,
            )
        )
    body = emitter._loop_stmts(statement.body.statements, iteration_bindings=bindings)
    result.extend(
        [
            IRVarDecl(
                c_type=CType(text="int"),
                name=length,
                init=IRCall(
                    callee=f"{mangled}_iterLen",
                    args=[IRVar(name=iterable)],
                ),
            ),
            IRFor(
                init=IRVarDecl(
                    c_type=CType(text="int"),
                    name=index,
                    init=IRLiteral(text="0"),
                ),
                condition=IRBinOp(
                    left=IRVar(name=index),
                    op="<",
                    right=IRVar(name=length),
                ),
                update=IRUnaryOp(op="++", operand=IRVar(name=index), prefix=False),
                body=IRBlock(stmts=body),
            ),
        ]
    )
    result.extend(finish_owned_iterable(emitter, owner))
    return result


def _iter_method_return_type(emitter, cls, iter_type, method_name, fallback_index):
    method = cls.methods.get(method_name) if cls else None
    if method is not None:
        from .core import _resolve_type

        substitutions = dict(zip(cls.generic_params, iter_type.generic_args))
        return emitter._resolve(
            _resolve_type(
                method.return_type,
                substitutions,
                emitter._typedefs(),
                emitter.type_identity,
            )
        )
    if fallback_index < len(iter_type.generic_args):
        return iter_type.generic_args[fallback_index]
    from ....ast_nodes import TypeExpr

    return TypeExpr(base="int")


def lower_string_forin(emitter, statement) -> list:
    from ....ast_nodes import TypeExpr

    iterable = emitter._fresh_temp("__iter")
    index = emitter._fresh_temp("__i")
    string_type = TypeExpr(base="string")
    result = [
        IRVarDecl(
            c_type=CType(text="char*"),
            name=iterable,
            init=emitter._expr(statement.iterable),
        )
    ]
    from .user_emitter_iteration_arc import (
        begin_owned_iterable,
        finish_owned_iterable,
    )

    owner = begin_owned_iterable(
        emitter,
        statement.iterable,
        string_type,
        iterable,
        result,
    )
    body = emitter._loop_stmts(
        statement.body.statements,
        iteration_bindings=[
            IterationBinding(
                name=statement.var_name,
                c_type="char",
                type_expr=TypeExpr(base="char"),
                value=IRIndex(obj=IRVar(name=iterable), index=IRVar(name=index)),
                owned=False,
            )
        ],
    )
    result.append(
        IRFor(
            init=IRVarDecl(
                c_type=CType(text="int"),
                name=index,
                init=IRLiteral(text="0"),
            ),
            condition=IRBinOp(
                left=IRIndex(obj=IRVar(name=iterable), index=IRVar(name=index)),
                op="!=",
                right=IRLiteral(text="'\\0'"),
            ),
            update=IRUnaryOp(op="++", operand=IRVar(name=index), prefix=False),
            body=IRBlock(stmts=body),
        )
    )
    result.extend(finish_owned_iterable(emitter, owner))
    return result


__all__ = ["lower_iterable_forin", "lower_string_forin"]
