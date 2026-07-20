"""Ownership-effect extraction across callable body shapes."""

from src.compiler.python.ast_nodes import (
    Block,
    Identifier,
    LambdaBlock,
    LambdaExpr,
    LambdaExprBody,
    Param,
    ReleaseStmt,
    TypeExpr,
)
from src.compiler.python.ownership_effects import owned_transfer_param_indices


def _lambda(body):
    return LambdaExpr(
        params=[Param(type=TypeExpr(base="Item"), name="value")],
        body=body,
    )


def test_expression_lambda_has_no_statement_transfer_effect() -> None:
    declaration = _lambda(LambdaExprBody(expression=Identifier(name="value")))

    assert owned_transfer_param_indices(declaration) == frozenset()


def test_block_lambda_unwraps_its_structured_block() -> None:
    declaration = _lambda(
        LambdaBlock(
            body=Block(
                statements=[ReleaseStmt(expr=Identifier(name="value"))],
            ),
        ),
    )

    assert owned_transfer_param_indices(declaration) == frozenset({0})
