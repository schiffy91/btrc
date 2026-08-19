"""Structural parse guards for the unified catalog's self-hosted AST."""

from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import ParseError, Parser
from tools.compiler_codegen.ast import AstCatalogGenerator

_ROOT = Path(__file__).resolve().parents[3]
_BTRC_AST = PurePosixPath("src/compiler/btrc/generated/ast/node.btrc")


def _generate_btrc() -> str:
    artifact = next(
        artifact
        for artifact in AstCatalogGenerator(_ROOT).artifacts()
        if artifact.path == _BTRC_AST
    )
    return artifact.content.decode("utf-8")


def test_generated_btrc_parses_without_error():
    """The full generated btrc parses with btrc's own parser."""
    src = _generate_btrc()
    tokens = Lexer(src).tokenize()
    try:
        program = Parser(tokens).parse()
    except ParseError as exc:  # pragma: no cover - failure path
        raise AssertionError(f"generated btrc failed to parse: {exc}") from exc
    assert program.declarations, "expected generated btrc to contain declarations"


def test_fat_tagged_node_class_is_present():
    src = _generate_btrc()
    program = Parser(Lexer(src).tokenize()).parse()

    from src.compiler.python.syntax.ast.generated import ClassDecl

    class_names = {d.name for d in program.declarations if isinstance(d, ClassDecl)}
    assert class_names == {"Node"}


def test_keyword_field_names_are_escaped():
    """Fields named like btrc keywords are renamed (default -> default_)."""
    src = _generate_btrc()
    # Must parse, and the raw keyword field declaration must not appear.
    assert "public expr default;" not in src
    assert "default_" in src
    assert "keep_" in src


def test_node_typed_fields_use_the_fat_node_owner():
    src = _generate_btrc()
    program = Parser(Lexer(src).tokenize()).parse()

    from src.compiler.python.syntax.ast.generated import ClassDecl, FieldDecl

    node = next(
        declaration
        for declaration in program.declarations
        if isinstance(declaration, ClassDecl) and declaration.name == "Node"
    )
    field_types = {
        member.type.base for member in node.members if isinstance(member, FieldDecl)
    }
    assert "Node" in field_types
    assert "expr" not in field_types
