"""Unsupported lowering paths fail explicitly instead of emitting invalid C."""

import pytest

from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.errors import CodegenError
from src.compiler.python.ir.gen.expressions import lower_expr
from src.compiler.python.ir.gen.statements import lower_stmt
from src.compiler.python.ir.nodes import IRExpr, IRStmt


class UnknownNode:
    pass


class UnknownIRExpr(IRExpr):
    pass


class UnknownIRStmt(IRStmt):
    pass


def test_unknown_statement_raises_codegen_error():
    with pytest.raises(CodegenError, match="unsupported statement node: UnknownNode"):
        lower_stmt(None, UnknownNode())


def test_unknown_expression_raises_codegen_error():
    with pytest.raises(CodegenError, match="unsupported expression node: UnknownNode"):
        lower_expr(None, UnknownNode())


def test_unknown_ir_expression_raises_emitter_error():
    with pytest.raises(TypeError, match="unsupported IR expression: UnknownIRExpr"):
        CEmitter()._expr(UnknownIRExpr())


def test_unknown_ir_statement_raises_emitter_error():
    with pytest.raises(TypeError, match="unsupported IR statement: UnknownIRStmt"):
        CEmitter()._emit_stmt(UnknownIRStmt())
