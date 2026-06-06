"""Final reachable branches: semantic-token classification (new/constructor/
generic), static-method dedup completion, constructor signature, and the
server's signature last-good fallback."""

import importlib

from lsprotocol import types as lsp

from src.devex.lsp.completion import get_completions
from src.devex.lsp.semantic_tokens import get_semantic_tokens
from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.tests.lsphelp import SAMPLE, analyze, decoded_semantic_tokens, pos_of

srv = importlib.import_module("src.devex.lsp.server")
URI = "file:///t.btrc"


def test_semantic_tokens_new_constructor_and_generic():
    src = ("enum Color { RED, GREEN };\n"
           "class Box<T> { public T v; public Box(T v) { self.v = v; } }\n"
           "int main() {\n"
           "    Box<int> b = new Box(5);\n"
           "    Color c = RED;\n"
           "    return 0;\n"
           "}\n")
    toks = get_semantic_tokens(analyze(src))
    assert toks is not None and len(toks.data) > 0
    decoded = decoded_semantic_tokens(src, toks.data)
    assert ("Box", "type", 0) in decoded
    assert ("Color", "type", 0) in decoded
    assert ("RED", "enumMember", 0) in decoded


def test_completion_stdlib_class_dedup():
    # Strings is both in the analyzed class_table and the stdlib static table;
    # the dedup loop avoids duplicate labels.
    src = 'int main() { string s = Strings.copy("x"); return 0; }\n'
    items = get_completions(analyze(src), pos_of(src, "Strings.copy", offset=8))
    labels = [i.label for i in items]
    assert len(labels) == len(set(labels))   # no duplicates


def test_constructor_signature_active_param():
    src = ("class Rect { public int w; public int h;\n"
           "    public Rect(int w, int h) { self.w = w; self.h = h; } }\n"
           "int main() { Rect r = Rect(3, 4); return r.w; }\n")
    s = get_signature_help(analyze(src), pos_of(src, "Rect(3, 4)", offset=5))
    assert s is not None and len(s.signatures[0].parameters) == 2


def test_server_signature_falls_back_to_last_good(monkeypatch):
    published = []
    monkeypatch.setattr(srv.server, "text_document_publish_diagnostics",
                        lambda params: published.append(params), raising=False)

    class _Doc:
        source = SAMPLE

    class _WS:
        def get_text_document(self, uri):
            return _Doc()

    monkeypatch.setattr(srv.server.protocol, "_workspace", _WS(), raising=False)
    srv._validate_document(URI, SAMPLE)                 # good analysis cached
    srv._validate_document(URI, "class { broken")        # current is broken (no analysis)
    sig = srv.signature_help(lsp.SignatureHelpParams(
        text_document=lsp.TextDocumentIdentifier(uri=URI),
        position=pos_of(SAMPLE, "add(self.x", offset=4)))
    assert sig is not None and sig.signatures
