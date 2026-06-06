"""Behavioral tests for the remaining LSP features: hover, completion,
find-references, rename, document symbols, signature help, semantic tokens.
All drive the real feature functions over SAMPLE through the shared compiler."""

from src.devex.lsp.completion import get_completions
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.references import (
    get_references,
    get_rename_edits,
    prepare_rename,
)
from src.devex.lsp.semantic_tokens import get_semantic_tokens
from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.symbols import get_document_symbols
from src.devex.lsp.tests.lsphelp import SAMPLE, analyze, decoded_semantic_tokens, hover_text, pos_of

# ----------------------------------------------------------------- hover

def test_hover_method_shows_name():
    r = analyze(SAMPLE)
    txt = hover_text(get_hover_info(r, pos_of(SAMPLE, "p.getX", offset=2)))
    assert "getX" in txt


def test_hover_class_shows_name():
    r = analyze(SAMPLE)
    txt = hover_text(get_hover_info(r, pos_of(SAMPLE, "Point p", offset=1)))
    assert "Point" in txt


def test_hover_empty_on_blank():
    r = analyze(SAMPLE)
    # column far past end of an empty line → no hover
    assert get_hover_info(r, pos_of(SAMPLE, "\n\n", offset=1)) is None


# ------------------------------------------------------------- completion

def test_member_completion_lists_methods():
    r = analyze(SAMPLE)
    # cursor right after `p.` in `p.getX()` → member completion on Point
    items = get_completions(r, pos_of(SAMPLE, "p.getX", offset=2))
    labels = {it.label for it in items}
    assert "getX" in labels and "doubled" in labels


def test_top_level_completion_includes_user_symbols():
    r = analyze(SAMPLE)
    # inside main(), at the start of the `return` line, identifiers are offered
    items = get_completions(r, pos_of(SAMPLE, "return v", offset=0))
    labels = {it.label for it in items}
    assert "Point" in labels or "add" in labels


# ------------------------------------------------- references + rename

def test_find_references_of_method():
    r = analyze(SAMPLE)
    refs = get_references(r, pos_of(SAMPLE, "p.getX", offset=2),
                          include_declaration=True)
    lines = sorted(loc.range.start.line for loc in refs)
    assert 7 in lines    # the getX declaration
    assert 13 in lines   # the p.getX() call


def test_find_references_excludes_declaration_when_asked():
    r = analyze(SAMPLE)
    with_decl = get_references(r, pos_of(SAMPLE, "p.getX", offset=2),
                               include_declaration=True)
    without = get_references(r, pos_of(SAMPLE, "p.getX", offset=2),
                             include_declaration=False)
    assert len(without) < len(with_decl)


def test_prepare_rename_returns_symbol_range():
    r = analyze(SAMPLE)
    rng = prepare_rename(r, pos_of(SAMPLE, "p = Point", offset=0))  # the local `p`
    assert rng is not None
    assert rng.start.line == 12


def test_rename_local_edits_all_uses():
    r = analyze(SAMPLE)
    edit = get_rename_edits(r, pos_of(SAMPLE, "p = Point", offset=0), "q")
    assert edit is not None
    # gather edits regardless of changes vs documentChanges representation
    changes = edit.changes or {}
    all_edits = [e for edits in changes.values() for e in edits]
    if not all_edits and edit.document_changes:
        for dc in edit.document_changes:
            all_edits.extend(getattr(dc, "edits", []))
    assert len(all_edits) >= 2                     # decl + use
    assert all(e.new_text == "q" for e in all_edits)


# --------------------------------------------------------- doc symbols

def test_document_symbols_tree():
    r = analyze(SAMPLE)
    syms = get_document_symbols(r)
    names = {s.name for s in syms}
    assert {"Point", "main", "add", "Color"} <= names
    point = next(s for s in syms if s.name == "Point")
    child_names = {c.name for c in (point.children or [])}
    assert "getX" in child_names and "x" in child_names


# ------------------------------------------------------ signature help

def test_signature_help_inside_call():
    r = analyze(SAMPLE)
    # inside add(self.x, self.x) on line 8 — cursor just after the '('
    sig = get_signature_help(r, pos_of(SAMPLE, "add(self.x", offset=4))
    assert sig is not None and sig.signatures
    assert "add" in sig.signatures[0].label


# ------------------------------------------------------ semantic tokens

def test_semantic_tokens_nonempty():
    r = analyze(SAMPLE)
    toks = get_semantic_tokens(r)
    assert toks is not None
    assert len(toks.data) > 0 and len(toks.data) % 5 == 0  # 5 ints per token


def test_semantic_tokens_cover_fstring_variables_in_document_only():
    source = 'int main() { string label = "hi"; var command = f"printf {label} >&2"; return 0; }\n'

    tokens = get_semantic_tokens(analyze(source))

    assert tokens is not None
    decoded = decoded_semantic_tokens(source, tokens.data, with_position=True)
    assert (0, 58, "label", "variable", 0) in decoded
