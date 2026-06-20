"""Unsupported lowering paths fail explicitly instead of emitting invalid C."""

import pytest

from src.compiler.python.ir.gen.errors import CodegenError
from src.compiler.python.ir.gen.expressions import lower_expr
from src.compiler.python.ir.gen.statements import lower_stmt


class UnknownNode:
    pass


def test_unknown_statement_raises_codegen_error():
    with pytest.raises(CodegenError, match="unsupported statement node: UnknownNode"):
        lower_stmt(None, UnknownNode())


def test_unknown_expression_raises_codegen_error():
    with pytest.raises(CodegenError, match="unsupported expression node: UnknownNode"):
        lower_expr(None, UnknownNode())
