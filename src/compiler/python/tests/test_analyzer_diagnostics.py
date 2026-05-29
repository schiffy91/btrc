"""Behavioral analyzer tests: assert real diagnostics (not just line execution)
for enum-switch exhaustiveness, the managed-alias warning, and parallel-for."""

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(src):
    return Analyzer().analyze(Parser(Lexer(src, "<t>").tokenize()).parse())


def errors(src):
    return _analyze(src).errors


def warnings(src):
    return _analyze(src).warnings


def _has(msgs, sub):
    return any(sub in m for m in msgs)


def test_non_exhaustive_enum_switch_is_flagged():
    src = """
    enum Color { RED, GREEN, BLUE };
    int main() {
        Color c = RED;
        switch (c) {
            case RED: break;
            case GREEN: break;
        }
        return 0;
    }
    """
    errs = errors(src)
    assert _has(errs, "not exhaustive")
    assert _has(errs, "BLUE")          # names the specific missing variant


def test_exhaustive_enum_switch_is_accepted():
    src = """
    enum Color { RED, GREEN, BLUE };
    int main() {
        Color c = RED;
        switch (c) {
            case RED: break;
            case GREEN: break;
            case BLUE: break;
        }
        return 0;
    }
    """
    assert not _has(errors(src), "not exhaustive")


def test_default_case_makes_switch_exhaustive():
    src = """
    enum Color { RED, GREEN, BLUE };
    int main() {
        Color c = RED;
        switch (c) {
            case RED: break;
            default: break;
        }
        return 0;
    }
    """
    assert not _has(errors(src), "not exhaustive")


def test_managed_alias_emits_warning():
    src = """
    class Node { public int v; public Node(int v) { self.v = v; } }
    int main() {
        Node a = Node(1);
        var b = a;           // inferred class type → aliases a managed variable
        return b.v;
    }
    """
    assert _has(warnings(src), "Aliasing managed variable")


def test_primitive_copy_is_not_aliased():
    src = """
    int main() {
        int a = 1;
        var b = a;           // inferred primitive — no alias warning
        return b;
    }
    """
    assert not _has(warnings(src), "Aliasing managed variable")


def test_parallel_for_analyzes_without_error():
    src = """
    int main() {
        Vector<int> xs = [1, 2, 3];
        int total = 0;
        parallel for x in xs { total = total + x; }
        return total;
    }
    """
    assert not errors(src)
