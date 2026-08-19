"""End-to-end contracts for shared type-directed operator lowering."""

from __future__ import annotations

import shutil

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.syntax.ast.generated import TypeExpr
from src.compiler.python.ir.lowering.types import CodegenError
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.analyzer.types import OperatorSemantics, OperatorTypeError
from src.compiler.python.parser.parser import Parser
from src.compiler.python.analyzer.types import TypeIdentity
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
IDENTITY = TypeIdentity()
OPERATORS = OperatorSemantics(IDENTITY)

RUNTIME_SOURCE = r"""
#include <assert.h>

int left_calls = 0;
int right_calls = 0;

string? left_probe(string? value) {
    left_calls++;
    return value;
}

string? right_probe(string? value) {
    right_calls++;
    return value;
}

int identity(int value) { return value; }
int negate(int value) { return -value; }
int callback_order = 0;

__fn_ptr<int, int> callback_probe(
    __fn_ptr<int, int> callback, int marker
) {
    callback_order = callback_order * 10 + marker;
    return callback;
}

class StringOps<T> {
    public T value;
    public StringOps(T value) { self.value = value; }
    public bool eq(T other) { return self.value == other; }
    public bool ne(T other) { return self.value != other; }
    public bool lt(T other) { return self.value < other; }
    public bool gt(T other) { return self.value > other; }
    public bool le(T other) { return self.value <= other; }
    public bool ge(T other) { return self.value >= other; }
    public T join(T other) { return self.value + other; }
    public T fallback(T other) { return self.value ?? other; }
}

class MagicOps<T> {
    public MagicOps() {}
    public bool eq(T left, T right) { return __btrc_eq(left, right); }
    public bool lt(T left, T right) { return __btrc_lt(left, right); }
    public bool gt(T left, T right) { return __btrc_gt(left, right); }
    public uint hash(T value) { return __btrc_hash(value); }
}

class NumberOps<T> {
    public NumberOps() {}
    public T divide(T left, T right) { return left / right; }
    public T modulo(T left, T right) { return left % right; }
}

class Base {
    public Base() {}
}

class Child extends Base {
    public Child() {}
}

int main() {
    string dynamic = "sa" + "me";
    string? nil = null;

    assert(dynamic == "same");
    assert(dynamic != "different");
    assert("alpha" < "beta");
    assert("beta" > "alpha");
    assert("alpha" <= "alpha");
    assert("beta" >= "beta");

    assert(nil == null);
    assert(nil < "alpha");
    assert("alpha" > nil);
    assert(nil <= null);
    assert("alpha" >= nil);
    assert(nil != "alpha");

    assert(left_probe(null) < right_probe("x"));
    assert(left_calls == 1 && right_calls == 1);
    left_calls = 0;
    right_calls = 0;
    assert(left_probe(dynamic) == right_probe("same"));
    assert(left_calls == 1 && right_calls == 1);

    StringOps<string?> empty = new StringOps<string?>(null);
    StringOps<string?> text = new StringOps<string?>(dynamic);
    assert(empty.eq(null));
    assert(empty.ne("same"));
    assert(empty.lt("same"));
    assert(text.gt(null));
    assert(empty.le(null));
    assert(text.ge("same"));
    assert(text.eq("same"));
    assert(text.fallback("fallback") == "same");
    assert(empty.fallback("fallback") == "fallback");
    assert(text.join("!") == "same!");

    MagicOps<string?> magic = new MagicOps<string?>();
    assert(magic.eq(dynamic, "same"));
    assert(magic.lt(null, "same"));
    assert(magic.gt("same", null));
    assert(magic.hash(null) == 0u);
    assert(magic.hash(dynamic) == magic.hash("same"));
    MagicOps<double> real_magic = new MagicOps<double>();
    assert(real_magic.hash(0.0) == real_magic.hash(-0.0));
    assert(real_magic.hash(1.5) == real_magic.hash(1.5));
    assert(real_magic.hash(NAN) == real_magic.hash(NAN));
    assert(real_magic.hash(INFINITY) == real_magic.hash(INFINITY));

    NumberOps<int> ints = new NumberOps<int>();
    assert(ints.divide(21, 2) == 10);
    assert(ints.modulo(21, 2) == 1);
    NumberOps<float> floats = new NumberOps<float>();
    assert(floats.modulo(7.9, 2.0) == 1.0);
    NumberOps<long long> wide = new NumberOps<long long>();
    assert(wide.divide(8589934592LL, 2LL) == 4294967296LL);
    assert(wide.modulo(8589934593LL, 2LL) == 1LL);
    long negative = -2L;
    uint one = 1u;
    var mixed_first = negative + one;
    var mixed_second = one + negative;
    assert(mixed_first == (unsigned long)-1L);
    assert(mixed_second == (unsigned long)-1L);
    printf("%lu %lu", mixed_first, mixed_second);
    printf("%llu %llu", true ? 1LL : 2u, false ? 2u : 1LL);
    printf("%f", 7.9 % 2.0);

    Base base = new Base();
    Child child = new Child();
    Base alias = child;
    assert(alias == child);
    assert(base != child);
    __fn_ptr<int, int> callback = identity;
    assert(callback == callback);
    assert(callback != null);
    assert(callback_probe(identity, 1) == callback_probe(identity, 2));
    assert(callback_order == 12);
    callback_order = 0;
    assert(callback_probe(identity, 1) != callback_probe(negate, 2));
    assert(callback_order == 12);
    MagicOps<__fn_ptr<int, int>> callback_magic =
        new MagicOps<__fn_ptr<int, int>>();
    assert(callback_magic.eq(callback, callback));
    return 0;
}
"""


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
    generated = emit_c(RUNTIME_SOURCE)

    assert generated.count("strcmp(") >= 20
    assert "__btrc_hash_str" in generated
    assert "#define __btrc_div" in generated
    assert "#define __btrc_mod" in generated
    assert "__btrc_hash_real" in generated
    assert "callback == callback" not in generated
    assert "__btrc_fn_left" in generated
    assert "__btrc_fn_right" in generated
