"""Semantic checks for expressions that previously reached invalid C."""

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<expression-contracts>").tokenize()).parse()
    return Analyzer().analyze(program).errors


def _has(errors: list[str], text: str) -> bool:
    return any(text.lower() in error.lower() for error in errors)


def test_assignment_requires_an_lvalue():
    assert _has(_errors("void run() { 1 = 2; }"), "not assignable")


def test_assignment_requires_compatible_types():
    errors = _errors('void run() { int value = 0; value = "bad"; }')
    assert _has(errors, "cannot assign 'string' to 'int'")


def test_binary_operator_requires_valid_operands():
    errors = _errors('void run() { var value = "bad" - 1; }')
    assert _has(errors, "operator '-'")


def test_overloaded_operators_use_their_declared_return_types():
    errors = _errors("""
        class Number {
            public int value;
            public Number(int value) { self.value = value; }
            public int __sub__(Number other) {
                return self.value - other.value;
            }
            public int __neg__() { return -self.value; }
        }
        void run() {
            Number left = Number(7);
            Number right = Number(2);
            int difference = left - right;
            int negated = -left;
        }
    """)
    assert errors == []


def test_class_null_ternaries_infer_the_class_type_in_either_order():
    program = Parser(
        Lexer(
            """
        class Node {}
        void run(bool choose, Node node) {
            var first = choose ? node : null;
            var second = choose ? null : node;
        }
    """,
            "<expression-contracts>",
        ).tokenize()
    ).parse()
    result = Analyzer().analyze(program)
    assert result.errors == []
    first, second = program.declarations[1].body.statements
    assert first.type.base == second.type.base == "Node"
    assert first.type.is_nullable and second.type.is_nullable


def test_index_requires_indexable_object_and_integral_index():
    errors = _errors('void run() { int* values; int first = 1[0]; int second = values["bad"]; }')
    assert _has(errors, "not indexable")
    assert _has(errors, "integral type")


def test_class_index_diagnostics_name_the_required_protocol_signatures():
    read_errors = _errors("class Box {} void run(Box box) { box[0]; }")
    write_errors = _errors(
        "class Box { public int set(int index, int value) { return value; } } void run(Box box) { box[0] = 1; }"
    )
    assert _has(read_errors, "indexing requires an instance get(index) method")
    assert _has(write_errors, "has no void instance set(index, value) method")


def test_dereference_requires_pointer_operand():
    errors = _errors("void run() { int value = *1; }")
    assert _has(errors, "unary operator '*'")


def test_spawn_requires_a_callable():
    errors = _errors("void run() { var thread = spawn(1); }")
    assert _has(errors, "spawn expects")


def test_ownership_operations_reject_primitives():
    errors = _errors("void run() { int value = 1; keep value; release value; delete value; }")
    assert sum("ownership operation is not valid" in error.lower() for error in errors) == 3
