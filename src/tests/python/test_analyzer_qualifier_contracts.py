"""Const qualification and mutable-storage semantic boundaries."""

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<qualifier-contracts>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program).errors


def test_one_level_pointer_conversion_can_add_but_not_remove_const():
    valid = _errors("""
        void run(int* writable) {
            const int* readable = writable;
        }
    """)
    invalid = _errors("""
        void run(const int* readable) {
            int* writable = readable;
        }
    """)

    assert valid == []
    assert any("cannot assign" in error.lower() and "writable" in error.lower() for error in invalid)


def test_deep_pointer_conversion_cannot_add_base_const_implicitly():
    errors = _errors("""
        void run(int** writable) {
            const int** unsound = writable;
        }
    """)

    assert any("cannot assign" in error.lower() and "unsound" in error.lower() for error in errors)


def test_const_pointee_cannot_be_updated_through_deref_or_index():
    errors = _errors("""
        void run(const int* values) {
            *values = 1;
            values[0]++;
        }
    """)

    assert sum("const-qualified storage" in error.lower() for error in errors) == 2


def test_const_aggregate_propagates_to_value_members_not_pointer_pointees():
    errors = _errors("""
        struct Inner { int value; };
        struct Outer { struct Inner inner; int* values; };
        void run(const struct Outer* outer) {
            outer->inner.value = 1;
            outer->values = null;
            outer->values[0] = 2;
        }
    """)

    const_errors = [error for error in errors if "const-qualified" in error.lower()]
    assert len(const_errors) == 2
