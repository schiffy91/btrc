"""Feature-dense transpile tests. Each program exercises many codegen paths at
once (operators, casts, inheritance/dispatch, ARC, collections, lambdas with
captures, arrays) so coverage is broad; assertions check concrete emitted C.
"""

import re

from src.compiler.python.tests.test_codegen import emit_c


def test_inheritance_override_and_upcast():
    src = """
    class Animal { public int legs; public Animal() { self.legs = 4; }
        public int speak() { return 0; } }
    class Dog extends Animal {
        public Dog() { self.legs = 4; }
        public int speak() { return 1; }
    }
    int main() {
        Animal a = new Dog();        // upcast: Dog* -> Animal*
        Dog d = new Dog();
        return a.speak() + d.speak();
    }
    """
    c = emit_c(src)
    assert "Dog" in c and "Animal" in c
    assert "(Animal*)" in c or "(struct Animal*)" in c        # explicit upcast


def test_all_operators():
    src = """
    int main() {
        int a = 6 & 3; int b = 6 | 1; int c = 6 ^ 2;
        int d = 1 << 3; int e = 16 >> 2; int f = ~5;
        int g = -a; bool h = !(a == b);
        int t = (a > b) ? a : b;
        int m = 17 % 5;
        return a + b + c + d + e + f + g + (h ? 1 : 0) + t + m;
    }
    """
    c = emit_c(src)
    for op in ["&", "|", "^", "<<", ">>", "~", "%", "?"]:
        assert op in c, f"missing operator {op}"


def test_compound_assignment_operators():
    src = "int main() { int x = 20; x += 5; x -= 3; x *= 2; x /= 4; x %= 5; return x; }"
    c = emit_c(src)
    assert "+=" in c and "-=" in c and "*=" in c and "/=" in c and "%=" in c


def test_casts_and_numeric_types():
    src = """
    int main() {
        double d = 3.99;
        int i = (int)d;
        long l = (long)i;
        float f = (float)l;
        char ch = (char)65;
        unsigned u = (unsigned)i;
        return i + ch;
    }
    """
    c = emit_c(src)
    assert "(int)" in c and "(long)" in c and "(float)" in c


def test_nullable_and_null_checks():
    src = """
    class N { public int v; public N() { self.v = 7; } }
    int main() {
        N? n = null;
        if (n == null) { return 0; }
        return n.v;
    }
    """
    c = emit_c(src)
    assert "NULL" in c


def test_array_aggregate_initializer():
    src = "int main() { int[] arr = {10, 20, 30}; int[] empty; return arr[1]; }"
    c = emit_c(src)
    assert re.search(r"int arr\[\]\s*=\s*\{", c), c            # C aggregate init


def test_lambda_with_capture_allocates_env():
    src = """
    int main() {
        int base = 100;
        int scale = 2;
        var f = (int x) => x * scale + base;
        return f(5);
    }
    """
    c = emit_c(src)
    assert "_env" in c                                          # capture env struct


def test_collections_list_map_set_methods():
    src = """
    int main() {
        List<int> xs = {1, 2, 3};
        xs.add(4);
        int n = xs.size();
        Map<string, int> m = {"a": 1};
        m.put("b", 2);
        Set<int> s = {5, 6};
        s.add(7);
        return n + m.size() + s.size();
    }
    """
    c = emit_c(src)
    assert "List" in c and "Map" in c and "Set" in c


def test_arc_early_return_with_managed_local():
    src = """
    class Obj { public int v; public Obj() { self.v = 0; } public int get() { return self.v; } }
    int pick(int flag) {
        Obj a = new Obj();
        Obj b = new Obj();
        if (flag > 0) { return a.get(); }     // b released, a returned-through
        return b.get();
    }
    int main() { return pick(1); }
    """
    c = emit_c(src)
    assert "__btrc_ret" in c or "__rc" in c                    # temp + release ordering


def test_while_with_break_and_continue():
    src = """
    int main() {
        int i = 0; int s = 0;
        while (true) {
            i += 1;
            if (i > 10) { break; }
            if (i % 2 == 0) { continue; }
            s += i;
        }
        return s;
    }
    """
    c = emit_c(src)
    assert "break" in c and "continue" in c and "while" in c


def test_string_methods_and_fstring():
    src = """
    int main() {
        string s = "Hello, World";
        int n = s.length();
        bool h = s.startsWith("Hello");
        string up = s.toUpper();
        int x = 42;
        string msg = f"{up} has {n} chars, x={x}";
        print(msg);
        return n + (h ? 1 : 0);
    }
    """
    c = emit_c(src)
    assert "snprintf" in c or "strlen" in c
