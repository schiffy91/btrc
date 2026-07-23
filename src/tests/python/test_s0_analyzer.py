"""S0 analyzer bug regression tests.

Covers: declaration-order-independent inheritance (S0-9), lambda capture of
variables used only inside try/catch (S0-10), setjmp.h include for try/catch
inside lambdas (S0-10b), unknown cast target diagnostics (S0-1b), and
linear-time, recursion-safe analysis of long binary chains (S0-14).
"""

import time

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ir.gen.lowerer import IRLowerer
from src.compiler.python.ir.nodes import IRInclude
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def parse(source: str):
    return Parser(Lexer(source).tokenize()).parse()


def analyze(source: str):
    program = parse(source)
    return SemanticAnalyzer().analyze(program), program


# --- S0-9: child class declared before its parent ---


class TestInheritanceDeclarationOrder:
    CHILD_FIRST = """
        class Child extends Parent {
            public int childOnly;
        }
        class Parent {
            public int px;
            public int getPx() { return self.px; }
        }
    """

    PARENT_FIRST = """
        class Parent {
            public int px;
            public int getPx() { return self.px; }
        }
        class Child extends Parent {
            public int childOnly;
        }
    """

    def test_child_first_inherits_fields_and_methods(self):
        an, _ = analyze(self.CHILD_FIRST)
        child = an.class_table["Child"]
        assert "px" in child.fields
        assert "getPx" in child.methods
        assert "childOnly" in child.fields

    def test_child_first_matches_parent_first(self):
        an1, _ = analyze(self.CHILD_FIRST)
        an2, _ = analyze(self.PARENT_FIRST)
        c1 = an1.class_table["Child"]
        c2 = an2.class_table["Child"]
        assert list(c1.fields.keys()) == list(c2.fields.keys())
        assert list(c1.methods.keys()) == list(c2.methods.keys())

    def test_parent_fields_come_first_in_layout(self):
        # Struct layout contract: inherited fields precede own fields.
        an, _ = analyze(self.CHILD_FIRST)
        assert list(an.class_table["Child"].fields.keys()) == ["px", "childOnly"]

    def test_three_level_chain_any_order(self):
        src = """
            class C extends B { public int c; }
            class A { public int a; }
            class B extends A { public int b; }
        """
        an, _ = analyze(src)
        assert list(an.class_table["C"].fields.keys()) == ["a", "b", "c"]

    def test_field_use_in_child_first_program(self):
        src = """
            class Dog extends Animal {
                public void speak() { print(self.name); }
            }
            class Animal { public string name; }
        """
        an, _ = analyze(src)
        assert an.errors == []

    def test_missing_parent_still_errors(self):
        an, _ = analyze("class Child extends Nope { public int x; }")
        assert any("Nope" in e for e in an.errors)

    def test_inheritance_cycle_does_not_hang(self):
        src = """
            class A extends B { public int a; }
            class B extends A { public int b; }
        """
        an, _ = analyze(src)
        assert any("Circular inheritance" in e for e in an.errors)

    def test_constructor_not_inherited(self):
        src = """
            class Child extends Parent { public int y; }
            class Parent {
                public int x;
                public Parent(int x) { self.x = x; }
            }
        """
        an, _ = analyze(src)
        child = an.class_table["Child"]
        assert child.constructor is None
        assert "Parent" not in child.methods


# --- S0-10: lambda captures variables used only inside try/catch ---


class TestLambdaCaptureTryCatch:
    def test_capture_inside_try_block(self):
        src = """
            void f() {
                int outer = 42;
                var fn = () => {
                    try { print(outer); } catch (e) { }
                    return 0;
                };
            }
        """
        _, prog = analyze(src)
        lam = prog.declarations[0].body.statements[1].initializer
        assert [c.name for c in lam.captures] == ["outer"]

    def test_capture_inside_catch_and_finally(self):
        src = """
            void f() {
                int a = 1;
                int b = 2;
                var fn = () => {
                    try { } catch (e) { print(a); } finally { print(b); }
                    return 0;
                };
            }
        """
        _, prog = analyze(src)
        lam = prog.declarations[0].body.statements[2].initializer
        assert [c.name for c in lam.captures] == ["a", "b"]

    def test_params_and_locals_still_excluded(self):
        src = """
            void f() {
                int outer = 1;
                var fn = (int p) => {
                    int local = p + outer;
                    try { print(local); } catch (e) { }
                    return local;
                };
            }
        """
        _, prog = analyze(src)
        lam = prog.declarations[0].body.statements[1].initializer
        assert [c.name for c in lam.captures] == ["outer"]

    def test_plain_capture_unchanged(self):
        src = """
            void f() {
                int x = 7;
                var fn = () => { return x + 1; };
            }
        """
        _, prog = analyze(src)
        lam = prog.declarations[0].body.statements[1].initializer
        assert [c.name for c in lam.captures] == ["x"]


# --- S0-10b: setjmp.h registered from the try/catch lowering site ---


class TestSetjmpInclude:
    def _includes_for(self, src):
        program = parse(src)
        analyzed = SemanticAnalyzer().analyze(program)
        return [
            declaration.header
            for declaration in IRLowerer(analyzed).lower().preprocessor_decls
            if isinstance(declaration, IRInclude)
        ]

    def test_try_inside_lambda_includes_setjmp(self):
        src = """
            void f() {
                var fn = () => {
                    try { print(1); } catch (e) { }
                    return 0;
                };
            }
        """
        assert "setjmp.h" in self._includes_for(src)

    def test_throw_inside_lambda_includes_setjmp(self):
        src = """
            void f() {
                var fn = () => {
                    throw "bad";
                    return 0;
                };
            }
        """
        assert "setjmp.h" in self._includes_for(src)

    def test_top_level_try_includes_setjmp_once(self):
        src = "void f() { try { print(1); } catch (e) { } }"
        includes = self._includes_for(src)
        assert includes.count("setjmp.h") == 1

    def test_no_trycatch_no_setjmp(self):
        assert "setjmp.h" not in self._includes_for("void f() { print(1); }")


# --- S0-1b: unknown single-IDENT cast targets are diagnosed ---


class TestUnknownCastTarget:
    def test_unknown_ident_cast_is_error(self):
        an, _ = analyze("void f(int a) { var x = (Bogus) a; }")
        assert any("Bogus" in e for e in an.errors)

    def test_known_class_cast_ok(self):
        src = """
            class Foo { public int x; }
            void f(Foo p) { var x = (Foo) p; }
        """
        an, _ = analyze(src)
        assert an.errors == []

    def test_enum_cast_ok(self):
        src = """
            enum Color { RED, GREEN };
            void f(int a) { var x = (Color) a; }
        """
        an, _ = analyze(src)
        assert an.errors == []

    def test_struct_cast_ok(self):
        src = """
            struct Point { int x; int y; };
            void f(Point p) { var q = (Point) p; }
        """
        an, _ = analyze(src)
        assert an.errors == []

    def test_typedef_cast_ok(self):
        src = """
            typedef unsigned int UnsignedAlias;
            void f(int a) { var x = (UnsignedAlias) a; }
        """
        an, _ = analyze(src)
        assert an.errors == []

    def test_generic_param_cast_ok(self):
        src = """
            class Box<T> {
                public T val;
                public T as(T v) { return (T) v; }
            }
        """
        an, _ = analyze(src)
        assert an.errors == []

    def test_pointer_cast_to_unknown_requires_portable_integer_carrier(self):
        # Strict C requires integer/pointer round-trips through intptr_t or
        # uintptr_t even when the pointee names an opaque hosted type.
        an, _ = analyze("void f(int a) { var x = (FILE*) a; }")
        assert any("Pointer/integer casts require intptr_t or uintptr_t" in error for error in an.errors)


# --- S0-14: long binary chains — linear time, no RecursionError ---


class TestLongBinaryChains:
    @staticmethod
    def _chain(n):
        return "int f(int a) { return " + "+".join(["a"] * n) + "; }"

    def test_no_recursion_error_at_5000_terms(self):
        an, _ = analyze(self._chain(5000))
        assert an.errors == []

    def test_2000_terms_under_one_second(self):
        program = parse(self._chain(2000))
        start = time.time()
        SemanticAnalyzer().analyze(program)
        assert time.time() - start < 1.0

    def test_node_types_still_recorded(self):
        src = "int f(int a, float b) { return a + a; }"
        an, prog = analyze(src)
        ret = prog.declarations[0].body.statements[0]
        t = an.node_types.get(id(ret.value))
        assert t is not None and t.base == "int"

    def test_mixed_type_inference_unchanged(self):
        src = """
            void f(int a, float b) {
                var x = a + b;
                var y = a + a;
            }
        """
        an, prog = analyze(src)
        x_init = prog.declarations[0].body.statements[0].initializer
        y_init = prog.declarations[0].body.statements[1].initializer
        assert an.node_types[id(x_init)].base == "float"
        assert an.node_types[id(y_init)].base == "int"
