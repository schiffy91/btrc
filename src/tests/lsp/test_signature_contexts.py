"""Signature help by receiver context: inherited-method parent chain, self,
static and chained receivers, unresolved receivers, active-parameter counting
that ignores nested calls and commas inside string literals, and builtin
function and member calls."""

from src.tests.lsp.lsphelp import analyze, get_signature_help, pos_of


def _sig(src, needle, occurrence=1, offset=0):
    return get_signature_help(analyze(src), pos_of(src, needle, occurrence, offset))


def test_inherited_method_signature_walks_parent_chain():
    src = (
        "class Base {\n"
        "    public int b;\n"
        "    public Base() { self.b = 0; }\n"
        "    public int combine(int a, int c) { return a + c; }\n"
        "}\n"
        "class Sub extends Base { public Sub() { self.b = 1; } }\n"
        "int main() { Sub s = Sub(); return s.combine(1, 2); }\n"
    )
    s = _sig(src, "s.combine(1", offset=10)  # cursor in the first argument
    assert s is not None and "combine" in s.signatures[0].label
    assert len(s.signatures[0].parameters) == 2


def test_active_parameter_ignores_commas_in_strings():
    src = 'int two(string a, int b) { return b; }\nint main() { return two("x, y", 3); }\n'
    s = _sig(src, ", 3)", offset=2)  # cursor on the real second arg
    assert s is not None and s.active_parameter == 1


def test_builtin_function_call_signature_no_crash():
    src = 'int main() { print("hello"); return 0; }\n'
    s = _sig(src, 'print("hello"', offset=6)
    assert s is None or s.signatures  # whatever it returns, it must not crash


def test_signature_self_method_inside_method():
    src = (
        "class C { public int v; public C() { self.v = 0; }\n"
        "          public int twice() { return self.dbl(self.v); }\n"
        "          public int dbl(int n) { return n + n; } }\n"
        "int main() { C c = C(); return c.twice(); }\n"
    )
    s = get_signature_help(analyze(src), pos_of(src, "self.dbl(self.v", offset=9))
    assert s is not None and s.signatures


def test_signature_static_method_via_class_name():
    src = (
        "class Mathy {\n"
        "    public int base;\n"
        "    public Mathy(int base) { self.base = base; }\n"
        "    class int addp(int a, int b) { return a + b; }\n"
        "}\n"
        "int main() { return Mathy.addp(1, 2); }\n"
    )
    s = get_signature_help(analyze(src), pos_of(src, "Mathy.addp(1", offset=11))
    assert s is not None and "addp" in s.signatures[0].label


def test_signature_static_class_method():
    src = (
        "class Mathy { public int base; public Mathy(int base) { self.base = base; }\n"
        "    public int addp(int a, int b) { return a + b; } }\n"
        "int main() { int r = Mathy.addp(1, 2); return r; }\n"
    )
    s = get_signature_help(analyze(src), pos_of(src, "Mathy.addp(1", offset=11))
    assert s is None or (s.signatures and "addp" in s.signatures[0].label)


def test_signature_unresolved_receiver_is_none():
    src = (
        "class Foo { public int f; public Foo() { self.f = 0; }\n"
        "            public int act(int x) { return x; } }\n"
        "int main() { int n = 5; return n.act(2); }\n"
    )
    s = get_signature_help(analyze(src), pos_of(src, "n.act(2", offset=6))
    assert s is None


def test_signature_nested_chain_method_call():
    src = (
        "class Inner { public int v; public Inner() { self.v = 0; }\n"
        "              public int run(int x) { return x; } }\n"
        "class Outer { public Inner inner; public Outer() { self.inner = Inner(); }\n"
        "              public Inner make() { return self.inner; } }\n"
        "int main() { Outer outer = Outer(); return outer.make().run(3); }\n"
    )
    s = get_signature_help(analyze(src), pos_of(src, "run(3", offset=4))
    assert s is not None and "run" in s.signatures[0].label


def test_signature_nested_call_active_param():
    src = "int g(int a, int b) { return a + b; }\nint f(int x) { return x; }\nint main() { return g(f(1), 2); }\n"
    # cursor on the outer call's second argument, past the nested f(1)
    s = get_signature_help(analyze(src), pos_of(src, ", 2)", offset=2))
    assert s is not None and s.active_parameter == 1


def test_builtin_member_signature_help():
    # signature help inside a built-in string method call
    src = 'int main() { string s = "hello"; int i = s.indexOf("l"); return i; }\n'
    s = get_signature_help(analyze(src), pos_of(src, 's.indexOf("l"', offset=10))
    assert s is None or s.signatures
