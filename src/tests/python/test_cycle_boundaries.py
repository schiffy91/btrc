"""Focused contracts for deterministic cycle-collector boundaries."""

from copy import deepcopy
from pathlib import Path

from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFunctionDef,
    IRHelperDecl,
    IRLiteral,
    IRModule,
    IRReturn,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.ir.optimizer import IROptimizer
from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

SELF_HOSTED_BOUNDARIES = Path("src/compiler/btrc/ir/lowering/ownership/cycle_boundaries.btrc")
EDGE_RELEASE_HELPERS = (
    "__btrc_arc_release_edge",
    "__btrc_arc_replace_edge",
)


def _call_statement(name: str) -> IRExprStmt:
    return IRExprStmt(
        expr=IRCall(
            callee=name,
            helper_ref=name,
            args=[],
        )
    )


def _called_name(statement) -> str | None:
    if isinstance(statement, IRExprStmt) and isinstance(statement.expr, IRCall):
        return statement.expr.callee
    return None


def test_return_value_is_evaluated_before_its_forced_cycle_flush() -> None:
    collision = "__btrc_cycle_return_1"
    function = IRFunctionDef(
        name="finish_boundary",
        return_type=CType(text="int"),
        body=IRBlock(
            stmts=[
                IRVarDecl(
                    c_type=CType(text="int"),
                    name=collision,
                    init=IRLiteral(text="17"),
                ),
                _call_statement("__btrc_arc_release"),
                _call_statement("__btrc_flush_cycles"),
                IRReturn(value=IRCall(callee="finish", args=[])),
            ]
        ),
    )

    assert IROptimizer.install_function_cycle_boundary(function)

    statements = function.body.stmts
    result_index = next(
        index
        for index, statement in enumerate(statements)
        if isinstance(statement, IRVarDecl) and isinstance(statement.init, IRCall) and statement.init.callee == "finish"
    )
    result = statements[result_index]
    flush_indexes = [
        index for index, statement in enumerate(statements) if _called_name(statement) == "__btrc_flush_cycles"
    ]
    return_index = next(index for index, statement in enumerate(statements) if isinstance(statement, IRReturn))

    assert len(flush_indexes) == 2
    assert flush_indexes[0] < result_index < flush_indexes[1] < return_index
    assert result.name != collision
    assert statements[return_index].value == IRVar(name=result.name)

    first_rewrite = deepcopy(statements)
    assert IROptimizer.install_function_cycle_boundary(function)
    assert function.body.stmts == first_rewrite


def test_explicit_flush_before_local_return_is_not_mistaken_for_pass_output() -> None:
    local = "__btrc_cycle_return_1"
    function = IRFunctionDef(
        name="finish_boundary",
        return_type=CType(text="int"),
        body=IRBlock(
            stmts=[
                _call_statement("__btrc_arc_release"),
                IRVarDecl(
                    c_type=CType(text="int"),
                    name=local,
                    init=IRLiteral(text="17"),
                ),
                _call_statement("__btrc_flush_cycles"),
                IRReturn(value=IRVar(name=local)),
            ]
        ),
    )

    assert IROptimizer.install_function_cycle_boundary(function)

    statements = function.body.stmts
    return_index = next(index for index, statement in enumerate(statements) if isinstance(statement, IRReturn))
    generated = statements[return_index - 2]
    assert isinstance(generated, IRVarDecl)
    assert generated.is_cycle_return_temp
    assert generated.name != local
    assert generated.init == IRVar(name=local)
    assert _called_name(statements[return_index - 1]) == "__btrc_flush_cycles"

    first_rewrite = deepcopy(statements)
    assert IROptimizer.install_function_cycle_boundary(function)
    assert function.body.stmts == first_rewrite


def test_edge_only_releases_receive_forced_cycle_boundaries() -> None:
    for helper in EDGE_RELEASE_HELPERS:
        function = IRFunctionDef(
            name=f"boundary_for_{helper}",
            return_type=CType(text="void"),
            body=IRBlock(
                stmts=[
                    _call_statement(helper),
                    IRReturn(),
                ]
            ),
        )

        assert IROptimizer.install_function_cycle_boundary(function), helper
        assert [_called_name(statement) for statement in function.body.stmts] == [
            helper,
            "__btrc_flush_cycles",
            None,
        ]


def test_optimizer_materializes_flush_helper_for_edge_only_program() -> None:
    edge_helper = "__btrc_arc_replace_edge"
    module = IRModule(
        helper_decls=[
            IRHelperDecl.from_runtime(definition)
            for definition in RuntimeHelperCatalog().definitions_for({edge_helper})
        ],
        function_defs=[
            IRFunctionDef(
                name="main",
                return_type=CType(text="void"),
                body=IRBlock(stmts=[_call_statement(edge_helper)]),
            )
        ],
    )

    IROptimizer(module).optimize()

    assert _called_name(module.function_defs[0].body.stmts[-1]) == "__btrc_flush_cycles"
    positions = {declaration.name: index for index, declaration in enumerate(module.helper_decls)}
    assert "__btrc_flush_cycles" in positions
    for declaration in module.helper_decls:
        for dependency in declaration.depends_on:
            if dependency in positions:
                assert positions[dependency] < positions[declaration.name]


def test_self_hosted_cycle_boundary_mirrors_edge_and_return_contracts() -> None:
    source = SELF_HOSTED_BOUNDARIES.read_text()
    detector = source[source.index("public bool containsCyclableRelease") : source.index("private IRNode forcedFlush")]
    rewriter = source[source.index("private void rewriteCycleReturns") : source.index("public void forceBoundary")]

    for helper in EDGE_RELEASE_HELPERS:
        assert f'node.callee == "{helper}"' in detector
    assert "self.context.freshTemporary" in rewriter
    assert "self.isMaterializedReturn" in rewriter
    assert "is_cycle_return_temp = true" in rewriter
    assert rewriter.index("statement.value != null") < rewriter.index("self.forcedFlush()")
    assert rewriter.index("IRNode.variableDeclaration(") < rewriter.index("self.forcedFlush()")
