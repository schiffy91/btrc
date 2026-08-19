"""Focused contracts for TranslationUnitLowerer's exception feature scan."""

from src.compiler.python.syntax.ast.generated import FunctionDecl
from src.compiler.python.ir.lowering.translation_unit import TranslationUnitLowerer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _body(src):
    prog = Parser(Lexer(src, "<t>").tokenize()).parse()
    fn = next(d for d in prog.declarations if isinstance(d, FunctionDecl))
    return fn.body


def _first_stmt(src):
    return _body(src).statements[0]


def test_detects_trycatch_in_then_block():
    assert TranslationUnitLowerer.uses_trycatch(_body('void f() { if (1 == 1) { try { throw "x"; } catch (string e) {} } }'))


def test_detects_trycatch_in_else_block():
    assert TranslationUnitLowerer.uses_trycatch(_body('void f() { if (1 == 1) {} else { try { throw "x"; } catch (string e) {} } }'))


def test_detects_trycatch_in_else_if():
    assert TranslationUnitLowerer.uses_trycatch(
        _body('void f() { if (1 == 1) {} else if (2 == 2) { try { throw "x"; } catch (string e) {} } }')
    )


def test_detects_trycatch_in_while_for_dowhile():
    assert TranslationUnitLowerer.uses_trycatch(_body('void f() { while (1 == 0) { try { throw "x"; } catch (string e) {} } }'))
    assert TranslationUnitLowerer.uses_trycatch(
        _body('void f() { for (int i = 0; i < 0; i = i + 1) { try { throw "x"; } catch (string e) {} } }')
    )
    assert TranslationUnitLowerer.uses_trycatch(_body('void f() { do { try { throw "x"; } catch (string e) {} } while (1 == 0); }'))


def test_detects_trycatch_in_switch_case_directly():
    assert TranslationUnitLowerer.uses_trycatch(_body('void f() { switch (1) { case 1: throw "y"; default: {} } }'))


def test_detects_trycatch_in_switch_case_nested():
    assert TranslationUnitLowerer.uses_trycatch(
        _body(
            'void f() { switch (1) { case 1: while (1 == 0) { try { throw "y"; } catch (string e) {} } default: {} } }'
        )
    )


def test_detects_trycatch_nested_in_try_catch_finally():
    src = (
        'void f() { try { try { throw "a"; } catch (string e) {} }'
        ' catch (string e) {} finally { try { throw "b"; } catch (string e) {} } }'
    )
    assert TranslationUnitLowerer.uses_trycatch(_body(src))


def test_stmt_detector_directly_on_each_structure():
    assert TranslationUnitLowerer.uses_trycatch(_first_stmt('void f() { if (1 == 1) { throw "x"; } }'))
    assert TranslationUnitLowerer.uses_trycatch(
        _first_stmt('void f() { if (1 == 1) {} else if (2 == 2) { try { throw "x"; } catch (string e) {} } }')
    )
    assert TranslationUnitLowerer.uses_trycatch(_first_stmt('void f() { while (1 == 0) { try { throw "x"; } catch (string e) {} } }'))
    assert TranslationUnitLowerer.uses_trycatch(
        _first_stmt(
            'void f() { switch (1) { case 1: while (1 == 0) { try { throw "y"; } catch (string e) {} } default: {} } }'
        )
    )


def test_no_trycatch_returns_false():
    assert not TranslationUnitLowerer.uses_trycatch(_body("void f() { int x = 0; if (x > 0) { x = 1; } while (x < 5) { x = x + 1; } }"))
    assert not TranslationUnitLowerer.uses_trycatch(_first_stmt("void f() { int x = 0; }"))
    assert not TranslationUnitLowerer.uses_trycatch(None)
