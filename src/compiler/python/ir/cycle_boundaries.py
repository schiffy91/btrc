"""Install deterministic drains at observable cycle-ownership boundaries."""

from __future__ import annotations

import dataclasses

from .completion import sequence_may_fall_through
from .nodes import (
    IRBlock,
    IRCall,
    IRCase,
    IRDoWhile,
    IRExprStmt,
    IRFor,
    IRFunctionDef,
    IRIf,
    IRModule,
    IRReturn,
    IRSwitch,
    IRVar,
    IRVarDecl,
    IRWhile,
)

PUBLIC_COLLECTION_BASES = frozenset({"Array", "List", "Map", "Set", "Vector"})
_PROGRAM_ENTRIES = frozenset({"btrc_main", "main"})
_CYCLABLE_RELEASE_HELPERS = frozenset(
    {
        "__btrc_arc_release",
        "__btrc_arc_release_edge",
        "__btrc_arc_replace_edge",
    }
)


def install_function_cycle_boundary(function: IRFunctionDef) -> bool:
    """Force-drain a release-bearing externally observable function."""
    if function.body is None or not contains_cyclable_release(function.body):
        return False
    _rewrite_block(function, function.body, [0], _local_names(function))
    if sequence_may_fall_through(function.body.stmts) and not _ends_with_flush(function.body.stmts):
        function.body.stmts.append(_flush_stmt())
    return True


def install_program_cycle_boundary(module: IRModule) -> bool:
    """Drain deferred suspects before a live executable entry point exits."""
    if not any(
        contains_cyclable_release(function.body) for function in module.function_defs if function.body is not None
    ):
        return False
    installed = False
    for function in module.function_defs:
        if function.name in _PROGRAM_ENTRIES:
            _rewrite_block(function, function.body, [0], _local_names(function))
            if sequence_may_fall_through(function.body.stmts) and not _ends_with_flush(function.body.stmts):
                function.body.stmts.append(_flush_stmt())
            installed = True
    return installed


def contains_cyclable_release(value) -> bool:
    """Whether structured IR can enqueue a graph-bearing release suspect."""
    if isinstance(value, IRCall):
        return value.helper_ref in _CYCLABLE_RELEASE_HELPERS or (
            isinstance(value.callee, str) and value.callee in _CYCLABLE_RELEASE_HELPERS
        )
    if isinstance(value, (list, tuple)):
        return any(contains_cyclable_release(item) for item in value)
    if not dataclasses.is_dataclass(value):
        return False
    return any(
        contains_cyclable_release(item)
        for field in dataclasses.fields(value)
        if not isinstance((item := getattr(value, field.name)), str)
    )


def _rewrite_block(
    function: IRFunctionDef,
    block: IRBlock,
    counter: list[int],
    local_names: set[str],
) -> None:
    rewritten = []
    for statement in block.stmts:
        _rewrite_nested(function, statement, counter, local_names)
        if isinstance(statement, IRReturn):
            materialized = _is_materialized_flush_return(rewritten, statement)
            if statement.value is not None and not materialized:
                result = _next_return_name(counter, local_names)
                rewritten.append(
                    IRVarDecl(
                        c_type=function.return_type,
                        name=result,
                        init=statement.value,
                        is_cycle_return_temp=True,
                    )
                )
                statement.value = IRVar(name=result)
            if not _ends_with_flush(rewritten):
                rewritten.append(_flush_stmt())
        rewritten.append(statement)
    block.stmts = rewritten


def _rewrite_nested(
    function: IRFunctionDef,
    statement,
    counter: list[int],
    local_names: set[str],
) -> None:
    if isinstance(statement, IRBlock):
        _rewrite_block(function, statement, counter, local_names)
    elif isinstance(statement, IRIf):
        _rewrite_block(function, statement.then_block, counter, local_names)
        if statement.else_block is not None:
            _rewrite_block(function, statement.else_block, counter, local_names)
    elif isinstance(statement, (IRWhile, IRDoWhile, IRFor)):
        _rewrite_block(function, statement.body, counter, local_names)
    elif isinstance(statement, IRSwitch):
        for case in statement.cases:
            _rewrite_case(function, case, counter, local_names)


def _rewrite_case(
    function: IRFunctionDef,
    case: IRCase,
    counter: list[int],
    local_names: set[str],
) -> None:
    block = IRBlock(stmts=case.body)
    _rewrite_block(function, block, counter, local_names)
    case.body = block.stmts


def _local_names(function: IRFunctionDef) -> set[str]:
    names = {parameter.name for parameter in function.params}

    def collect(value) -> None:
        if isinstance(value, IRVarDecl):
            names.add(value.name)
        if isinstance(value, (list, tuple)):
            for item in value:
                collect(item)
        elif dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                item = getattr(value, field.name)
                if not isinstance(item, str):
                    collect(item)

    collect(function.body)
    return names


def _next_return_name(counter: list[int], local_names: set[str]) -> str:
    while True:
        counter[0] += 1
        name = f"__btrc_cycle_return_{counter[0]}"
        if name not in local_names:
            local_names.add(name)
            return name


def _is_materialized_flush_return(statements, statement: IRReturn) -> bool:
    if len(statements) < 2 or not _ends_with_flush(statements):
        return False
    declaration = statements[-2]
    return bool(
        isinstance(declaration, IRVarDecl)
        and declaration.is_cycle_return_temp
        and isinstance(statement.value, IRVar)
        and declaration.name == statement.value.name
    )


def _flush_stmt() -> IRExprStmt:
    return IRExprStmt(
        expr=IRCall(
            callee="__btrc_flush_cycles",
            helper_ref="__btrc_flush_cycles",
            args=[],
        )
    )


def _ends_with_flush(statements) -> bool:
    if not statements:
        return False
    statement = statements[-1]
    return bool(
        isinstance(statement, IRExprStmt)
        and isinstance(statement.expr, IRCall)
        and (statement.expr.helper_ref == "__btrc_flush_cycles" or statement.expr.callee == "__btrc_flush_cycles")
    )


__all__ = [
    "PUBLIC_COLLECTION_BASES",
    "contains_cyclable_release",
    "install_function_cycle_boundary",
    "install_program_cycle_boundary",
]
