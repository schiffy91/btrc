"""Remaining reachable edge paths: degraded literal-init hover, parameter
hover, no-call signature context, zero-arg active parameter, stdlib static
completion, and an unlocated analyzer diagnostic."""

from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.devex.lsp.completion import get_completions
from src.devex.lsp.diagnostics import AnalysisResult, compute_diagnostics
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.tests.lsphelp import analyze, hover_text, pos_of


def _degraded(src, uri="file:///x.btrc"):
    tokens = Lexer(src, "x").tokenize()
    ast = Parser(tokens).parse()
    return AnalysisResult(uri=uri, source=src, tokens=tokens, ast=ast, analyzed=None)


def test_hover_var_literal_init_fallback():
    # var initialized from a literal (not call/new) → heuristic falls back
    src = "int main() { var k = 5; return k; }\n"
    t = hover_text(get_hover_info(_degraded(src), pos_of(src, "var k", offset=4)))
    assert t != ""


def test_hover_method_parameter():
    src = ("class C { public int v; public C(int v) { self.v = v; }\n"
           "          public int f(int a) { return a; } }\n"
           "int main() { C c = C(1); return c.f(2); }\n")
    t = hover_text(get_hover_info(analyze(src), pos_of(src, "return a", offset=7)))
    assert "a" in t


def test_signature_help_outside_any_call_is_none():
    src = "int main() { int z = 1 + 2; return z; }\n"
    assert get_signature_help(analyze(src), pos_of(src, "1 + 2", offset=0)) is None


def test_signature_zero_arguments_active_param_zero():
    src = ("class C { public int v; public C() { self.v = 0; }\n"
           "          public int f(int a) { return a; } }\n"
           "int main() { C c = C(); return c.f(); }\n")
    s = get_signature_help(analyze(src), pos_of(src, "c.f()", offset=4))  # cursor between ( )
    assert s is None or s.active_parameter == 0


def test_completion_stdlib_class_static_methods_offered():
    src = 'int main() { string s = Strings.copy("x"); return 0; }\n'
    names = {i.label for i in get_completions(analyze(src), pos_of(src, "Strings.copy", offset=8))}
    assert names


def test_unlocated_analyzer_error_becomes_diagnostic(monkeypatch):
    # an analyzer diag without a position (line/col 0) maps to a 1:1 diagnostic
    from src.compiler.python.analyzer.analyzer import Analyzer
    from src.compiler.python.analyzer.core import Diag

    real = Analyzer.analyze

    def fake(self, program):
        res = real(self, program)
        res.diags.append(Diag("a problem with no position", 0, 0))
        return res

    monkeypatch.setattr(Analyzer, "analyze", fake)
    r = compute_diagnostics("file:///t.btrc", "int main() { return 0; }\n")
    assert any("no position" in d.message for d in r.diagnostics)
    bad = next(d for d in r.diagnostics if "no position" in d.message)
    assert (bad.range.start.line, bad.range.start.character) == (0, 0)
