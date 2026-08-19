"""Class members preserve explicit declarator-array storage."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.syntax.ast.generated import ClassDecl, FieldDecl, IntLiteral
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def test_fixed_class_field_array_suffix_is_typed_storage():
    program = Parser(Lexer("class Buffer { public int values[2]; }", "<test>").tokenize()).parse()

    declaration = program.declarations[0]
    assert isinstance(declaration, ClassDecl)
    field = declaration.members[0]
    assert isinstance(field, FieldDecl)
    assert field.type.is_array
    assert isinstance(field.type.array_size, IntLiteral)
    assert field.type.array_size.value == 2


def test_generic_class_field_array_suffix_preserves_element_parameter():
    program = Parser(Lexer("class Buffer<T> { public T values[4]; }", "<test>").tokenize()).parse()

    field = program.declarations[0].members[0]
    assert isinstance(field, FieldDecl)
    assert field.type.base == "T"
    assert field.type.is_array
    assert field.type.array_size.value == 4


def test_fixed_array_property_is_rejected_before_codegen():
    program = Parser(
        Lexer(
            "class Buffer { public int values[4] { get; set; } }",
            "<test>",
        ).tokenize()
    ).parse()

    errors = SemanticAnalyzer().analyze(program).errors

    assert any("Property 'Buffer.values' cannot use fixed-size array storage" in error for error in errors)


def test_fixed_array_field_with_managed_elements_is_rejected():
    program = Parser(
        Lexer(
            "class Item { public Item() {} } class Buffer { public Item values[4]; }",
            "<test>",
        ).tokenize()
    ).parse()

    errors = SemanticAnalyzer().analyze(program).errors

    assert any("Field 'Buffer.values' cannot contain managed elements" in error for error in errors)
