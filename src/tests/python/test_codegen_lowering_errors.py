"""Unsupported lowering paths fail explicitly instead of emitting invalid C."""

import pytest

from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.ir.lowering.expressions import ExpressionLowerer
from src.compiler.python.ir.lowering.types import CodegenError
from src.compiler.python.ir.nodes import IRExpr, IRStmt


class UnknownNode:
    pass


class UnknownIRExpr(IRExpr):
    pass


class UnknownIRStmt(IRStmt):
    pass


def test_unknown_statement_raises_codegen_error():
    with pytest.raises(CodegenError, match="unsupported statement node: UnknownNode"):
        raise ExpressionLowerer.unsupported_node("statement", UnknownNode())


def test_unknown_expression_raises_codegen_error():
    with pytest.raises(CodegenError, match="unsupported expression node: UnknownNode"):
        raise ExpressionLowerer.unsupported_node("expression", UnknownNode())


def test_unknown_ir_expression_raises_emitter_error():
    with pytest.raises(TypeError, match="unsupported IR expression: UnknownIRExpr"):
        CEmitter()._expr(UnknownIRExpr())


def test_unknown_ir_statement_raises_emitter_error():
    with pytest.raises(TypeError, match="unsupported IR statement: UnknownIRStmt"):
        CEmitter()._emit_stmt(UnknownIRStmt())
