"""Canonical typedef receiver semantics and strict-C lowering."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import Identifier
from src.tests.python.test_codegen import emit_c

FIXTURE = Path(__file__).resolve().parents[1] / "btrc" / "fixtures" / "typedef_member_alias_runtime.btrc"
COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

TYPEDEF_OPERATOR_RUNTIME_SOURCE = r"""
#include <assert.h>

class Box<T> {
    public T value;
    public Box(T value) { self.value = value; }
    public Box<T> __add__(T delta) { return new Box<T>(delta); }
    public bool __eq__(T other) { return self.value == other; }
}

class SignedValue {
    public int value;
    public SignedValue(int value) { self.value = value; }
    public SignedValue __neg__() { return new SignedValue(-self.value); }
}

typedef Box<int> IntBox;
typedef SignedValue SignedAlias;

int main() {
    IntBox value = new Box<int>(2);
    IntBox sum = value + 3;
    value += 4;
    SignedAlias original = new SignedValue(5);
    SignedAlias negative = -original;

    assert(sum.value == 3);
    assert(value.value == 4);
    assert(sum == 3);
    assert(value == 4);
    assert(negative.value == -5);

    value = null;
    sum = null;
    original = null;
    negative = null;
    return 0;
}
"""


def _parse(source: str):
    return Parser(Lexer(source, "<typedef-members>").tokenize()).parse()


def _analyze(source: str):
    program = _parse(source)
    return program, SemanticAnalyzer().analyze(program)


def _walk(node):
    if is_dataclass(node):
        yield node
        for field in fields(node):
            yield from _walk(getattr(node, field.name))
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk(item)


def test_alias_receivers_are_stored_as_canonical_semantic_types():
    program, analyzed = _analyze(FIXTURE.read_text())
    assert analyzed.errors == []

    box_types = [
        analyzed.node_types[id(node)] for node in _walk(program) if isinstance(node, Identifier) and node.name == "box"
    ]
    cell_types = [
        analyzed.node_types[id(node)] for node in _walk(program) if isinstance(node, Identifier) and node.name == "cell"
    ]

    assert box_types and {type_expr.base for type_expr in box_types} == {"Box"}
    assert cell_types and {type_expr.base for type_expr in cell_types} == {"Cell"}
    assert all([argument.base for argument in type_expr.generic_args] == ["int"] for type_expr in cell_types)


@pytest.mark.parametrize(
    ("source", "diagnostic"),
    (
        (
            "class Vault { private int secret; } typedef Vault Alias; int read(Alias value) { return value.secret; }",
            "private field 'secret'",
        ),
        (
            "class Vault { private int secret { get; set; } } typedef Vault Alias; "
            "int read(Alias value) { return value.secret; }",
            "private property 'secret'",
        ),
        (
            "class Accessors { public int readOnly { get; } } typedef Accessors Alias; "
            "void write(Alias value) { value.readOnly = 1; }",
            "property 'readonly' has no setter",
        ),
        (
            "class Accessors { public int writeOnly { set; } } typedef Accessors Alias; "
            "int read(Alias value) { return value.writeOnly; }",
            "property 'writeonly' has no getter",
        ),
        (
            "class Accessors { public int writeOnly { set; } } typedef Accessors Alias; "
            "void update(Alias value) { value.writeOnly += 1; }",
            "property 'writeonly' has no getter",
        ),
        (
            "class Slots { public int get(string key) { return 0; } } typedef Slots Alias; "
            "int read(Alias value) { return value[1]; }",
            "expects 'string'",
        ),
        (
            "class Vault { private int reveal() { return 1; } } typedef Vault Alias; "
            "int read(Alias value) { return value.reveal(); }",
            "private method 'reveal'",
        ),
    ),
)
def test_alias_receivers_preserve_member_contracts(source: str, diagnostic: str):
    _program, analyzed = _analyze(source)
    assert any(diagnostic in error.lower() for error in analyzed.errors)


def test_alias_declarations_keep_source_spelling_but_dispatch_canonically():
    generated = emit_c(FIXTURE.read_text())

    assert "BoxAlias box = Box_new(10);" in generated
    assert "CellAlias cell = btrc_Cell_int_new(5);" in generated
    for symbol in ("Box_get_value", "Box_set_value", "Box_get", "Box_set", "Box_add"):
        assert f"{symbol}(" in generated
    for symbol in (
        "btrc_Cell_int_get_value",
        "btrc_Cell_int_set_value",
        "btrc_Cell_int_get",
        "btrc_Cell_int_set",
        "btrc_Cell_int_read",
    ):
        assert f"{symbol}(" in generated
    assert "box.value" not in generated
    assert "box[" not in generated
    assert "box.add(" not in generated


def test_alias_operators_dispatch_canonically_but_keep_physical_spelling():
    _program, analyzed = _analyze(TYPEDEF_OPERATOR_RUNTIME_SOURCE)
    assert analyzed.errors == []

    generated = emit_c(TYPEDEF_OPERATOR_RUNTIME_SOURCE)
    assert "IntBox value = btrc_Box_int_new(2);" in generated
    assert "SignedAlias original = SignedValue_new(5);" in generated
    assert "btrc_Box_int___add__(" in generated
    assert "btrc_Box_int___eq__(" in generated
    assert "SignedValue___neg__(" in generated
    assert "IntBox __btrc_update_old_" in generated


@pytest.mark.parametrize(
    ("source", "diagnostic"),
    (
        (
            "class Secret { private Secret __add__(int delta) { return self; } } "
            "typedef Secret Alias; "
            "void run(Alias value) { Alias result = value + 1; }",
            "private operator 'Secret.__add__'",
        ),
        (
            'typedef string TextAlias; void run() { TextAlias value = "x"; value -= "x"; }',
            "Operator '-=' is not defined for 'TextAlias' and 'string'",
        ),
    ),
)
def test_alias_operators_preserve_invalid_operation_checks(source: str, diagnostic: str):
    _program, analyzed = _analyze(source)
    assert any(diagnostic in error for error in analyzed.errors), analyzed.errors


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_alias_member_runtime_is_strict_c11(tmp_path: Path, c_compiler: str):
    generated = tmp_path / "typedef_member_aliases.c"
    binary = tmp_path / "typedef_member_aliases"
    generated.write_text(emit_c(FIXTURE.read_text()))
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(generated),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, timeout=10)


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_alias_operator_runtime_is_strict_c11(tmp_path: Path, c_compiler: str):
    generated = tmp_path / "typedef_operators.c"
    binary = tmp_path / "typedef_operators"
    generated.write_text(emit_c(TYPEDEF_OPERATOR_RUNTIME_SOURCE))
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(generated),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
