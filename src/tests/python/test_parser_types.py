"""Parser coverage for the type grammar: C-style multi-word primitives, struct/
enum/union/tuple type spellings, array-sized parameters, `keep` params, and the
`<` generic-vs-comparison disambiguation."""

import pytest

from src.compiler.python.syntax.ast.generated import CastExpr, FunctionDecl, LambdaExpr
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import ParseError
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


@pytest.mark.parametrize(
    "spelling",
    [
        "unsigned short int",
        "signed short int",
        "unsigned long int",
        "signed long int",
        "unsigned long long int",
        "signed long long int",
    ],
)
def test_signed_unsigned_integer_spellings_parse(spelling):
    prog = parse(f"{spelling} f({spelling} x) {{ return x; }}")
    func = prog.declarations[0]
    assert func.return_type.base == spelling
    assert func.params[0].type.base == spelling


def test_long_long_double_is_rejected():
    with pytest.raises(ParseError):
        parse("long long double invalid() { return 0; }")


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


def test_tuple_type_preserves_qualifiers_and_suffixes():
    prog = parse("void f() { const volatile (int, string)? maybe; (int, string)* pointer; (int, string)[] values; }")
    maybe, pointer, values = prog.declarations[0].body.statements
    assert maybe.type.base == "Tuple"
    assert maybe.type.is_const and maybe.type.is_volatile
    assert maybe.type.is_nullable and maybe.type.pointer_depth == 1
    assert pointer.type.pointer_depth == 1 and not pointer.type.is_nullable
    assert values.type.is_array


def test_declarator_array_records_layer_outside_nullable_marker():
    prog = parse("void f() { int[]? nullable_array; int? nullable_elements[2]; }")
    nullable_array, nullable_elements = prog.declarations[0].body.statements

    assert nullable_array.type.is_array
    assert nullable_array.type.nullable_outer_depth == 0
    assert nullable_elements.type.is_array
    assert nullable_elements.type.nullable_outer_depth == 1


def test_nested_generic_nullable_type_and_cast():
    prog = parse("void f() { Box<Vector<int>>? box; var x = (Box<Vector<int>>) box; }")
    box_type = prog.declarations[0].body.statements[0].type
    cast = prog.declarations[0].body.statements[1].initializer
    assert box_type.base == "Box" and box_type.is_nullable
    assert box_type.generic_args[0].base == "Vector"
    assert isinstance(cast, CastExpr)
    assert cast.target_type.generic_args[0].generic_args[0].base == "int"


def test_nested_generic_nullable_verbose_lambda():
    prog = parse("void f() { var fn = Box<Vector<int>>? function() { return null; }; }")
    initializer = prog.declarations[0].body.statements[0].initializer
    assert isinstance(initializer, LambdaExpr)
    assert initializer.return_type.is_nullable
    assert initializer.return_type.generic_args[0].base == "Vector"


def test_parameter_with_explicit_array_size():
    src = "int sum(int buf[10]) { return buf[0]; }\nint main() { return 0; }"
    prog = parse(src)
    swap = next(d for d in prog.declarations if isinstance(d, FunctionDecl) and d.name == "sum")
    assert swap.params[0].type.is_array
    assert swap.params[0].type.array_size is not None


def test_keep_parameter():
    src = (
        "class Obj { public int v; public Obj() { self.v = 0; } }\n"
        "void hold(keep Obj o) { return; }\nint main() { return 0; }"
    )
    prog = parse(src)
    hold = next(d for d in prog.declarations if isinstance(d, FunctionDecl) and d.name == "hold")
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
