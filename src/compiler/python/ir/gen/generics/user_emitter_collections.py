"""Collection literal ownership in monomorphized generic method bodies."""

from __future__ import annotations

from ...nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCommaExpr,
    IRLiteral,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)


def lower_collection_literal(emitter, target: str, literal, target_type=None):
    """Build an owning collection while consuming caller-owned elements."""
    from ....ast_nodes import BraceInitializer, ListLiteral

    constructor = IRCall(callee=f"{target}_new", args=[])
    is_list = isinstance(literal, (BraceInitializer, ListLiteral))
    items = literal.elements if is_list else literal.entries
    if not items:
        return constructor
    cleanup_active = emitter.exception_cleanup_active()
    if cleanup_active and target_type is None:
        from ..errors import CodegenError

        raise CodegenError("generic collection literal in try scope requires a concrete type")

    temporary = emitter._fresh_temp("__list" if is_list else "__map")
    c_type = emitter.iter_value_c(target_type) if target_type is not None else f"{target}*"
    temporary_decl = IRVarDecl(c_type=CType(text=c_type), name=temporary)
    emitter._func_var_decls.append(temporary_decl)
    declarations = [temporary_decl]
    value = IRVar(name=temporary)
    sequence = [IRBinOp(left=value, op="=", right=constructor)]

    result = value
    if cleanup_active:
        cleanup_decls, cleanup_exprs = emitter._boundary_lifetime.cleanup_registration(
            temporary_decl,
            target_type,
            "__btrc_collection_cleanup",
            active=True,
            activate_cleanup=(lambda: _activate_cleanup_registration(emitter)),
        )
        declarations.extend(cleanup_decls)
        sequence.extend(cleanup_exprs)

    if is_list:
        element_type = target_type.generic_args[0] if target_type is not None and target_type.generic_args else None
        for element in literal.elements:
            sequence.append(
                _prepared_effect(
                    emitter,
                    [(element, element_type)],
                    lambda values, element=element: IRCall(
                        callee=f"{target}_push",
                        args=[value, values[id(element)]],
                    ),
                )
            )
    else:
        key_type, value_type = (
            target_type.generic_args if target_type is not None and len(target_type.generic_args) == 2 else (None, None)
        )
        for entry in literal.entries:
            sequence.append(
                _prepared_effect(
                    emitter,
                    [(entry.key, key_type), (entry.value, value_type)],
                    lambda values, entry=entry: IRCall(
                        callee=f"{target}_put",
                        args=[
                            value,
                            values[id(entry.key)],
                            values[id(entry.value)],
                        ],
                    ),
                )
            )

    if cleanup_active:
        result_decl = IRVarDecl(c_type=CType(text=c_type), name=emitter._fresh_temp("__collection_result"))
        emitter._func_var_decls.append(result_decl)
        declarations.append(result_decl)
        result = IRVar(name=result_decl.name)
        sequence.extend(
            [
                IRBinOp(left=result, op="=", right=value),
                IRBinOp(left=value, op="=", right=IRLiteral(text="NULL")),
            ]
        )
    sequence.append(result)
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=sequence),
    )


def _prepared_effect(emitter, values, build):
    from ..call_boundary import CallOperand
    from ..prepared_values import prepare_generic_value, prepared_value_pin_flags

    prepared = [
        (
            node,
            prepare_generic_value(
                emitter,
                node,
                target_type or emitter._resolve_expr_type(node),
            ),
        )
        for node, target_type in values
    ]
    if len(prepared) == 1 and not prepared[0][1].owned:
        node, value = prepared[0]
        return build({id(node): value.value})
    pins = prepared_value_pin_flags(
        emitter._gen,
        prepared,
        type_of=emitter._resolve_expr_type,
    )
    operands = []
    for index, (node, value) in enumerate(prepared):
        operands.append(
            CallOperand(
                node=node,
                type_expr=value.effective_type,
                c_type=emitter.iter_value_c(value.effective_type),
                pin=pins[index],
                owned=value.owned,
                lowered=value.value,
            )
        )
    return emitter._boundary_ownership.boundaries.sequence(
        operands,
        lower_expr=lambda _node: None,
        build_call=build,
        result_c_type=None,
        activate_cleanup=emitter._activate_cleanup_registration,
    )


def _activate_cleanup_registration(emitter):
    emitter.mark_cleanup_registration()


__all__ = ["lower_collection_literal"]
