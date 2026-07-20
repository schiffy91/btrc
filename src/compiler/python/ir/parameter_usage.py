"""Normalize unused C parameters into explicit structured discards."""

from __future__ import annotations

from .nodes import IRExprStmt, IRModule, IRVar, IRVarDecl
from .optimizer_walk import iter_ir_nodes


def consume_unused_parameters(module: IRModule) -> None:
    """Prepend a discard for every parameter not referenced by its function.

    Function signatures are part of the language/API contract, so lowering may
    not remove an unused parameter.  An ``IRExprStmt(IRVar(...))`` records that
    its value is intentionally ignored; the emitter renders that statement as a
    standard-C ``(void)(name);`` expression.

    Textual escape hatches are deliberately ignored here.  Missing a use only
    adds a harmless discard, while treating an identifier inside raw text as a
    binding use could leave the generated C with an unused-parameter warning.
    """
    for function in module.function_defs:
        if function.body is None or not function.params:
            continue

        nodes = tuple(iter_ir_nodes(function.body))
        references = {node.name for node in nodes if isinstance(node, IRVar)}
        declarations = {node.name for node in nodes if isinstance(node, IRVarDecl)}
        existing_discards = {
            statement.expr.name
            for statement in function.body.stmts
            if (isinstance(statement, IRExprStmt) and isinstance(statement.expr, IRVar))
        }
        unused = [
            parameter.name
            for parameter in function.params
            if (
                parameter.name not in existing_discards
                and (parameter.name not in references or parameter.name in declarations)
            )
        ]
        function.body.stmts[0:0] = [IRExprStmt(expr=IRVar(name=name)) for name in unused]


__all__ = ["consume_unused_parameters"]
