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
)
from .arc_ops import release_if_present
from .arguments import arg_names_for, bind_arg_nodes_to_params
from .arguments_arc import plan_call_operands
from .call_boundary import sequence_call_boundary
from .optional_call_temporaries import optional_call_temp
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
    receiver_decl = optional_call_temp(
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
    declaration = callable_for_call(gen, node)
    from .call_contracts import resolved_params_for_call

    params = resolved_params_for_call(gen, node)
    plain_callee = replace(node.callee, optional=False)
    plain_node = replace(node, callee=plain_callee)
    from .callable_fields import callable_field_signature

    callable_field = callable_field_signature(gen, node.callee) is not None
    from .evaluation_order import has_observable_effect

    has_later_operand = any(
        has_observable_effect(gen, argument)
        for _index, argument, _default in bind_arg_nodes_to_params(
            params, node.args, arg_names_for(node, len(node.args))
        )
    )
    from .receiver_pinning import receiver_pin_required

    receiver_suffix = _receiver_cleanup(
        gen,
        receiver_decl,
        receiver_type,
        receiver_node,
        declarations,
        prelude,
        pin_borrowed=receiver_pin_required(
            gen,
            receiver_node,
            declared_call=declaration is not None,
            later_effect=has_later_operand,
            owned_local_type=gen.managed_local_type,
        ),
    )
    operands, needs_boundary = plan_call_operands(
        gen,
        params,
        node.args,
        arg_names_for(node, len(node.args)),
        callee=node.callee if callable_field else None,
        transferred_params=owned_transfer_param_indices(declaration),
        call=plain_node,
        default_receiver_value=receiver,
    )
    result_type = gen.analyzed.node_types.get(id(node))

    def lower_guarded_operand(value):
        previous = gen._owning_temp_overrides.get(id(receiver_node))
        gen._owning_temp_overrides[id(receiver_node)] = receiver
        try:
            return lower_expr(gen, plain_callee if value is node.callee else value)
        finally:
            if previous is None:
                gen._owning_temp_overrides.pop(id(receiver_node), None)
            else:
                gen._owning_temp_overrides[id(receiver_node)] = previous

    def build_call(overrides):
        all_overrides = {id(receiver_node): receiver, **overrides}
        if id(node.callee) in overrides:
            all_overrides[id(plain_callee)] = overrides[id(node.callee)]
        previous = {key: gen._owning_temp_overrides.get(key) for key in all_overrides}
        gen._owning_temp_overrides.update(all_overrides)
        try:
            from .methods import lower_method_call

            return lower_method_call(gen, plain_node)
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
            lower_expr=lower_guarded_operand,
            build_call=build_call,
            result_c_type=(type_to_c(result_type) if result_type is not None else None),
            fresh_temp=gen.fresh_temp,
            cleanup_active=gen.exception_cleanup_active(),
            record_decl=gen._func_var_decls.append,
            result_type=result_type,
            result_owned=owns_result(gen, node),
        )
    else:
        call = build_call({})

    true_value = _release_receiver_after_call(
        gen,
        call,
        result_type,
        receiver_suffix,
        declarations,
        result_owned=owns_result(gen, node),
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


def _receiver_cleanup(
    gen,
    receiver_decl,
    receiver_type,
    receiver_node,
    declarations,
    prelude,
    *,
    pin_borrowed,
):
    receiver = IRVar(name=receiver_decl.name)
    owned = bool(receiver_type is not None and owns_result(gen, receiver_node))
    from .evaluation_order import borrowed_value_can_be_pinned
    from .managed_values import is_managed_type

    pinned = bool(
        receiver_type is not None
        and pin_borrowed
        and borrowed_value_can_be_pinned(receiver_node)
        and not owned
        and is_managed_type(gen, receiver_type)
    )
    if not owned and not pinned:
        return []
    if pinned:
        from .managed_values import retain_value

        prelude.append(retain_value(gen, receiver, receiver_type))
    from .temporary_cleanup import cleanup_registration

    cleanup_decls, cleanup_exprs = cleanup_registration(
        gen,
        receiver_decl,
        receiver_type,
        "__btrc_optional_receiver_cleanup",
    )
    declarations.extend(cleanup_decls)
    prelude.extend(cleanup_exprs)
    from .arc_ops import poll_release_batch

    saved_decl = optional_call_temp(
        gen,
        "__btrc_optional_receiver_release",
        type_to_c(receiver_type),
        IRLiteral(text="NULL"),
    )
    declarations.append(saved_decl)
    saved = IRVar(name=saved_decl.name)
    suffix = [
        IRBinOp(left=saved, op="=", right=receiver),
        IRBinOp(left=receiver, op="=", right=IRLiteral(text="NULL")),
        release_if_present(gen, saved, receiver_type),
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
    *,
    result_owned,
):
    if not suffix:
        return call
    sequence = []
    if result_type is not None and result_type.base != "void":
        result_decl = optional_call_temp(
            gen,
            "__btrc_optional_result",
            type_to_c(result_type),
        )
        declarations.append(result_decl)
        result = IRVar(name=result_decl.name)
        sequence.append(IRBinOp(left=result, op="=", right=call))
        from .managed_values import is_managed_type

        protect_result = bool(result_owned and is_managed_type(gen, result_type) and gen.exception_cleanup_active())
        if protect_result:
            from .temporary_cleanup import cleanup_registration

            cleanup_decls, cleanup_exprs = cleanup_registration(
                gen,
                result_decl,
                result_type,
                "__btrc_optional_result_cleanup",
            )
            declarations.extend(cleanup_decls)
            sequence.extend(cleanup_exprs)
            handoff_decl = optional_call_temp(
                gen,
                "__btrc_optional_result_handoff",
                type_to_c(result_type),
                IRLiteral(text="NULL"),
            )
            declarations.append(handoff_decl)
            handoff = IRVar(name=handoff_decl.name)
        sequence.extend(suffix)
        if protect_result:
            sequence.extend(
                [
                    IRBinOp(left=handoff, op="=", right=result),
                    IRBinOp(
                        left=result,
                        op="=",
                        right=IRLiteral(text="NULL"),
                    ),
                    handoff,
                ]
            )
        else:
            sequence.append(result)
    else:
        sequence.append(call)
        sequence.extend(suffix)
        sequence.append(IRCast(target_type=CType(text="void"), expr=IRLiteral(text="0")))
    return IRCommaExpr(expressions=sequence)


__all__ = ["lower_optional_method_call"]
