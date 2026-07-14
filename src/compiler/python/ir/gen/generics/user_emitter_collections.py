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
    from .user_emitter_scopes import exception_cleanup_active

    cleanup_active = exception_cleanup_active(emitter)
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
        from ..temporary_cleanup import cleanup_registration

        cleanup_decls, cleanup_exprs = cleanup_registration(
            emitter._gen,
            temporary_decl,
            target_type,
            "__btrc_collection_cleanup",
            active=True,
            fresh_temp=emitter._fresh_temp,
            activate_cleanup=(lambda: _activate_cleanup_registration(emitter)),
        )
        declarations.extend(cleanup_decls)
        sequence.extend(cleanup_exprs)

    if is_list:
        for element in literal.elements:
            sequence.append(
                emitter._sequence_owned_effect(
                    [element],
                    lambda element=element: IRCall(
                        callee=f"{target}_push",
                        args=[value, emitter._expr(element)],
                    ),
                )
            )
    else:
        for entry in literal.entries:
            sequence.append(
                emitter._sequence_owned_effect(
                    [entry.key, entry.value],
                    lambda entry=entry: IRCall(
                        callee=f"{target}_put",
                        args=[
                            value,
                            emitter._expr(entry.key),
                            emitter._expr(entry.value),
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


def _activate_cleanup_registration(emitter):
    from .user_emitter_scopes import mark_cleanup_registration

    mark_cleanup_registration(emitter)


__all__ = ["lower_collection_literal"]
