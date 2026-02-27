"""Iteration lowering: for-in, range-for, and C-style for loops."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import (
    CForStmt, ForInitExpr, ForInitVar, CallExpr, Identifier,
)
from ..nodes import (
    CType, IRBlock, IRContinue, IRFor, IRIf, IRRawC, IRStmt,
    IRUnaryOp, IRVarDecl, IRVar, IRFieldAccess, IRIndex,
)
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def _lower_for_in(gen: IRGenerator, node) -> list[IRStmt]:
    """Lower for-in to C-style for loop."""
    from .statements import lower_block, _quick_text
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

    # List iteration: for x in list
    if iter_type and iter_type.base == "List":
        idx = gen.fresh_temp("__i")
        body_block = lower_block(gen, node.body)
        # Prepend: T x = list->data[__i];
        elem_c = type_to_c(iter_type.generic_args[0]) if iter_type.generic_args else "int"
        elem_decl = IRVarDecl(
            c_type=CType(text=elem_c), name=var_name,
            init=IRIndex(
                obj=IRFieldAccess(obj=ir_iter, field="data", arrow=True),
                index=IRVar(name=idx)))
        body_block.stmts.insert(0, elem_decl)
        return [IRFor(
            init=f"int {idx} = 0",
            condition=f"{idx} < {_quick_text(ir_iter)}->len",
            update=f"{idx}++",
            body=body_block,
        )]

    # Map iteration: for k, v in map
    if iter_type and iter_type.base == "Map" and var_name2:
        idx = gen.fresh_temp("__i")
        body_block = lower_block(gen, node.body)
        k_c = type_to_c(iter_type.generic_args[0]) if iter_type.generic_args else "int"
        v_c = type_to_c(iter_type.generic_args[1]) if len(iter_type.generic_args) > 1 else "int"
        it = _quick_text(ir_iter)
        # Prepend: skip unoccupied, then extract k and v
        skip = IRIf(
            condition=IRUnaryOp(op="!", operand=IRIndex(
                obj=IRFieldAccess(obj=ir_iter, field="occupied", arrow=True),
                index=IRVar(name=idx)), prefix=True),
            then_block=IRBlock(stmts=[IRContinue()]),
        )

        k_decl = IRVarDecl(c_type=CType(text=k_c), name=var_name,
                           init=IRIndex(
                               obj=IRFieldAccess(obj=ir_iter, field="keys", arrow=True),
                               index=IRVar(name=idx)))
        v_decl = IRVarDecl(c_type=CType(text=v_c), name=var_name2,
                           init=IRIndex(
                               obj=IRFieldAccess(obj=ir_iter, field="values", arrow=True),
                               index=IRVar(name=idx)))
        body_block.stmts.insert(0, v_decl)
        body_block.stmts.insert(0, k_decl)
        body_block.stmts.insert(0, skip)
        return [IRFor(
            init=f"int {idx} = 0",
            condition=f"{idx} < {it}->cap",
            update=f"{idx}++",
            body=body_block,
        )]

    # Map keys-only iteration: for k in map (single variable)
    if iter_type and iter_type.base == "Map" and not var_name2:
        idx = gen.fresh_temp("__i")
        body_block = lower_block(gen, node.body)
        k_c = type_to_c(iter_type.generic_args[0]) if iter_type.generic_args else "int"
        it = _quick_text(ir_iter)
        skip = IRIf(
            condition=IRUnaryOp(op="!", operand=IRIndex(
                obj=IRFieldAccess(obj=ir_iter, field="occupied", arrow=True),
                index=IRVar(name=idx)), prefix=True),
            then_block=IRBlock(stmts=[IRContinue()]),
        )
        k_decl = IRVarDecl(c_type=CType(text=k_c), name=var_name,
                           init=IRIndex(
                               obj=IRFieldAccess(obj=ir_iter, field="keys", arrow=True),
                               index=IRVar(name=idx)))
        body_block.stmts.insert(0, k_decl)
        body_block.stmts.insert(0, skip)
        return [IRFor(
            init=f"int {idx} = 0",
            condition=f"{idx} < {it}->cap",
            update=f"{idx}++",
            body=body_block,
        )]

    # Set iteration: for x in set
    if iter_type and iter_type.base == "Set":
        idx = gen.fresh_temp("__i")
        body_block = lower_block(gen, node.body)
        elem_c = type_to_c(iter_type.generic_args[0]) if iter_type.generic_args else "int"
        it = _quick_text(ir_iter)

        skip = IRIf(
            condition=IRUnaryOp(op="!", operand=IRIndex(
                obj=IRFieldAccess(obj=ir_iter, field="occupied", arrow=True),
                index=IRVar(name=idx)), prefix=True),
            then_block=IRBlock(stmts=[IRContinue()]),
        )
        elem_decl = IRVarDecl(
            c_type=CType(text=elem_c), name=var_name,
            init=IRIndex(
                obj=IRFieldAccess(obj=ir_iter, field="keys", arrow=True),
                index=IRVar(name=idx)))
        body_block.stmts.insert(0, elem_decl)
        body_block.stmts.insert(0, skip)
        return [IRFor(
            init=f"int {idx} = 0",
            condition=f"{idx} < {it}->cap",
            update=f"{idx}++",
            body=body_block,
        )]

    # String iteration: for c in str
    if iter_type and iter_type.base == "string":
        idx = gen.fresh_temp("__i")
        body_block = lower_block(gen, node.body)
        it = _quick_text(ir_iter)
        char_decl = IRVarDecl(
            c_type=CType(text="char"), name=var_name,
            init=IRIndex(obj=ir_iter, index=IRVar(name=idx)))
        body_block.stmts.insert(0, char_decl)
        return [IRFor(
            init=f"int {idx} = 0",
            condition=f"{it}[{idx}] != '\\0'",
            update=f"{idx}++",
            body=body_block,
        )]

    # Fallback: assume list-like with .len and .data
    idx = gen.fresh_temp("__i")
    body_block = lower_block(gen, node.body)
    it = _quick_text(ir_iter)
    body_block.stmts.insert(0, IRVarDecl(
        c_type=CType(text="int"), name=var_name,
        init=IRRawC(text=f"{it}[{idx}]")))
    return [IRFor(
        init=f"int {idx} = 0",
        condition=f"{idx} < {it}_len",
        update=f"{idx}++",
        body=body_block,
    )]


def _lower_range_for(gen: IRGenerator, var_name: str,
                     args: list, body) -> list[IRStmt]:
    """Lower for x in range(...) to a C for loop."""
    from .statements import lower_block, _quick_text
    body_block = lower_block(gen, body)
    if len(args) == 1:
        end = _quick_text(_lower_expr(gen, args[0]))
        return [IRFor(init=f"int {var_name} = 0",
                      condition=f"{var_name} < {end}",
                      update=f"{var_name}++",
                      body=body_block)]
    elif len(args) == 2:
        start = _quick_text(_lower_expr(gen, args[0]))
        end = _quick_text(_lower_expr(gen, args[1]))
        return [IRFor(init=f"int {var_name} = {start}",
                      condition=f"{var_name} < {end}",
                      update=f"{var_name}++",
                      body=body_block)]
    elif len(args) >= 3:
        start = _quick_text(_lower_expr(gen, args[0]))
        end = _quick_text(_lower_expr(gen, args[1]))
        step = _quick_text(_lower_expr(gen, args[2]))
        return [IRFor(
            init=f"int {var_name} = {start}",
            condition=f"({step} > 0 ? {var_name} < {end} : {var_name} > {end})",
            update=f"{var_name} += {step}",
            body=body_block)]
    return [IRFor(init=f"int {var_name} = 0",
                  condition=f"{var_name} < 0",
                  update=f"{var_name}++",
                  body=body_block)]


def _lower_c_for(gen: IRGenerator, node: CForStmt) -> IRFor:
    """Lower a C-style for statement."""
    from .statements import lower_block, _quick_text
    init_text = ""
    if node.init:
        if isinstance(node.init, ForInitVar):
            vd = node.init.var_decl
            c_type = type_to_c(vd.type) if vd.type else "int"
            if vd.initializer:
                init_text = f"{c_type} {vd.name} = {_quick_text(_lower_expr(gen, vd.initializer))}"
            else:
                init_text = f"{c_type} {vd.name}"
        elif isinstance(node.init, ForInitExpr):
            init_text = _quick_text(_lower_expr(gen, node.init.expression))

    cond_text = _quick_text(_lower_expr(gen, node.condition)) if node.condition else "1"
    update_text = _quick_text(_lower_expr(gen, node.update)) if node.update else ""

    return IRFor(init=init_text, condition=cond_text, update=update_text,
                 body=lower_block(gen, node.body))


def _lower_expr(gen, node):
    """Convenience wrapper to avoid circular import at module level."""
    from .expressions import lower_expr
    return lower_expr(gen, node)
