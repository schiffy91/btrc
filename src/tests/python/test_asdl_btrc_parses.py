"""Smoke test: the btrc AST generator (asdl_btrc.py) emits btrc that PARSES.

The generator produces btrc-language AST node classes from ast.asdl for the
eventual self-hosted compiler. Its output was historically unparseable:
  - ASDL field names colliding with btrc keywords (``default``, ``keep``) were
    emitted verbatim -> ParseError "Expected member name, got DEFAULT".
  - ASDL sum-type names (``expr``, ``stmt``, ...) were used as field types with
    no backing btrc class/typedef.

This test runs asdl_btrc on the real ast.asdl, then lexes + parses the output
with btrc's own Lexer/Parser (no ParseError allowed). It permanently guards the
generator. It does not require the output to compile to C -- there is no
self-hosted pipeline yet; PARSING is the bar.
"""

from __future__ import annotations

import importlib.util
import os

from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import ParseError, Parser

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
# ast.asdl lives beside grammar.ebnf in src/language/; the btrc AST generator
# (asdl_btrc.py) lives with the rest of the Python AST tooling.
_ASDL_FILE = os.path.join(_ROOT, "src", "language", "ast.asdl")
_ASDL_BTRC_PY = os.path.join(_ROOT, "src", "compiler", "python", "ast", "asdl_btrc.py")


def _load_asdl_btrc():
    """Import asdl_btrc.py by path (it lives outside the test's package)."""
    spec = importlib.util.spec_from_file_location("asdl_btrc_mod", _ASDL_BTRC_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _generate_btrc() -> str:
    asdl_btrc = _load_asdl_btrc()
    module = asdl_btrc.parse_file(_ASDL_FILE)
    return asdl_btrc.generate(module)


def test_generated_btrc_parses_without_error():
    """The full generated btrc parses with btrc's own parser."""
    src = _generate_btrc()
    tokens = Lexer(src).tokenize()
    try:
        program = Parser(tokens).parse()
    except ParseError as exc:  # pragma: no cover - failure path
        raise AssertionError(f"generated btrc failed to parse: {exc}") from exc
    assert program.declarations, "expected generated btrc to contain declarations"


def test_expected_node_classes_present():
    """Key constructor classes and a sum-type base class are emitted."""
    src = _generate_btrc()
    program = Parser(Lexer(src).tokenize()).parse()

    from src.compiler.python.ast_nodes import ClassDecl

    class_names = {d.name for d in program.declarations if isinstance(d, ClassDecl)}
    # Constructor classes (one per ASDL constructor).
    for expected in ("ClassDecl", "BinaryExpr", "ImportDecl", "Param"):
        assert expected in class_names, f"missing class {expected}"
    # Base class generated for the ``expr`` sum type (and others).
    assert "Expr" in class_names, "missing sum-type base class Expr"


def test_keyword_field_names_are_escaped():
    """Fields named like btrc keywords are renamed (default -> default_)."""
    src = _generate_btrc()
    # Must parse, and the raw keyword field declaration must not appear.
    assert "public expr default;" not in src
    assert "default_" in src
    assert "keep_" in src


def test_sum_typed_fields_use_backing_base_class():
    """Sum-typed fields reference the generated base class, never the raw
    lowercase ASDL sum name (which has no btrc class)."""
    src = _generate_btrc()
    program = Parser(Lexer(src).tokenize()).parse()

    from src.compiler.python.ast_nodes import ClassDecl, FieldDecl

    binary = next(d for d in program.declarations if isinstance(d, ClassDecl) and d.name == "BinaryExpr")
    field_types = {m.type.base for m in binary.members if isinstance(m, FieldDecl)}
    # left/right are ASDL ``expr`` -> btrc ``Expr`` (the base class).
    assert "Expr" in field_types
    assert "expr" not in field_types
