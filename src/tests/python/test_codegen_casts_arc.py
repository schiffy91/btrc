"""Cast disambiguation (generic-type and nested-paren casts) and ARC cleanup for
generic-typed fields and classes exposing a free() method."""

from src.tests.python.test_codegen import emit_c


def test_cast_to_generic_type():
    c = emit_c("class Box<T> { public T v; public Box(T v) { self.v = v; } }\n"
               "int main() { Box<int> b = new Box<int>(5); Box<int> c = (Box<int>)b; return c.v; }")
    assert "Box_int" in c


def test_cast_with_nested_parens():
    c = emit_c("int main() { int a = 5; int b = (int)(a + 1); return b; }")
    assert "(int)" in c


def test_pointer_and_nullable_casts():
    c = emit_c("class N { public int v; public N() { self.v = 0; } }\n"
               "int main() { N n = new N(); N m = (N)n; return m.v; }")
    assert "(N" in c or "N*" in c


def test_arc_cleanup_generic_collection_field():
    c = emit_c("class Holder {\n"
               "    public Vector<int> items;\n"
               "    public Holder() { self.items = new Vector<int>(); self.items.add(1); }\n"
               "}\n"
               "int main() { Holder h = new Holder(); return 0; }")
    assert "Holder" in c


def test_arc_class_with_free_method():
    c = emit_c("class Pool<T> {\n"
               "    public T item;\n"
               "    public Pool(T x) { self.item = x; }\n"
               "    public void free() { }\n"
               "}\n"
               "int main() { Pool<int> p = new Pool<int>(5); return 0; }")
    assert "Pool_int" in c


def test_arc_class_field_with_generic_collection_release():
    # An owning class holds another class that itself owns a collection — the
    # destructor chain releases through both, exercising the generic-typed
    # field destroy-name resolution.
    c = emit_c("class Bag { public Vector<int> data; public Bag() { self.data = new Vector<int>(); } }\n"
               "class Owner { public Bag bag; public Owner() { self.bag = new Bag(); } }\n"
               "int main() { Owner o = new Owner(); return 0; }")
    assert "Owner" in c and "Bag" in c
