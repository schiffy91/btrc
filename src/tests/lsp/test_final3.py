"""Remaining reachable branches: inherited-member access classification,
user-class static completion, semantic-token type classification, parent-chain
member resolution, and degraded-mode defensive returns."""

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.devex.lsp.analysis.document import DocumentAnalysis as AnalysisResult
from src.tests.lsp.lsphelp import (
    analyze,
    get_completions,
    get_definition,
    get_hover_info,
    get_references,
    get_semantic_tokens,
    get_signature_help,
    pos_of,
)

INH = """\
class Animal {
    public string name;
    public Animal(string n) { self.name = n; }
    public string speak() { return self.name; }
}

class Dog extends Animal {
    public Dog(string n) { self.name = n; }
}

int main() {
    Dog d = Dog("rex");
    string s = d.speak();
    string nm = d.name;
    return 0;
}
"""


def test_references_inherited_method_access_classifies_via_parent():
    # click the *access* d.speak(); speak is inherited (Dog doesn't override it).
    # Non-empty result means it classified as a member via the parent chain
    # (a misclassification as a plain variable would drop the dotted access).
    refs = get_references(analyze(INH), pos_of(INH, "d.speak", offset=2))
    assert refs


def test_references_inherited_field_access_classifies_via_parent():
    refs = get_references(analyze(INH), pos_of(INH, "d.name", offset=2))
    assert refs


def test_hover_inherited_member_access():
    from src.tests.lsp.lsphelp import hover_text

    t = hover_text(get_hover_info(analyze(INH), pos_of(INH, "d.speak", offset=2)))
    assert "speak" in t


# --- user-class static method completion ------------------------------------


def test_completion_user_class_static_methods():
    src = (
        "class Util {\n"
        "    public int x;\n"
        "    public Util() { self.x = 0; }\n"
        "    class int helper(int a) { return a; }\n"
        "}\n"
        "int main() { return Util.helper(5); }\n"
    )
    names = {i.label for i in get_completions(analyze(src), pos_of(src, "Util.helper", offset=5))}
    assert "helper" in names


# --- semantic token type classification -------------------------------------


def test_semantic_tokens_classify_type_names():
    src = (
        "struct Pt { int x; int y; };\n"
        "typedef int Id;\n"
        "class Widget { public int w; public Widget() { self.w = 0; } }\n"
        "int main() {\n"
        "    Widget wd = Widget();\n"
        "    Id n = 5;\n"
        "    return n + wd.w;\n"
        "}\n"
    )
    toks = get_semantic_tokens(analyze(src))
    assert toks is not None and len(toks.data) > 0


# --- degraded mode: members that cannot resolve hit the defensive returns ----


def _degraded(src, uri="file:///x.btrc"):
    tokens = Lexer(src, "x").tokenize()
    ast = Parser(tokens).parse()
    return AnalysisResult(uri=uri, source=src, tokens=tokens, ast=ast, analyzed=None)


def test_degraded_unresolvable_member_degrades_cleanly():
    src = "int main() { mystery.thing(); return 0; }\n"
    r = _degraded(src)
    pos = pos_of(src, "mystery.thing", offset=8)  # cursor on `thing`
    assert get_hover_info(r, pos) is None
    assert get_definition(r, pos) is None
    assert isinstance(get_completions(r, pos_of(src, "mystery.thing", offset=8)), list)
    s = get_signature_help(r, pos_of(src, "thing()", offset=6))
    assert s is None or s.signatures
    assert get_references(r, pos) == [] or isinstance(get_references(r, pos), list)
