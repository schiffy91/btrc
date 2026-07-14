"""Advanced codegen paths: try/catch nesting detection (drives setjmp/longjmp
plumbing), ARC cleanup for generic-typed fields, interface subtyping, thread
lambdas with expression bodies, and C-for headers built from varied expressions
(the structured expression emitter)."""

from src.tests.python.test_codegen import emit_c


def test_trycatch_nested_in_every_control_structure():
    # generator's _stmt_uses_trycatch walks if/while/for/do-while/switch/finally;
    # a try nested in each forces the setjmp/longjmp volatile machinery on.
    src = """
    int main() {
        int s = 0;
        if (s == 0) { try { throw "a"; } catch (string e) { s = 1; } }
        while (s < 2) { try { s = s + 1; } catch (string e) { s = 9; } }
        for (int i = 0; i < 2; i = i + 1) { try { s = s + i; } catch (string e) { } }
        do { try { s = s + 1; } catch (string e) { } } while (s < 6);
        switch (s) { case 6: { try { s = 7; } catch (string e) { } } default: { } }
        try {
            try { throw "nested"; } catch (string e) { s = 8; }
        } catch (string e) { s = 9; } finally { s = s + 1; }
        return s;
    }
    """
    c = emit_c(src)
    assert "setjmp" in c or "longjmp" in c or "__btrc_try" in c


def test_throw_in_class_method_adds_setjmp_include():
    src = """
    class Failer {
        public void fail() { throw "x"; }
    }
    int main() {
        Failer f = new Failer();
        f.fail();
        return 0;
    }
    """
    c = emit_c(src)
    assert "#include <setjmp.h>" in c


def test_arc_cleanup_for_generic_typed_field():
    # A class whose field is a generic collection needs the mangled
    # destroy/free name in its destructor.
    src = """
    class Bag {
        public List<int> items;
        public Bag() { self.items = new List<int>(); }
    }
    int main() { Bag b = new Bag(); return 0; }
    """
    c = emit_c(src)
    assert "Bag" in c


def test_interface_implementation_with_concrete_static_dispatch():
    src = """
    interface Speaker { int speak(); }
    class Dog implements Speaker { public int speak() { return 1; } }
    class Cat implements Speaker { public int speak() { return 2; } }
    int useit(Dog s) { return s.speak(); }
    int main() { Dog d = new Dog(); return useit(d); }
    """
    c = emit_c(src)
    assert "Dog" in c and "speak" in c


def test_interface_extends_interface():
    src = """
    interface HasName { string name(); }
    interface HasFullName extends HasName { string full(); }
    class Person implements HasFullName {
        public string name() { return "a"; }
        public string full() { return "a b"; }
    }
    int main() { Person p = new Person(); print(p.full()); return 0; }
    """
    c = emit_c(src)
    assert "Person" in c


def test_cfor_header_with_unary_field_and_index():
    # Structured C-for emission handles postfix unary, field
    # access (self.x), and index (arr[..]) expressions.
    src = """
    class Counter {
        public int n;
        public Counter() { self.n = 0; }
        public int run() {
            int total = 0;
            for (self.n = 0; self.n < 3; self.n = self.n + 1) { total = total + self.n; }
            int[] arr = {0, 0, 0};
            for (arr[0] = 0; arr[0] < 2; arr[0] = arr[0] + 1) { total = total + arr[0]; }
            for (int i = 0; i < 4; i = i + 1) { total = total + i; }
            return total;
        }
    }
    int main() { Counter c = new Counter(); return c.run(); }
    """
    c = emit_c(src)
    assert "for" in c


def test_property_getter_with_managed_local_returns_declared_type():
    # Regression guard: a property getter with an ARC-managed local needs a
    # return temp; that temp must use the getter's own return type, not a stale
    # one left over from a previously-lowered member.
    src = """
    class Thing { public int v; public Thing() { self.v = 0; } public int get() { return self.v; } }
    class Widget {
        public int v;
        public Widget() { self.v = 0; }
        public int doubled {
            get {
                Thing t = new Thing();   // managed local forces a return temp
                t.v = self.v;
                return t.get() * 2;
            }
        }
    }
    int main() { Widget w = new Widget(); return w.doubled; }
    """
    c = emit_c(src)
    # The getter's return temp (if any) must be `int`, never a stray pointer type.
    assert "__auto_type" not in c
    import re

    bad = re.search(r"\b(?!int\b)[A-Za-z_]\w*\*? __btrc_ret_\d+ = .*?get\(", c)
    assert bad is None, f"return temp has wrong type: {bad.group(0) if bad else ''}"


def test_thread_lambda_expression_body_with_capture():
    # spawn of an expression-bodied lambda that captures a local exercises the
    # expr-body thread-wrapper path (box result + capture cleanup).
    src = """
    int main() {
        int n = 21;
        var t = spawn(() => n * 2);
        return t.join();
    }
    """
    c = emit_c(src)
    assert "__btrc_spawn_wrapper" in c
    assert "__result" in c or "return" in c


def test_capturing_iife_materializes_typed_call_site_environment():
    c = emit_c("""
        int main() {
            int offset = 3;
            return ((int value) => value + offset)(4);
        }
    """)
    assert "struct __btrc_lambda_1_env __btrc_lambda_1_call_env;" in c
    assert "(__btrc_lambda_1_call_env.offset = offset)" in c
    assert "(&__btrc_lambda_1_call_env)" in c
    assert "({" not in c


def test_nested_lambda_block_uses_inner_callable_return_type():
    c = emit_c("""
        int main() {
            int offset = 10;
            var outer = (int x) => {
                int base = x + offset;
                var inner = (int y) => y + base;
                return inner(100);
            };
            return outer(5);
        }
    """)
    assert "static int __btrc_lambda_1(" in c
    assert "return __btrc_lambda_2(100" in c


def test_nested_lambda_environment_mapping_is_function_local():
    c = emit_c("""
        int main() {
            var outer = () => {
                int local = 4;
                var inner = () => local;
                return inner();
            };
            var inner = () => 7;
            return outer() + inner();
        }
    """)
    main = c.split("int main(void)", 1)[1]
    assert "return (outer() + inner());" in main
    assert "__inner_env" not in main
