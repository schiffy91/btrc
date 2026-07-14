"""Bounded-depth lowering for long scalar-string concatenation chains."""

from __future__ import annotations

from ...ast_nodes import BinaryExpr
from ..nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCommaExpr,
    IRLiteral,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from .managed_values import is_string_type, release_value
from .ownership import owns_result
from .temporary_cleanup import cleanup_registration
from .types import type_to_c

_FLAT_CHAIN_MIN_TERMS = 32


def lower_long_string_concat(gen, node):
    """Lower a long left-associated chain as one flat comma sequence."""
    leaves = _left_chain_leaves(gen, node)
    if len(leaves) < _FLAT_CHAIN_MIN_TERMS:
        return None

    result_type = gen.analyzed.node_types.get(id(node))
    c_type = type_to_c(result_type)
    declarations: list[IRVarDecl] = []
    sequence = []
    values = []
    leaf_types = []
    owned = []

    for leaf in leaves:
        leaf_type = gen.analyzed.node_types.get(id(leaf)) or result_type
        declaration = _temporary(gen, "__btrc_concat_part", c_type)
        declarations.append(declaration)
        value = IRVar(name=declaration.name)
        values.append(value)
        leaf_types.append(leaf_type)
        owned.append(owns_result(gen, leaf))

    accumulator_decl = _temporary(gen, "__btrc_concat_acc", c_type)
    next_decl = _temporary(gen, "__btrc_concat_next", c_type)
    result_decl = _temporary(gen, "__btrc_concat_result", c_type)
    declarations.extend([accumulator_decl, next_decl, result_decl])
    accumulator = IRVar(name=accumulator_decl.name)
    next_value = IRVar(name=next_decl.name)
    result = IRVar(name=result_decl.name)

    _evaluate_leaf(
        gen,
        leaves[0],
        leaf_types[0],
        declarations[0],
        values[0],
        owned[0],
        declarations,
        sequence,
    )
    _evaluate_leaf(
        gen,
        leaves[1],
        leaf_types[1],
        declarations[1],
        values[1],
        owned[1],
        declarations,
        sequence,
    )
    sequence.append(
        IRBinOp(
            left=accumulator,
            op="=",
            right=_concat_call(gen, values[0], values[1]),
        )
    )
    _register_cleanup(
        gen,
        accumulator_decl,
        result_type,
        declarations,
        sequence,
        "__btrc_concat_acc_cleanup",
    )
    _release_leaf(gen, values[0], leaf_types[0], owned[0], sequence)
    _release_leaf(gen, values[1], leaf_types[1], owned[1], sequence)

    for index in range(2, len(values)):
        leaf = values[index]
        leaf_type = leaf_types[index]
        _evaluate_leaf(
            gen,
            leaves[index],
            leaf_type,
            declarations[index],
            leaf,
            owned[index],
            declarations,
            sequence,
        )
        sequence.append(
            IRBinOp(
                left=next_value,
                op="=",
                right=_concat_call(gen, accumulator, leaf),
            )
        )
        sequence.extend(
            [
                release_value(gen, accumulator, result_type),
                IRBinOp(
                    left=accumulator,
                    op="=",
                    right=IRLiteral(text="NULL"),
                ),
            ]
        )
        _release_leaf(gen, leaf, leaf_type, owned[index], sequence)
        sequence.extend(
            [
                IRBinOp(left=accumulator, op="=", right=next_value),
                IRBinOp(
                    left=next_value,
                    op="=",
                    right=IRLiteral(text="NULL"),
                ),
            ]
        )

    sequence.extend(
        [
            IRBinOp(left=result, op="=", right=accumulator),
            IRBinOp(
                left=accumulator,
                op="=",
                right=IRLiteral(text="NULL"),
            ),
            result,
        ]
    )
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=sequence),
    )


def _left_chain_leaves(gen, node):
    rights = []
    cursor = node
    while _is_scalar_concat(gen, cursor):
        rights.append(cursor.right)
        cursor = cursor.left
    rights.reverse()
    return [cursor, *rights]


def _is_scalar_concat(gen, node) -> bool:
    if not isinstance(node, BinaryExpr) or node.op != "+":
        return False
    types = gen.analyzed.node_types
    return all(is_string_type(gen, types.get(id(value))) for value in (node, node.left, node.right))


def _temporary(gen, prefix: str, c_type: str) -> IRVarDecl:
    declaration = IRVarDecl(
        c_type=CType(text=c_type),
        name=gen.fresh_temp(prefix),
        init=IRLiteral(text="NULL"),
    )
    gen._func_var_decls.append(declaration)
    return declaration


def _register_cleanup(
    gen,
    declaration,
    type_expr,
    declarations,
    sequence,
    prefix,
):
    cleanup_declarations, cleanup_expressions = cleanup_registration(
        gen,
        declaration,
        type_expr,
        prefix,
        active=gen.exception_cleanup_active(),
    )
    declarations.extend(cleanup_declarations)
    sequence.extend(cleanup_expressions)


def _evaluate_leaf(
    gen,
    node,
    type_expr,
    declaration,
    value,
    owned,
    declarations,
    sequence,
) -> None:
    from .expressions import lower_expr

    sequence.append(IRBinOp(left=value, op="=", right=lower_expr(gen, node)))
    if owned:
        _register_cleanup(
            gen,
            declaration,
            type_expr,
            declarations,
            sequence,
            "__btrc_concat_part_cleanup",
        )


def _release_leaf(gen, value, type_expr, owned: bool, sequence) -> None:
    if not owned:
        return
    sequence.extend(
        [
            release_value(gen, value, type_expr),
            IRBinOp(left=value, op="=", right=IRLiteral(text="NULL")),
        ]
    )


def _concat_call(gen, left, right):
    gen.use_helper("__btrc_strcat")
    gen.use_helper("__btrc_str_track")
    return IRCall(
        callee="__btrc_str_track",
        args=[
            IRCall(
                callee="__btrc_strcat",
                args=[left, right],
                helper_ref="__btrc_strcat",
            )
        ],
        helper_ref="__btrc_str_track",
    )


__all__ = ["lower_long_string_concat"]
