"""Codegen for generic methods through the ordinary AST→IR lowering stack.

Immutable specialization views feed the same function, statement, expression,
call, storage, and ownership owners used by non-generic declarations.
"""

import re

from src.tests.python.test_codegen import emit_c


def test_generic_method_all_control_flow():
    src = """
    class Util<T> {
        public T val;
        public Util(T v) { self.val = v; }
        public int control(int n) {
            int s = 0;
            int u;                              // declaration without initializer
            for i in range(n) { s = s + i; }    // range(end)
            for j in range(0, n) { s = s + j; } // range(start, end)
            for (int k = 0; k < n; k = k + 1) { s = s + k; }   // c-for, decl init
            int m = 0;
            for (m = 0; m < n; m = m + 1) { s = s + m; }       // c-for, expr init
            if (s > 50) { s = s + 1; }
            else if (s < 0) { s = s - 1; }      // else-if chain
            else { s = s; }
            while (s > 100) { s = s - 10; }
            do { s = s + 1; } while (s < 3);
            return s + u - u;
        }
    }
    int main() { Util<int> a = new Util<int>(3); return a.control(5); }
    """
    c = emit_c(src)
    assert re.search(r"Util_int", c), c


def test_generic_method_with_managed_local_and_delete():
    # A class-typed local inside a generic method exercises the keep/release/
    # delete lowering in the generic statement emitter.
    src = """
    class Res { public int v; public Res() { self.v = 0; } }
    class Holder<T> {
        public T val;
        public Holder(T v) { self.val = v; }
        public int work() {
            Res r = new Res();
            r.v = 5;
            int out = r.v;
            delete r;
            return out;
        }
    }
    int main() { Holder<int> h = new Holder<int>(1); return h.work(); }
    """
    c = emit_c(src)
    assert "Holder_int" in c


def test_generic_collection_indexes_self_data():
    # A Vector-like generic that indexes its own backing store resolves the
    # element type T via self.data[...] in the generic emitter.
    src = """
    class Vec<T> {
        public T[] data;
        public int count;
        public Vec() { self.count = 0; }
        public T at(int i) { return self.data[i]; }
        public int len() { return self.count; }
    }
    int main() { Vec<int> v = new Vec<int>(); return v.len(); }
    """
    c = emit_c(src)
    assert "Vec_int" in c


def test_generic_typed_collection_literal_in_method():
    src = """
    class Builder<T> {
        public T seed;
        public Builder(T s) { self.seed = s; }
        public int sum() {
            List<int> xs = {1, 2, 3};
            int total = 0;
            for x in xs { total = total + x; }
            return total;
        }
    }
    int main() { Builder<int> b = new Builder<int>(0); return b.sum(); }
    """
    c = emit_c(src)
    assert "Builder_int" in c
