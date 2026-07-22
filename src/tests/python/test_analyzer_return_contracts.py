"""Return statements must match signatures and terminate every path."""

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<return-contracts>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program).errors


def _has(errors: list[str], text: str) -> bool:
    return any(text.lower() in error.lower() for error in errors)


def test_void_function_cannot_return_a_value():
    assert _has(_errors("void run() { return 1; }"), "cannot return a value")


def test_non_void_function_cannot_use_bare_return():
    assert _has(_errors("int run() { return; }"), "must return 'int'")


def test_conditional_loop_return_does_not_cover_fallthrough():
    errors = _errors("int run() { for (; false;) { return 1; } }")
    assert _has(errors, "no return statement")


def test_try_and_catch_must_both_terminate():
    errors = _errors("int run() { try { return 1; } catch (error) { print(error); } }")
    assert _has(errors, "no return statement")


def test_finally_return_terminates_every_path():
    errors = _errors("int run() { try { print(1); } finally { return 2; } }")
    assert not _has(errors, "no return statement")


def test_loop_break_prevents_infinite_loop_from_proving_return():
    errors = _errors("""
        int run(bool stop) {
            while (true) {
                if (stop) { break; }
                return 1;
            }
        }
    """)
    assert _has(errors, "no return statement")
