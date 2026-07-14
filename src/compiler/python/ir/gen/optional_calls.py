"""Lazy, single-evaluation lowering for optional method calls."""

from __future__ import annotations

from dataclasses import replace

from ...ast_nodes import CallExpr, FieldAccessExpr
from ..nodes import (
    CType,
    IRBinOp,
    IRCast,
    IRCommaExpr,
    IRLiteral,
    IRStmtExpr,
    IRTernary,
    IRVar,
    IRVarDecl,
)
from .arc_ops import release_if_present
from .arguments import arg_names_for
from .arguments_arc import plan_call_operands
from .call_boundary import sequence_call_boundary
from .optional_values import optional_zero_value
from .ownership import owns_result
from .types import type_to_c


def lower_optional_method_call(gen, node: CallExpr):
    """Lower ``receiver?.method(args)`` with lazy managed arguments."""
    assert isinstance(node.callee, FieldAccessExpr) and node.callee.optional
    from .call_effects import (
        callable_for_call,
        owned_transfer_param_indices,
    )
    from .expressions import lower_expr

    receiver_node = node.callee.obj
    receiver_type = gen.analyzed.node_types.get(id(receiver_node))
    receiver_decl = _temp_decl(
        gen,
        "__btrc_optional_receiver",
        type_to_c(receiver_type) if receiver_type is not None else "void*",
    )
    receiver = IRVar(name=receiver_decl.name)
    declarations = [receiver_decl]
    prelude = [
        IRBinOp(
            left=receiver,
            op="=",
            right=lower_expr(gen, receiver_node),
        )
    ]
    receiver_suffix = _owned_receiver_cleanup(
        gen,
        receiver,
        receiver_type,
        receiver_node,
        declarations,
        prelude,
    )

    declaration = callable_for_call(gen, node)
    params = declaration.params if declaration is not None else []
    operands, needs_boundary = plan_call_operands(
        gen,
        params,
        node.args,
        arg_names_for(node, len(node.args)),
        transferred_params=owned_transfer_param_indices(declaration),
    )
    result_type = gen.analyzed.node_types.get(id(node))

    def build_call(overrides):
        all_overrides = {id(receiver_node): receiver, **overrides}
        previous = {key: gen._owning_temp_overrides.get(key) for key in all_overrides}
        gen._owning_temp_overrides.update(all_overrides)
        try:
            from .methods import lower_method_call

            plain_callee = replace(node.callee, optional=False)
            return lower_method_call(gen, replace(node, callee=plain_callee))
        finally:
            for key, value in previous.items():
                if value is None:
                    gen._owning_temp_overrides.pop(key, None)
                else:
                    gen._owning_temp_overrides[key] = value

    if needs_boundary:
        call = sequence_call_boundary(
            gen,
            operands,
            lower_expr=lambda value: lower_expr(gen, value),
            build_call=build_call,
            result_c_type=(type_to_c(result_type) if result_type is not None else None),
            fresh_temp=gen.fresh_temp,
            cleanup_active=gen.exception_cleanup_active(),
            record_decl=gen._func_var_decls.append,
        )
    else:
        call = build_call({})

    true_value = _release_receiver_after_call(
        gen,
        call,
        result_type,
        receiver_suffix,
        declarations,
    )
    prelude.append(
        IRTernary(
            condition=IRBinOp(
                left=receiver,
                op="!=",
                right=IRLiteral(text="NULL"),
            ),
            true_expr=true_value,
            false_expr=optional_zero_value(gen, result_type),
        )
    )
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=prelude),
    )


def _owned_receiver_cleanup(
    gen,
    receiver,
    receiver_type,
    receiver_node,
    declarations,
    prelude,
):
    if receiver_type is None or not owns_result(gen, receiver_node):
        return []
    from .temporary_cleanup import cleanup_registration

    cleanup_decls, cleanup_exprs = cleanup_registration(
        gen,
        receiver,
        receiver_type,
        "__btrc_optional_receiver_cleanup",
    )
    declarations.extend(cleanup_decls)
    prelude.extend(cleanup_exprs)
    from .arc_ops import poll_release_batch

    suffix = [
        release_if_present(gen, receiver, receiver_type),
        IRBinOp(left=receiver, op="=", right=IRLiteral(text="NULL")),
    ]
    flush = poll_release_batch(gen, types=[receiver_type])
    if flush is not None:
        suffix.append(flush)
    return suffix


def _release_receiver_after_call(
    gen,
    call,
    result_type,
    suffix,
    declarations,
):
    if not suffix:
        return call
    sequence = []
    if result_type is not None and result_type.base != "void":
        result_decl = _temp_decl(
            gen,
            "__btrc_optional_result",
            type_to_c(result_type),
        )
        declarations.append(result_decl)
        result = IRVar(name=result_decl.name)
        sequence.append(IRBinOp(left=result, op="=", right=call))
        sequence.extend(suffix)
        sequence.append(result)
    else:
        sequence.append(call)
        sequence.extend(suffix)
        sequence.append(IRCast(target_type=CType(text="void"), expr=IRLiteral(text="0")))
    return IRCommaExpr(expressions=sequence)


def _temp_decl(gen, prefix: str, c_type: str, init=None) -> IRVarDecl:
    declaration = IRVarDecl(
        c_type=CType(text=c_type),
        name=gen.fresh_temp(prefix),
        init=init,
    )
    gen._func_var_decls.append(declaration)
    return declaration


__all__ = ["lower_optional_method_call"]
