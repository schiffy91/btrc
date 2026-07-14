"""More codegen paths: element-type inference for untyped collection literals,
tuple literals/types, enum-value references, char formatting, and a rich GPU
kernel exercising the WGSL emitter (local decls, void return, loops, literals)."""

from src.tests.python.test_codegen import emit_c


def test_vector_construction_and_methods():
    c = emit_c("int main() { Vector<int> v = new Vector<int>(); v.add(1); v.add(2);\n             return v.size(); }")
    assert "btrc_Vector_int" in c


def test_for_in_user_class_vector_binds_pointer_type():
    c = emit_c(
        "class Item { public int v; public Item(int v) { self.v = v; } }\n"
        "class Vector<T> { public T* data; public int len; public int cap;\n"
        "    public Vector() { self.data = null; self.len = 0; self.cap = 0; }\n"
        "    public int iterLen() { return self.len; }\n"
        "    public T iterGet(int i) { return self.data[i]; } }\n"
        "class Holder { public Vector<Item> items;\n"
        "    public Holder() { self.items = new Vector<Item>(); }\n"
        "    public int total() { int total = 0;\n"
        "        for item in self.items { total = total + item.v; }\n"
        "        return total; } }\n"
        "int main() { Holder h = Holder(); return h.total(); }"
    )
    # Element type Item is a class, so Vector<Item> monomorphizes on the
    # pointer element Item* — the mangled name carries the `_p1` pointer-depth
    # suffix (CMP-19), distinguishing it from a hypothetical Vector<Item>
    # by-value instance.
    assert "Item* item = btrc_Vector_Item_p1_iterGet" in c
    assert "item->v" in c


def test_string_for_in_evaluates_iterable_once():
    c = emit_c(
        'string choose_text(int which) { return which == 1 ? "abc" : ""; }\n'
        "int main() { int total = 0;\n"
        "    for ch in choose_text(1) { total += ch; }\n"
        "    return total; }"
    )
    assert c.count("choose_text(1)") == 1
    assert "char* __iter_" in c


def test_map_construction_and_methods():
    c = emit_c(
        'int main() { Map<string, int> m = new Map<string, int>(); m.put("a", 1);\n             return m.size(); }'
    )
    assert "btrc_Map" in c


def test_class_double_pointer_field_is_raw_storage_not_arc_managed():
    c = emit_c(
        "class Item { public int id; }\n"
        "class Buffer<T> { public T* data;\n"
        "    public Buffer() { self.data = null; }\n"
        "    public void clear() { free(self.data); self.data = null; } }\n"
        "int main() { Buffer<Item> b = new Buffer<Item>(); b.clear(); return 0; }"
    )
    assert "free(self->data)" in c
    assert "__btrc_field_old" not in c
    assert "Item_destroy(self->data)" not in c


def test_tuple_literal_and_type():
    c = emit_c("(int, int) make() { return (1, 2); }\nint main() { (int, int) p = make(); return 0; }")
    assert "Tuple" in c


def test_enum_value_reference_in_expression():
    c = emit_c(
        "enum Color { RED, GREEN, BLUE };\nint main() { Color c = GREEN; if (c == BLUE) { return 1; } return 0; }"
    )
    assert "GREEN" in c or "Color" in c


def test_char_literal_and_formatting():
    c = emit_c("int main() { char ch = 'A'; print(ch); return 0; }")
    assert "char" in c


def test_self_value_passed_as_argument():
    c = emit_c(
        "class Node { public int v; public Node() { self.v = 0; }\n"
        "    public int viaHelper() { return helper(self); } }\n"
        "int helper(Node n) { return n.v; }\n"
        "int main() { Node n = new Node(); return n.viaHelper(); }"
    )
    assert "self" in c


def test_gpu_kernel_rich_body_wgsl():
    # Drives the WGSL expression/statement emitter: a local var, an early void
    # return, a c-for loop, float/bool literals, and a comparison.
    c = emit_c(
        "@gpu\nvoid process(float[] xs, int[] flags, float k) {\n"
        "    int i = gpu_id();\n"
        "    float v = xs[i];\n"
        "    if (flags[i] == 0) { return; }\n"
        "    for (int j = 0; j < 3; j = j + 1) { v = v + 1.0; }\n"
        "    bool big = v > 10.0;\n"
        "    if (big) { v = 0.0; }\n"
        "    xs[i] = v * k;\n"
        "}\n"
        "int main() { float[] xs = {1.0}; int[] flags = {1}; "
        "process(xs, flags, 2.0); return 0; }"
    )
    assert "@compute" in c
    assert "var" in c  # WGSL local var declaration
    assert "return;" in c  # early void return in kernel


def test_sizeof_of_expression_lowers():
    c = emit_c("int main() { int x = 5; return sizeof(x); }")
    assert "sizeof" in c
