"""Type normalization must preserve the complete TypeExpr contract."""

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ast_nodes import FunctionDecl, TypeExpr
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(source: str):
    program = Parser(Lexer(source, "<type-metadata>").tokenize()).parse()
    analyzed = Analyzer().analyze(program)
    assert analyzed.errors == []
    return program, analyzed


def test_class_upgrade_preserves_nested_qualifiers():
    program, _ = _analyze("""
        class Item {}
        class Box<T> {}
        void consume(const volatile Box<Item?> value) {}
    """)

    function = next(decl for decl in program.declarations if isinstance(decl, FunctionDecl) and decl.name == "consume")
    outer = function.params[0].type
    inner = outer.generic_args[0]

    assert outer.base == "Box"
    assert outer.pointer_depth == 1
    assert outer.is_const is True
    assert outer.is_volatile is True
    assert inner.base == "Item"
    assert inner.pointer_depth == 1
    assert inner.is_const is False
    assert inner.is_nullable is True


def test_generic_substitution_preserves_placeholder_metadata():
    analyzer = Analyzer()
    placeholder = TypeExpr(
        base="T",
        pointer_depth=1,
        is_array=True,
        is_const=True,
        is_nullable=True,
        is_static=True,
        is_extern=True,
        is_volatile=True,
        line=7,
        col=11,
    )
    concrete = TypeExpr(base="Item", pointer_depth=1, line=2, col=3)

    result = analyzer._substitute_type(placeholder, {"T": concrete})

    assert result.base == "Item"
    assert result.pointer_depth == 2
    assert result.is_array is True
    assert result.is_const is True
    assert result.is_nullable is True
    assert result.is_static is True
    assert result.is_extern is True
    assert result.is_volatile is True
    assert (result.line, result.col) == (7, 11)


def test_nested_generic_substitution_preserves_owner_metadata():
    analyzer = Analyzer()
    owner = TypeExpr(
        base="Vector",
        generic_args=[TypeExpr(base="T")],
        pointer_depth=1,
        is_const=True,
        is_volatile=True,
    )

    result = analyzer._substitute_type(owner, {"T": TypeExpr(base="int")})

    assert result.generic_args[0].base == "int"
    assert result.pointer_depth == 1
    assert result.is_const is True
    assert result.is_volatile is True
