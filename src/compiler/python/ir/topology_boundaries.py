"""Exclude collection shape mutations from ARC collector snapshots."""

from __future__ import annotations

from .completion import StatementSequence
from .expr_nodes import (
    CType,
    IRAddressOf,
    IRCall,
    IRCast,
    IRFunctionRef,
    IRVar,
)
from .nodes import (
    IRBlock,
    IRCase,
    IRDoWhile,
    IRExprStmt,
    IRFor,
    IRFunctionDef,
    IRIf,
    IRReturn,
    IRSwitch,
    IRVarDecl,
    IRWhile,
)
from .topology_queries import CollectionTopologyMutation


class CollectionTopologyBoundary:
    """Own one atomic collection-shape mutation boundary."""

    def __init__(self, generator, function: IRFunctionDef):
        self._generator = generator
        self._function = function
        self._token = ""
        self._marker: str | None = None

    def install(self) -> bool:
        """Protect a mutating collection method from partial ARC snapshots."""

        body = self._function.body
        if body is None or not CollectionTopologyMutation(body).exists():
            return False

        self._token = self._generator.fresh_temp("__btrc_topology_scope")
        cleanup_enabled = bool(
            getattr(
                self._generator,
                "cross_function_cleanup_enabled",
                False,
            )
        )
        self._marker = self._generator.fresh_temp("__btrc_topology_cleanup") if cleanup_enabled else None
        self._generator.helpers.use("__btrc_arc_topology_begin")
        self._generator.helpers.use("__btrc_arc_topology_complete")
        if cleanup_enabled:
            self._generator.helpers.use("__btrc_cleanup_mark")
            self._generator.helpers.use("__btrc_arc_topology_cleanup")
            self._generator.helpers.use("__btrc_discard_cleanups_to")

        self._rewrite_block(body)
        if StatementSequence(body.stmts).may_fall_through():
            body.stmts.extend(self._epilogue())
        body.stmts[0:0] = self._prologue()
        return True

    def _prologue(self) -> list:
        statements = []
        if self._marker is not None:
            statements.append(
                IRVarDecl(
                    c_type=CType(text="int"),
                    name=self._marker,
                    init=IRCall(
                        callee="__btrc_cleanup_mark",
                        args=[],
                        helper_ref="__btrc_cleanup_mark",
                    ),
                )
            )
        token_declaration = IRVarDecl(
            c_type=CType(text="void*"),
            name=self._token,
            init=IRCall(
                callee="__btrc_arc_topology_begin",
                args=[],
                helper_ref="__btrc_arc_topology_begin",
            ),
        )
        statements.append(token_declaration)
        if self._marker is not None:
            from .gen.cleanup_slots import register_cleanup_slot

            statements.append(
                IRExprStmt(
                    expr=register_cleanup_slot(
                        self._generator,
                        token_declaration,
                        IRFunctionRef(name="__btrc_arc_topology_cleanup"),
                        direct=True,
                    )
                )
            )
        return statements

    def _epilogue(self) -> list:
        statements = [
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_arc_topology_complete",
                    args=[
                        IRCast(
                            target_type=CType(text="void* volatile*"),
                            expr=IRAddressOf(expr=IRVar(name=self._token)),
                        )
                    ],
                    helper_ref="__btrc_arc_topology_complete",
                )
            )
        ]
        if self._marker is not None:
            statements.append(
                IRExprStmt(
                    expr=IRCall(
                        callee="__btrc_discard_cleanups_to",
                        args=[IRVar(name=self._marker)],
                        helper_ref="__btrc_discard_cleanups_to",
                    )
                )
            )
        return statements

    def _rewrite_block(self, block: IRBlock) -> None:
        rewritten = []
        for statement in block.stmts:
            self._rewrite_nested(statement)
            if isinstance(statement, IRReturn):
                if statement.value is not None:
                    result = self._generator.fresh_temp("__btrc_topology_return")
                    rewritten.append(
                        IRVarDecl(
                            c_type=self._function.return_type,
                            name=result,
                            init=statement.value,
                        )
                    )
                    statement.value = IRVar(name=result)
                rewritten.extend(self._epilogue())
            rewritten.append(statement)
        block.stmts = rewritten

    def _rewrite_nested(self, statement) -> None:
        if isinstance(statement, IRBlock):
            self._rewrite_block(statement)
        elif isinstance(statement, IRIf):
            self._rewrite_block(statement.then_block)
            if statement.else_block is not None:
                self._rewrite_block(statement.else_block)
        elif isinstance(statement, (IRWhile, IRDoWhile, IRFor)):
            self._rewrite_block(statement.body)
        elif isinstance(statement, IRSwitch):
            for case in statement.cases:
                self._rewrite_case(case)

    def _rewrite_case(self, case: IRCase) -> None:
        block = IRBlock(stmts=case.body)
        self._rewrite_block(block)
        case.body = block.stmts


__all__ = ["CollectionTopologyBoundary"]
