"""Degenerate inputs — empty documents, cursors on non-identifiers, and
transient parse errors. Every feature must degrade gracefully (no crash; an
empty/None result), which exercises the early-return guards in each module."""

from lsprotocol import types as lsp

from src.devex.lsp.completion import get_completions
from src.devex.lsp.definition import get_definition
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.references import get_references, get_rename_edits, prepare_rename
from src.devex.lsp.semantic_tokens import get_semantic_tokens
from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.symbols import get_document_symbols
from src.devex.lsp.tests.lsphelp import analyze, pos_of

ORIGIN = lsp.Position(line=0, character=0)


def test_empty_document_degrades_everywhere():
    r = analyze("")
    assert get_definition(r, ORIGIN) is None
    assert get_hover_info(r, ORIGIN) is None
    assert get_references(r, ORIGIN) == []
    assert get_signature_help(r, ORIGIN) is None
    assert prepare_rename(r, ORIGIN) is None
    assert get_rename_edits(r, ORIGIN, "x") is None
    assert get_document_symbols(r) == []
    assert isinstance(get_completions(r, ORIGIN), list)
    st = get_semantic_tokens(r)
    assert st is None or st.data == []


def test_cursor_on_blank_line():
    src = "int main() {\n    \n    return 0;\n}\n"
    r = analyze(src)
    ws = lsp.Position(line=1, character=2)  # the indented blank line
    assert get_definition(r, ws) is None
    assert get_hover_info(r, ws) is None
    assert get_references(r, ws) == []
    assert prepare_rename(r, ws) is None


def test_cursor_on_punctuation():
    src = "int main() { return 0; }\n"
    r = analyze(src)
    semi = pos_of(src, ";", offset=0)
    assert get_definition(r, semi) is None
    assert prepare_rename(r, semi) is None
    assert get_references(r, semi) == []


def test_broken_parse_keeps_diagnostics_but_no_ast_features():
    r = analyze("class { not valid\n")  # parse error → no AST
    assert r.diagnostics                 # the error is still reported
    assert get_definition(r, ORIGIN) is None
    assert get_references(r, ORIGIN) == []
    assert get_document_symbols(r) == []
