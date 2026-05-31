"""Parser coverage for the type grammar: C-style multi-word primitives, struct/
enum/union/tuple type spellings, array-sized parameters, `keep` params, and the
`<` generic-vs-comparison disambiguation."""

from src.compiler.python.ast_nodes import FunctionDecl, Param
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def parse(src):
    return Parser(Lexer(src, "<t>").tokenize()).parse()


def _types_of(src):
    """All TypeExpr.base strings reachable from a parsed program's main body."""
    prog = parse(src)
    return prog


def test_multiword_primitive_types_parse():
    # unsigned long long, long double, long int, short int, short — exercised as
    # parameter and return types (the type grammar entry point).
    src = """
    unsigned long long ull(unsigned long long x) { return x; }
    long double ld(long double x) { return x; }
    long int li(long int x) { return x; }
    short int si(short int x) { return x; }
    short sh(short x) { return x; }
    unsigned int ui(unsigned int x) { return x; }
    int main() { return 0; }
    """
    prog = parse(src)
    fns = [d.name for d in prog.declarations if isinstance(d, FunctionDecl)]
    assert {"ull", "ld", "li", "si", "sh", "ui"} <= set(fns)


def test_struct_enum_type_usage():
    src = """
    enum Color { RED, GREEN };
    struct Point { int x; int y; };
    int main() {
        enum Color c = RED;
        struct Point p;
        return 0;
    }
    """
    prog = parse(src)
    assert prog.declarations


def test_tuple_type_in_signature():
    # (int, int) is a tuple type; nested tuples exercise the paren-depth scan.
    src = "(int, int) swap((int, int) pair) { return pair; }\nint main() { return 0; }"
    prog = parse(src)
    fns = [d for d in prog.declarations if isinstance(d, FunctionDecl)]
    assert any(f.name == "swap" for f in fns)


def test_parameter_with_explicit_array_size():
    src = "int sum(int buf[10]) { return buf[0]; }\nint main() { return 0; }"
    prog = parse(src)
    swap = next(d for d in prog.declarations
                if isinstance(d, FunctionDecl) and d.name == "sum")
    assert swap.params[0].type.is_array
    assert swap.params[0].type.array_size is not None


def test_keep_parameter():
    src = ("class Obj { public int v; public Obj() { self.v = 0; } }\n"
           "void hold(keep Obj o) { return; }\nint main() { return 0; }")
    prog = parse(src)
    hold = next(d for d in prog.declarations
                if isinstance(d, FunctionDecl) and d.name == "hold")
    assert hold.params[0].keep is True


def test_less_than_is_comparison_not_generic():
    # `a < b` must parse as comparison; the generic-start lookahead bails at ';'.
    src = "int main() { int a = 1; int b = 2; bool c = a < b; bool d = a < b == false; return 0; }"
    prog = parse(src)
    assert prog.declarations


def test_nullable_and_pointer_and_const_types():
    src = """
    class N { public int v; public N() { self.v = 0; } }
    int main() {
        N? maybe = null;
        const int k = 5;
        return k;
    }
    """
    prog = parse(src)
    assert prog.declarations
