"""White-box tests for the try/catch detection walk in generator.py. The
module's _emit_includes short-circuits after the first try/catch-using
declaration, so a single program can't drive every branch of the recursive
detector — call the helpers directly on parsed function bodies instead."""

from src.compiler.python.ast_nodes import FunctionDecl
from src.compiler.python.ir.gen.generator import (
    _block_uses_trycatch,
    _stmt_uses_trycatch,
)
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _body(src):
    prog = Parser(Lexer(src, "<t>").tokenize()).parse()
    fn = next(d for d in prog.declarations if isinstance(d, FunctionDecl))
    return fn.body


def _first_stmt(src):
    return _body(src).statements[0]


def test_detects_trycatch_in_then_block():
    assert _block_uses_trycatch(_body('void f() { if (1 == 1) { try { throw "x"; } catch (string e) {} } }'))


def test_detects_trycatch_in_else_block():
    assert _block_uses_trycatch(_body('void f() { if (1 == 1) {} else { try { throw "x"; } catch (string e) {} } }'))


def test_detects_trycatch_in_else_if():
    assert _block_uses_trycatch(_body('void f() { if (1 == 1) {} else if (2 == 2) { try { throw "x"; } catch (string e) {} } }'))


def test_detects_trycatch_in_while_for_dowhile():
    assert _block_uses_trycatch(_body('void f() { while (1 == 0) { try { throw "x"; } catch (string e) {} } }'))
    assert _block_uses_trycatch(_body('void f() { for (int i = 0; i < 0; i = i + 1) { try { throw "x"; } catch (string e) {} } }'))
    assert _block_uses_trycatch(_body('void f() { do { try { throw "x"; } catch (string e) {} } while (1 == 0); }'))


def test_detects_trycatch_in_switch_case_directly():
    assert _block_uses_trycatch(_body('void f() { switch (1) { case 1: throw "y"; default: {} } }'))


def test_detects_trycatch_in_switch_case_nested():
    assert _block_uses_trycatch(_body('void f() { switch (1) { case 1: while (1 == 0) { try { throw "y"; } catch (string e) {} } default: {} } }'))


def test_detects_trycatch_nested_in_try_catch_finally():
    src = ('void f() { try { try { throw "a"; } catch (string e) {} }'
           ' catch (string e) {} finally { try { throw "b"; } catch (string e) {} } }')
    assert _block_uses_trycatch(_body(src))


def test_stmt_detector_directly_on_each_structure():
    assert _stmt_uses_trycatch(_first_stmt('void f() { if (1 == 1) { throw "x"; } }'))
    assert _stmt_uses_trycatch(_first_stmt('void f() { if (1 == 1) {} else if (2 == 2) { try { throw "x"; } catch (string e) {} } }'))
    assert _stmt_uses_trycatch(_first_stmt('void f() { while (1 == 0) { try { throw "x"; } catch (string e) {} } }'))
    assert _stmt_uses_trycatch(_first_stmt('void f() { switch (1) { case 1: while (1 == 0) { try { throw "y"; } catch (string e) {} } default: {} } }'))


def test_no_trycatch_returns_false():
    assert not _block_uses_trycatch(_body('void f() { int x = 0; if (x > 0) { x = 1; } while (x < 5) { x = x + 1; } }'))
    assert not _stmt_uses_trycatch(_first_stmt('void f() { int x = 0; }'))
    assert not _block_uses_trycatch(None)
