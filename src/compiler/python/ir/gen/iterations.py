"""Iteration lowering: for-in, range-for, and C-style for loops."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import (
    CForStmt, ForInitExpr, ForInitVar, CallExpr, Identifier,
)
from ..nodes import (
    CType, IRAssign, IRBinOp, IRBlock, IRCall, IRExprStmt, IRFor, IRIndex,
    IRLiteral, IRStmt, IRTernary, IRUnaryOp, IRVarDecl, IRVar,
)
from .types import type_to_c, mangle_generic_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def _lower_for_in(gen: IRGenerator, node) -> list[IRStmt]:
    """Lower for-in to C-style for loop."""
    from .statements import lower_block
    iterable = node.iterable
    var_name = node.var_name
    var_name2 = getattr(node, 'var_name2', None)

    # Detect range() calls
    if isinstance(iterable, CallExpr) and isinstance(iterable.callee, Identifier):
        if iterable.callee.name == "range":
            return _lower_range_for(gen, var_name, iterable.args, node.body)

    # Get the iterable type from the analyzer
    iter_type = gen.analyzed.node_types.get(id(iterable))
    ir_iter = _lower_expr(gen, iterable)

    # Iterable protocol: any class with iterLen + iterGet methods
    if iter_type and iter_type.generic_args:
        cls_info = gen.analyzed.class_table.get(iter_type.base)
        if cls_info and "iterLen" in cls_info.methods and "iterGet" in cls_info.methods:
            return _lower_iterable_for_in(gen, node, ir_iter, iter_type,
                                          cls_info, var_name, var_name2)

    # String iteration: for c in str
    if iter_type and iter_type.base == "string":
        return _lower_string_for_in(gen, node, ir_iter, var_name)

    # Fallback: assume list-like with .len and .data
    idx = gen.fresh_temp("__i")
    body_block = lower_block(gen, node.body)
    body_block.stmts.insert(0, IRVarDecl(
        c_type=CType(text="int"), name=var_name,
        init=IRIndex(obj=ir_iter, index=IRVar(name=idx))))
    return [IRFor(
        init=IRVarDecl(c_type=CType(text="int"), name=idx,
                       init=IRLiteral(text="0")),
        condition=IRBinOp(left=IRVar(name=idx), op="<",
                          right=IRVar(name=f"{_var_name_from_expr(ir_iter)}_len")),
        update=IRUnaryOp(op="++", operand=IRVar(name=idx), prefix=False),
        body=body_block,
    )]


def _lower_iterable_for_in(gen, node, ir_iter, iter_type, cls_info,
                            var_name, var_name2) -> list[IRStmt]:
    """Lower for-in via Iterable protocol (iterLen/iterGet/iterValueAt)."""
    from .statements import lower_block

    mangled = mangle_generic_type(iter_type.base, iter_type.generic_args)

    idx = gen.fresh_temp("__i")
    n_var = gen.fresh_temp("__n")
    body_block = lower_block(gen, node.body)

    # Element type from first generic arg
    elem_c = type_to_c(iter_type.generic_args[0]) if iter_type.generic_args else "int"

    # Two-variable iteration (e.g., for k, v in map): also call iterValueAt
    if var_name2 and "iterValueAt" in cls_info.methods and len(iter_type.generic_args) > 1:
        v_c = type_to_c(iter_type.generic_args[1])
        v_decl = IRVarDecl(
            c_type=CType(text=v_c), name=var_name2,
            init=IRCall(callee=f"{mangled}_iterValueAt",
                        args=[ir_iter, IRVar(name=idx)]))
        body_block.stmts.insert(0, v_decl)

    # Single-variable: T x = TYPE_iterGet(coll, __i);
    elem_decl = IRVarDecl(
        c_type=CType(text=elem_c), name=var_name,
        init=IRCall(callee=f"{mangled}_iterGet",
                    args=[ir_iter, IRVar(name=idx)]))
    body_block.stmts.insert(0, elem_decl)

    # int __n = TYPE_iterLen(coll);
    # for (int __i = 0; __i < __n; __i++) { body }
    return [
        IRVarDecl(c_type=CType(text="int"), name=n_var,
                  init=IRCall(callee=f"{mangled}_iterLen",
                              args=[ir_iter])),
        IRFor(init=IRVarDecl(c_type=CType(text="int"), name=idx,
                             init=IRLiteral(text="0")),
              condition=IRBinOp(left=IRVar(name=idx), op="<",
                                right=IRVar(name=n_var)),
              update=IRUnaryOp(op="++", operand=IRVar(name=idx),
                               prefix=False),
              body=body_block),
    ]


def _lower_string_for_in(gen, node, ir_iter, var_name) -> list[IRStmt]:
    """Lower for c in str to char-by-char iteration."""
    from .statements import lower_block

    idx = gen.fresh_temp("__i")
    body_block = lower_block(gen, node.body)
    char_decl = IRVarDecl(
        c_type=CType(text="char"), name=var_name,
        init=IRIndex(obj=ir_iter, index=IRVar(name=idx)))
    body_block.stmts.insert(0, char_decl)
    return [IRFor(
        init=IRVarDecl(c_type=CType(text="int"), name=idx,
                       init=IRLiteral(text="0")),
        condition=IRBinOp(
            left=IRIndex(obj=ir_iter, index=IRVar(name=idx)),
            op="!=",
            right=IRLiteral(text="'\\0'")),
        update=IRUnaryOp(op="++", operand=IRVar(name=idx), prefix=False),
        body=body_block,
    )]


def _lower_range_for(gen: IRGenerator, var_name: str,
                     args: list, body) -> list[IRStmt]:
    """Lower for x in range(...) to a C for loop."""
    from .statements import lower_block
    body_block = lower_block(gen, body)
    if len(args) == 1:
        end = _lower_expr(gen, args[0])
        return [IRFor(
            init=IRVarDecl(c_type=CType(text="int"), name=var_name,
                           init=IRLiteral(text="0")),
            condition=IRBinOp(left=IRVar(name=var_name), op="<", right=end),
            update=IRUnaryOp(op="++", operand=IRVar(name=var_name),
                             prefix=False),
            body=body_block)]
    elif len(args) == 2:
        start = _lower_expr(gen, args[0])
        end = _lower_expr(gen, args[1])
        return [IRFor(
            init=IRVarDecl(c_type=CType(text="int"), name=var_name,
                           init=start),
            condition=IRBinOp(left=IRVar(name=var_name), op="<", right=end),
            update=IRUnaryOp(op="++", operand=IRVar(name=var_name),
                             prefix=False),
            body=body_block)]
    elif len(args) >= 3:
        start = _lower_expr(gen, args[0])
        end = _lower_expr(gen, args[1])
        step = _lower_expr(gen, args[2])
        return [IRFor(
            init=IRVarDecl(c_type=CType(text="int"), name=var_name,
                           init=start),
            condition=IRTernary(
                condition=IRBinOp(left=step, op=">",
                                  right=IRLiteral(text="0")),
                true_expr=IRBinOp(left=IRVar(name=var_name), op="<",
                                  right=end),
                false_expr=IRBinOp(left=IRVar(name=var_name), op=">",
                                   right=end)),
            update=IRBinOp(left=IRVar(name=var_name), op="+=", right=step),
            body=body_block)]
    return [IRFor(
        init=IRVarDecl(c_type=CType(text="int"), name=var_name,
                       init=IRLiteral(text="0")),
        condition=IRBinOp(left=IRVar(name=var_name), op="<",
                          right=IRLiteral(text="0")),
        update=IRUnaryOp(op="++", operand=IRVar(name=var_name),
                         prefix=False),
        body=body_block)]


def _lower_c_for(gen: IRGenerator, node: CForStmt) -> IRFor:
    """Lower a C-style for statement."""
    from .statements import lower_block
    init_node = None
    if node.init:
        if isinstance(node.init, ForInitVar):
            vd = node.init.var_decl
            c_type = type_to_c(vd.type) if vd.type else "int"
            init_expr = _lower_expr(gen, vd.initializer) if vd.initializer else None
            init_node = IRVarDecl(c_type=CType(text=c_type), name=vd.name,
                                  init=init_expr)
        elif isinstance(node.init, ForInitExpr):
            init_node = IRExprStmt(expr=_lower_expr(gen, node.init.expression))

    cond_node = _lower_expr(gen, node.condition) if node.condition else IRLiteral(text="1")
    update_node = _lower_expr(gen, node.update) if node.update else None

    return IRFor(init=init_node, condition=cond_node, update=update_node,
                 body=lower_block(gen, node.body))


def _lower_expr(gen, node):
    """Convenience wrapper to avoid circular import at module level."""
    from .expressions import lower_expr
    return lower_expr(gen, node)


def _var_name_from_expr(expr) -> str:
    """Extract the variable name from an IRVar, for fallback iteration."""
    if isinstance(expr, IRVar):
        return expr.name
    return ""
