"""IR statement-expression sequencing must preserve source evaluation sites."""

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFunctionDef,
    IRLiteral,
    IRModule,
    IRNode,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _module(source: str) -> IRModule:
    program = Parser(Lexer(source, "<test>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors
    return IRLowerer(analyzed).lower()


@pytest.mark.parametrize(
    "source",
    [
        'int main() { string s = f"{1}"; return s.len(); }',
        "int main() { Vector<int> xs = [1, 2]; return xs.len; }",
        'int main() { Map<string, int> m = {"x": 1}; return m.len; }',
        'int main() { string x = null; string y = x ?? "y"; return y.len(); }',
        "int main() { int n = 1; var t = spawn(() => n); return t.join(); }",
        """
    class Item { public Item() {} }
    class Holder { public Item item; public Holder() { self.item = null; } }
    int main() { Holder h = new Holder(); h.item = new Item(); return 0; }
    """,
    ],
)
def test_generated_setups_are_declarations_only(source):
    stmt_exprs = [node for node in IRNode.walk_value(_module(source)) if isinstance(node, IRStmtExpr)]
    assert stmt_exprs
    for expression in stmt_exprs:
        assert expression.stmts
        assert all(
            isinstance(declaration, IRVarDecl)
            and (
                declaration.init is None
                or (isinstance(declaration.init, IRLiteral) and declaration.init.text in {"0", "NULL", "false"})
            )
            for declaration in expression.stmts
        )


def test_emitter_rejects_side_effectful_hoisting():
    unsafe = IRStmtExpr(
        stmts=[IRExprStmt(expr=IRCall(callee="side_effect", args=[]))],
        result=IRLiteral(text="1"),
    )
    module = IRModule(
        function_defs=[
            IRFunctionDef(
                name="main",
                return_type=CType(text="int"),
                body=IRBlock(stmts=[IRVarDecl(c_type=CType(text="int"), name="value", init=unsafe)]),
            )
        ]
    )
    with pytest.raises(ValueError, match="uninitialized variable declarations"):
        CEmitter().emit(module)


def test_expression_statement_explicitly_discards_its_value():
    module = IRModule(
        function_defs=[
            IRFunctionDef(
                name="probe",
                return_type=CType(text="void"),
                body=IRBlock(stmts=[IRExprStmt(expr=IRVar(name="value"))]),
            )
        ]
    )

    emitted = CEmitter().emit(module)

    assert "(void)(value);" in emitted
