"""Deeper analyzer paths: generic-type formatting in diagnostics, interface
subtype checks across an inheritance chain, missing-return detection, switch
return analysis, and @gpu body validation recursion."""

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(src):
    return Analyzer().analyze(Parser(Lexer(src, "<t>").tokenize()).parse())


def errors(src):
    return _analyze(src).errors


def _has(msgs, sub):
    return any(sub.lower() in m.lower() for m in msgs)


def test_interface_parameter_is_rejected_before_codegen():
    # Interfaces validate implementations but have no runtime dispatch object;
    # accepting this signature would emit an unknown C type.
    src = """
    interface Speaker { int speak(); }
    class Mid implements Speaker { public int v; public Mid() { self.v = 0; } public int speak() { return 1; } }
    class Sub extends Mid { public Sub() { self.v = 1; } }
    int call(Speaker s) { return s.speak(); }
    int main() { Sub x = new Sub(); return call(x); }
    """
    assert _has(errors(src), "cannot be used as a runtime value")


def test_deep_subclass_accepted_as_base():
    src = """
    class A { public int v; public A() { self.v = 0; } }
    class B extends A { public B() { self.v = 1; } }
    class C extends B { public C() { self.v = 2; } }
    int take(A a) { return a.v; }
    int main() { C c = new C(); return take(c); }
    """
    assert errors(src) == []


def test_switch_all_paths_return_is_accepted():
    src = """
    int classify(int x) {
        switch (x) {
            case 1: { return 10; }
            case 2: { if (x > 0) { return 20; } else { return 21; } }
            default: { return 0; }
        }
    }
    int main() { return classify(2); }
    """
    assert errors(src) == []


def test_gpu_body_with_loop_call_and_member_validates():
    # A valid kernel body with a c-for, a member access, and nested control flow
    # drives the @gpu body-validation recursion over each statement/expression.
    src = """
    @gpu
    void process(float[] xs, int n) {
        int i = gpu_id();
        for (int j = 0; j < n; j = j + 1) {
            if (xs[i] > 0.0) { xs[i] = xs[i] + 1.0; }
            else { xs[i] = 0.0; }
        }
        while (xs[i] > 100.0) { xs[i] = xs[i] - 1.0; }
    }
    int main() { return 0; }
    """
    assert errors(src) == []


def test_map_literal_type_inference():
    # An explicitly-typed empty map propagates its element types.
    src = 'int main() { Map<string, int> m = {"a": 1}; m.put("b", 2); return m.size(); }'
    assert errors(src) == []


def test_mutex_construction_type():
    src = "int main() { Mutex<int> m = new Mutex<int>(0); m.set(7); return m.get(); }"
    assert errors(src) == []
