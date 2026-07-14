"""Iteration lowering: for-in, range-for, and C-style for loops."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    CallExpr,
    Identifier,
)
from ..nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRFieldAccess,
    IRFor,
    IRIndex,
    IRLiteral,
    IRStmt,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .iteration_bindings import IterationBinding
from .iteration_loops import _lower_c_for, _lower_range_for  # noqa: F401
from .iteration_strings import lower_string_for_in as _lower_string_for_in
from .types import mangle_generic_type, type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def _lower_for_in(gen: IRGenerator, node) -> list[IRStmt]:
    """Lower for-in to C-style for loop."""
    from .statements import _lower_loop_body

    iterable = node.iterable
    var_name = node.var_name
    var_name2 = getattr(node, "var_name2", None)

    # Detect range() calls
    if isinstance(iterable, CallExpr) and isinstance(iterable.callee, Identifier):
        if iterable.callee.name == "range":
            return _lower_range_for(gen, var_name, iterable.args, node.body)

    # Get the iterable type from the analyzer
    iter_type = gen.analyzed.node_types.get(id(iterable))
    ir_iter = _lower_expr(gen, iterable)

    # Iterable protocol: any class with iterLen + iterGet methods
    if iter_type:
        cls_info = gen.analyzed.class_table.get(iter_type.base)
        if cls_info and "iterLen" in cls_info.methods and "iterGet" in cls_info.methods:
            return _lower_iterable_for_in(gen, node, ir_iter, iter_type, cls_info, var_name, var_name2)

    # String iteration: for c in str
    if iter_type and iter_type.base == "string":
        return _lower_string_for_in(gen, node, ir_iter, var_name)

    # Fallback: assume list-like with ->len and ->data[i]
    # Use a temp variable so the iterable is only evaluated once and
    # we always have a named variable for field access (fixes broken
    # codegen when ir_iter is not a simple IRVar).
    idx = gen.fresh_temp("__i")
    tmp_iter = gen.fresh_temp("__iter")
    iter_c_type = "void*"
    if iter_type:
        iter_c_type = type_to_c(iter_type)
        if not iter_c_type.endswith("*"):
            iter_c_type += "*"
    if iter_type and iter_type.generic_args:
        elem_c = _iter_value_c(gen, iter_type.generic_args[0])
    else:
        elem_c = "int"

    prefix = [
        IRVarDecl(
            c_type=CType(text=iter_c_type),
            name=tmp_iter,
            init=ir_iter,
        )
    ]
    from .iteration_ownership import (
        begin_owned_iterable,
        finish_owned_iterable,
    )

    owner = begin_owned_iterable(gen, iterable, iter_type, tmp_iter, prefix)
    data_expr = IRFieldAccess(obj=IRVar(name=tmp_iter), field="data", arrow=True)
    elem_type = iter_type.generic_args[0] if iter_type and iter_type.generic_args else None
    body_block = _lower_loop_body(
        gen,
        node.body,
        iteration_bindings=[
            IterationBinding(
                name=var_name,
                c_type=elem_c,
                type_expr=elem_type,
                value=IRIndex(obj=data_expr, index=IRVar(name=idx)),
                owned=False,
            )
        ],
    )
    result = [
        *prefix,
        IRFor(
            init=IRVarDecl(c_type=CType(text="int"), name=idx, init=IRLiteral(text="0")),
            condition=IRBinOp(
                left=IRVar(name=idx), op="<", right=IRFieldAccess(obj=IRVar(name=tmp_iter), field="len", arrow=True)
            ),
            update=IRUnaryOp(op="++", operand=IRVar(name=idx), prefix=False),
            body=body_block,
        ),
    ]
    result.extend(finish_owned_iterable(gen, owner))
    return result


def _lower_iterable_for_in(gen, node, ir_iter, iter_type, cls_info, var_name, var_name2) -> list[IRStmt]:
    """Lower for-in via Iterable protocol (iterLen/iterGet/iterValueAt)."""
    from .statements import _lower_loop_body

    mangled = mangle_generic_type(iter_type.base, iter_type.generic_args) if iter_type.generic_args else iter_type.base

    # Hoist every managed iterable. Besides exact-once evaluation, the named
    # slot can own a fresh result or retain a borrowed projection/call for the
    # entire loop, even if the body destroys or rebinds its original owner.
    from .iteration_ownership import (
        begin_owned_iterable,
        finish_owned_iterable,
    )

    tmp_iter = gen.fresh_temp("__iter")
    iter_c_type = type_to_c(iter_type)
    if not iter_c_type.endswith("*"):
        iter_c_type += "*"
    hoist_decl = IRVarDecl(c_type=CType(text=iter_c_type), name=tmp_iter, init=ir_iter)
    ir_iter = IRVar(name=tmp_iter)

    stmts: list[IRStmt] = [hoist_decl]
    owner = begin_owned_iterable(
        gen,
        node.iterable,
        iter_type,
        hoist_decl.name,
        stmts,
    )

    idx = gen.fresh_temp("__i")
    n_var = gen.fresh_temp("__n")
    # Element type from first generic arg. Class values are reference types in
    # btrc, and generic methods are monomorphized with pointer return types for
    # class arguments, so the loop binding must match the concrete iterGet ABI.
    elem_type = _iter_method_return_type(cls_info, iter_type, "iterGet")
    elem_c = _iter_value_c(gen, elem_type)

    bindings = [
        IterationBinding(
            name=var_name,
            c_type=elem_c,
            type_expr=elem_type,
            value=IRCall(
                callee=f"{mangled}_iterGet",
                args=[ir_iter, IRVar(name=idx)],
            ),
            owned=True,
        )
    ]

    # Two-variable iteration (e.g., for k, v in map): also call iterValueAt
    if var_name2 and "iterValueAt" in cls_info.methods:
        value_type = _iter_method_return_type(cls_info, iter_type, "iterValueAt")
        v_c = _iter_value_c(gen, value_type)
        bindings.append(
            IterationBinding(
                name=var_name2,
                c_type=v_c,
                type_expr=value_type,
                value=IRCall(
                    callee=f"{mangled}_iterValueAt",
                    args=[ir_iter, IRVar(name=idx)],
                ),
                owned=True,
            )
        )

    body_block = _lower_loop_body(gen, node.body, iteration_bindings=bindings)

    # int __n = TYPE_iterLen(coll);
    # for (int __i = 0; __i < __n; __i++) { body }
    stmts.append(
        IRVarDecl(c_type=CType(text="int"), name=n_var, init=IRCall(callee=f"{mangled}_iterLen", args=[ir_iter]))
    )
    stmts.append(
        IRFor(
            init=IRVarDecl(c_type=CType(text="int"), name=idx, init=IRLiteral(text="0")),
            condition=IRBinOp(left=IRVar(name=idx), op="<", right=IRVar(name=n_var)),
            update=IRUnaryOp(op="++", operand=IRVar(name=idx), prefix=False),
            body=body_block,
        ),
    )
    stmts.extend(finish_owned_iterable(gen, owner))
    return stmts


def _iter_value_c(gen: IRGenerator, t) -> str:
    c_type = type_to_c(t)
    if t and t.base in gen.analyzed.class_table and not c_type.endswith("*"):
        return f"{c_type}*"
    return c_type


def _iter_method_return_type(cls_info, iter_type, method_name):
    """Resolve an iterable protocol method for one concrete instance."""
    method = cls_info.methods[method_name]
    if not cls_info.generic_params:
        return method.return_type
    from .generics.core import _resolve_type

    substitutions = dict(zip(cls_info.generic_params, iter_type.generic_args))
    return _resolve_type(method.return_type, substitutions)


def _lower_expr(gen, node):
    """Convenience wrapper to avoid circular import at module level."""
    from .expressions import lower_expr

    return lower_expr(gen, node)
