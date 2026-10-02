"""End-to-end contracts for shared type-directed operator lowering."""

from __future__ import annotations

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.analyzer.types import OperatorSemantics, OperatorTypeError, TypeIdentity
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.lowering.types import CodegenError
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import TypeExpr
from src.tests.python.c11_runtime_sources import TYPED_OPERATOR_RUNTIME
from src.tests.python.reference_pipeline import emit_c

IDENTITY = TypeIdentity()
OPERATORS = OperatorSemantics(IDENTITY)


def _analyze(source: str):
    program = Parser(Lexer(source, "<typed-operators>").tokenize()).parse()
    return program, SemanticAnalyzer().analyze(program)


def test_scalar_string_shape_excludes_arrays_and_extra_pointers():
    assert IDENTITY.is_scalar_string(TypeExpr(base="string"))
    assert IDENTITY.is_scalar_string(TypeExpr(base="string", pointer_depth=1, is_nullable=True))
    assert not IDENTITY.is_scalar_string(TypeExpr(base="string", pointer_depth=1))
    assert not IDENTITY.is_scalar_string(TypeExpr(base="string", is_array=True))


def test_opaque_t_suffix_is_not_assumed_numeric():
    with pytest.raises(OperatorTypeError, match="aggregate operand"):
        OPERATORS.hash_domain(TypeExpr(base="payload_t"))

    _program, analyzed = _analyze("""
        void run() {
            payload_t payload;
            payload = 1;
            var sum = payload + 1;
            bool same = payload == 1;
        }
    """)
    assert any("Cannot assign 'int' to 'payload_t'" in item for item in analyzed.errors)
    assert any("Operator '+'" in item for item in analyzed.errors)
    assert any("aggregate operands" in item for item in analyzed.errors)


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ('void run() { bool value = "1" == 1; }', "string and non-string"),
        ('void run() { bool value = __btrc_eq(1, "1"); }', "string and non-string"),
        (
            "int identity(int value) { return value; } "
            "void run() { __fn_ptr<int, int> callback = identity; "
            "uint value = __btrc_hash(callback); }",
            "does not support function-pointer",
        ),
        (
            "void run(void* object, __fn_ptr<int, int> callback) { bool value = object == callback; }",
            "incompatible reference operands",
        ),
        ("void run(string text, string* pointer) { bool v = text == pointer; }", "string and non-string"),
        ("class Item {} void run(Item a, Item b) { bool v = a < b; }", "only == and !="),
        (
            "class Base<T> {} class Child<T> extends Base {} "
            "void run(Base<int> base, Child<string> child) { "
            "bool value = base == child; }",
            "mismatched positional specialization",
        ),
        ("struct Pair { int value; }; void run(Pair a, Pair b) { bool v = a == b; }", "aggregate operands"),
        ("void run() { int value = 1 ?? 2; }", "left operand of '??'"),
    ),
)
def test_invalid_operator_domains_are_analyzer_diagnostics(source, message):
    _program, analyzed = _analyze(source)
    assert any(message in error for error in analyzed.errors), analyzed.errors


def test_invalid_concrete_generic_operator_fails_closed_in_codegen():
    program, analyzed = _analyze("""
        class Item {}
        class Ordered<T> {
            public Ordered() {}
            public bool less(T left, T right) { return left < right; }
        }
        void run(Item left, Item right) {
            Ordered<Item> values = new Ordered<Item>();
            bool result = values.less(left, right);
        }
    """)
    assert not analyzed.errors
    assert program is analyzed.program
    with pytest.raises(CodegenError, match="only == and !="):
        IRLowerer(analyzed).lower()


def test_positional_generic_inheritance_fails_closed_before_comparison():
    _program, analyzed = _analyze("""
        class Base<T> {}
        class Child<T> extends Base {}
        void run(Base<int> base, Child<int> child) {
            bool same = base == child;
            bool different = child != base;
        }
    """)
    assert any("Generic class inheritance is not supported" in error for error in analyzed.errors), analyzed.errors


def test_declared_and_known_system_integer_typedefs_remain_numeric():
    _program, analyzed = _analyze("""
        typedef long long custom_count_t;
        void run(custom_count_t custom, ssize_t count, pid_t process) {
            bool custom_ok = custom > 0LL;
            bool count_ok = count >= (ssize_t)0;
            bool process_ok = process != (pid_t)0;
        }
    """)
    assert not analyzed.errors


def test_numeric_result_inference_is_operand_order_independent():
    program, analyzed = _analyze("""
        void run() {
            var first = 1LL + 2u;
            var second = 2u + 1LL;
            var third = 1UL + 2LL;
            var fourth = 2LL + 1UL;
            var fifth = true ? 1LL : 2u;
            var sixth = false ? 2u : 1LL;
        }
    """)
    assert not analyzed.errors
    inferred = [item.type.base for item in program.declarations[0].body.statements]
    assert inferred == [
        "unsigned long long",
        "unsigned long long",
        "unsigned long long",
        "unsigned long long",
        "unsigned long long",
        "unsigned long long",
    ]


def test_typed_operator_runtime_contains_shared_lowering():
    generated = emit_c(TYPED_OPERATOR_RUNTIME)

    assert generated.count("strcmp(") >= 20
    assert "__btrc_hash_str" in generated
    assert "#define __btrc_div" in generated
    assert "#define __btrc_mod" in generated
    assert "__btrc_hash_real" in generated
    assert "callback == callback" not in generated
    assert "__btrc_fn_left" in generated
    assert "__btrc_fn_right" in generated
