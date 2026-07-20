"""Fail-closed contracts for interfaces, abstract methods, and runtime generics."""

from __future__ import annotations

import pytest

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(source: str):
    program = Parser(Lexer(source, "<interface-runtime-boundary>").tokenize()).parse()
    return Analyzer().analyze(program)


def _errors(source: str) -> str:
    return "\n".join(_analyze(source).errors)


@pytest.mark.parametrize(
    "source",
    (
        "interface Value { int get(); } struct Box { Value value; };",
        "interface Value { int get(); } class Box { public Value value; }",
        "interface Value { int get(); } enum class Box { Some(Value value), Empty }",
        "interface Value { int get(); } Value value;",
        "interface Value { int get(); } Value make();",
        "interface Value { int get(); } void run() { Value value; }",
        "interface Value { int get(); } void run(Value* value) {}",
    ),
)
def test_interface_types_cannot_escape_into_runtime_storage(source: str):
    assert "Interface type 'Value' cannot be used as a runtime value" in _errors(source)


@pytest.mark.parametrize(
    ("source", "fragment"),
    (
        (
            "interface Parent { int read(int value); } interface Child extends Parent { string read(int value); }",
            "incompatible return type",
        ),
        (
            "interface Parent { int read(int value); } interface Child extends Parent { int read(string value); }",
            "incompatible type",
        ),
        (
            "interface Parent { keep Item read(); } interface Child extends Parent { Item read(); } class Item {}",
            "keep-return",
        ),
    ),
)
def test_interface_redeclarations_must_preserve_inherited_signatures(
    source: str,
    fragment: str,
):
    assert fragment in _errors(source)


@pytest.mark.parametrize(
    ("source", "fragment"),
    (
        (
            "class Parent { public int read() { return 1; } } "
            "class Child extends Parent { static int read() { return 2; } }",
            "static",
        ),
        (
            "class Item {} "
            "class Parent { public keep Item read() { return Item(); } } "
            "class Child extends Parent { public Item read() { return Item(); } }",
            "keep-return",
        ),
    ),
)
def test_class_overrides_preserve_calling_and_ownership_contracts(
    source: str,
    fragment: str,
):
    assert fragment in _errors(source)


def test_abstract_method_call_fails_before_emitting_an_undefined_symbol():
    errors = _errors("""
        abstract class AbstractReader {
            public abstract int read();
        }
        class Reader extends AbstractReader {
            public int read() { return 42; }
        }
        int invoke(AbstractReader reader) { return reader.read(); }
    """)

    assert "Abstract method 'AbstractReader.read' cannot be called" in errors


def test_concrete_override_remains_callable():
    analyzed = _analyze("""
        abstract class AbstractReader {
            public abstract int read();
        }
        class Reader extends AbstractReader {
            public int read() { return 42; }
        }
        int invoke(Reader reader) { return reader.read(); }
    """)

    assert analyzed.errors == []


@pytest.mark.parametrize(
    ("type_text", "expected", "actual"),
    (
        ("Vector", 1, 0),
        ("Vector<int, int>", 1, 2),
        ("Array<int, int>", 1, 2),
        ("List<int, int>", 1, 2),
        ("Set<int, int>", 1, 2),
        ("Thread<int, int>", 1, 2),
        ("Mutex<int, int>", 1, 2),
        ("Map<int>", 2, 1),
        ("Map<int, int, int>", 2, 3),
    ),
)
def test_runtime_generic_arity_is_validated_without_stdlib_stubs(
    type_text: str,
    expected: int,
    actual: int,
):
    errors = _errors(f"void run() {{ {type_text} value; }}")
    assert (f"Type '{type_text.split('<', 1)[0]}' expects {expected} generic argument(s) but got {actual}") in errors


def test_runtime_generic_arity_is_validated_in_registered_aggregate_fields():
    errors = _errors("struct Values { Map<int> entries; };")
    assert "Type 'Map' expects 2 generic argument(s) but got 1" in errors


@pytest.mark.parametrize("type_text", ("Tuple<int>", "__fn_ptr"))
def test_variadic_runtime_types_require_their_minimum_shape(type_text: str):
    errors = _errors(f"void run() {{ {type_text} value; }}")
    minimum = 2 if type_text.startswith("Tuple") else 1
    base = type_text.split("<", 1)[0]
    assert (f"Type '{base}' expects at least {minimum} generic argument(s) but got") in errors


def test_valid_runtime_generic_arities_remain_accepted():
    analyzed = _analyze("""
        void run() {
            Vector<int> vector;
            Array<int> array;
            List<int> list;
            Set<int> set;
            Thread<int> thread = spawn(() => 1);
            thread.join();
            Mutex<int> mutex;
            Map<int, string> map;
            Tuple<int, string> tuple;
            Tuple<int, string, bool> triple;
            __fn_ptr<void> callback;
        }
    """)

    assert analyzed.errors == []
