"""Normalize unused C parameters into explicit structured discards."""

from __future__ import annotations

from .expr_nodes import IRVar
from .module import IRModule
from .nodes import IRExprStmt, IRVarDecl
from .optimizer_walk import IRTree


class UnusedParameterConsumer:
    """Normalize unused C parameters in one IR module."""

    def __init__(self, module: IRModule):
        self._module = module

    def normalize(self) -> None:
        """Prepend structured discards for parameters without binding uses.

        Function signatures are part of the language/API contract, so this
        pass may not remove parameters. Textual escape hatches are deliberately
        ignored: an extra discard is harmless, while a textual false positive
        would leave strict-C output with an unused-parameter warning.
        """

        for function in self._module.function_defs:
            if function.body is None or not function.params:
                continue

            nodes = tuple(IRTree(function.body))
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


__all__ = ["UnusedParameterConsumer"]
