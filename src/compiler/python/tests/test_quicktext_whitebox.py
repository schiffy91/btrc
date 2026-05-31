"""White-box tests for _quick_text — the inline C renderer used for C-for loop
headers. Each IR expression form is rendered directly; specific node shapes are
hard to force into a for-header from source, so exercise the renderer directly."""

from src.compiler.python.ir.gen.statements import _quick_text
from src.compiler.python.ir.nodes import (
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRCast,
    IRDeref,
    IRFieldAccess,
    IRIndex,
    IRLiteral,
    IRRawC,
    IRRawExpr,
    IRReturn,
    IRSizeof,
    IRTernary,
    IRUnaryOp,
    IRVar,
)


def test_quick_text_literals_and_vars():
    assert _quick_text(IRLiteral(text="42")) == "42"
    assert _quick_text(IRVar(name="x")) == "x"
    assert _quick_text(IRRawExpr(text="raw")) == "raw"
    assert _quick_text(IRRawC(text="rawc")) == "rawc"
    assert _quick_text(None) == ""


def test_quick_text_binop_and_unary():
    assert _quick_text(IRBinOp(left=IRVar(name="a"), op="+", right=IRLiteral(text="1"))) == "(a + 1)"
    assert _quick_text(IRUnaryOp(op="++", operand=IRVar(name="i"), prefix=False)) == "(i++)"
    assert _quick_text(IRUnaryOp(op="!", operand=IRVar(name="b"), prefix=True)) == "(!b)"


def test_quick_text_call_field_index():
    assert _quick_text(IRCall(callee="f", args=[IRVar(name="x"), IRLiteral(text="2")])) == "f(x, 2)"
    assert _quick_text(IRFieldAccess(obj=IRVar(name="o"), field="m", arrow=True)) == "o->m"
    assert _quick_text(IRFieldAccess(obj=IRVar(name="o"), field="m", arrow=False)) == "o.m"
    assert _quick_text(IRIndex(obj=IRVar(name="a"), index=IRLiteral(text="0"))) == "a[0]"


def test_quick_text_ternary_addr_deref_sizeof():
    t = _quick_text(IRTernary(condition=IRVar(name="c"),
                              true_expr=IRLiteral(text="1"), false_expr=IRLiteral(text="2")))
    assert t == "(c ? 1 : 2)"
    assert _quick_text(IRAddressOf(expr=IRVar(name="x"))) == "(&x)"
    assert _quick_text(IRDeref(expr=IRVar(name="p"))) == "(*p)"
    assert _quick_text(IRSizeof(operand="int")) == "sizeof(int)"


def test_quick_text_unknown_falls_back():
    # An IR node _quick_text doesn't render inline → a labelled fallback comment.
    out = _quick_text(IRReturn(value=IRLiteral(text="0")))
    assert "unknown" in out or "/*" in out
