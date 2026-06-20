"""Parser coverage for declaration forms: top-level structs, classes that
implement multiple interfaces, multi-parameter generics, array-typed fields,
and `keep` on parameters and return types."""

from src.compiler.python.ast_nodes import ClassDecl, FunctionDecl, StructDecl
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def parse(src):
    return Parser(Lexer(src, "<t>").tokenize()).parse()


def test_struct_declaration():
    prog = parse("struct Point { int x; int y; };\nint main() { return 0; }")
    assert any(isinstance(d, StructDecl) for d in prog.declarations)


def test_class_implements_multiple_interfaces():
    src = """
    interface A { int a(); }
    interface B { int b(); }
    class C implements A, B {
        public int a() { return 1; }
        public int b() { return 2; }
    }
    int main() { return 0; }
    """
    prog = parse(src)
    c = next(d for d in prog.declarations if isinstance(d, ClassDecl) and d.name == "C")
    assert len(c.interfaces) == 2


def test_generic_class_multiple_type_params():
    prog = parse("class Pair<K, V> { public K k; public V v; }\nint main() { return 0; }")
    pair = next(d for d in prog.declarations if isinstance(d, ClassDecl))
    assert len(pair.generic_params) == 2


def test_struct_with_array_fields():
    # Struct fields support both sized `data[16]` and unsized `flags[]` arrays.
    src = "struct Buffer { int data[16]; int flags[]; int n; };\nint main() { return 0; }"
    prog = parse(src)
    buf = next(d for d in prog.declarations if isinstance(d, StructDecl))
    assert len(buf.fields) == 3
    assert buf.fields[0].type.is_array and buf.fields[0].type.array_size is not None
    assert buf.fields[1].type.is_array


def test_keep_parameter_in_method():
    src = ("class Obj { public int v; public Obj() { self.v = 0; } }\n"
           "class Sink { public void take(keep Obj o) { return; } }\n"
           "int main() { return 0; }")
    prog = parse(src)
    sink = next(d for d in prog.declarations if isinstance(d, ClassDecl) and d.name == "Sink")
    take = sink.members[0]
    assert take.params[0].keep is True


def test_keep_return_function():
    src = ("class Obj { public int v; public Obj() { self.v = 0; } }\n"
           "keep Obj make() { return new Obj(); }\n"
           "int main() { Obj o = make(); return 0; }")
    prog = parse(src)
    assert any(isinstance(d, FunctionDecl) and d.name == "make" for d in prog.declarations)
