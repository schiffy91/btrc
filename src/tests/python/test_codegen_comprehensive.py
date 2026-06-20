"""Feature-dense programs that drive many emitter / generic-emitter / WGSL lines
in a single transpile each: vtables + globals + structs + try/catch + nested
blocks + GPU kernels; a generic class touching every statement/expression form;
and a rich GPU kernel for the WGSL expression emitter."""

from src.tests.python.test_codegen import emit_c


def test_emitter_vtables_globals_structs_trycatch_blocks():
    src = """
    int g_count = 0;
    struct Pt { int x; int y; };
    class Base { public int v; public Base() { self.v = 0; } public int f() { return 1; } }
    class Derived extends Base { public Derived() { self.v = 0; } public int f() { return 2; } }
    @gpu void clear(float[] xs) { int i = gpu_id(); xs[i] = 0.0; }
    int compute() {
        Base b = new Derived();
        int s = 0;
        for (int i = 0; i < 3; i = i + 1) {
            { int nested = i * 2; s = s + nested; }
        }
        try { throw "x"; } catch (string e) { s = s + 9; }
        return b.f() + s;
    }
    int main() { g_count = compute(); return g_count; }
    """
    c = emit_c(src)
    assert "g_count" in c                       # global emitted
    assert "Derived" in c and "Base" in c       # inheritance / vtable


def test_generic_class_every_construct():
    src = """
    class Item { public int v; public Item() { self.v = 0; } }
    class Container<T> {
        public T value;
        public List<int> nums;
        public Map<string, int> table;
        public Item owned;
        public Container(T v) {
            self.value = v;
            self.nums = {1, 2, 3};
            self.table = {"a": 1};
            self.owned = new Item();
        }
        public void __del__() { }
        public int process(int n) {
            int total = 0;
            int sz = sizeof(total);
            for i in range(n) { total = total + i; }
            for j in range(0, n) { total = total + j; }
            for (int k = 0; k < n; k = k + 1) { total = total + k; }
            int m = 0;
            for (m = 0; m < n; m = m + 1) { total = total + m; }
            if (total > 100) { total = 100; }
            else if (total < 0) { total = 0; }
            else { total = total + 1; }
            while (total > 200) { total = total - 1; }
            return total + sz;
        }
    }
    int main() {
        Container<int> c = new Container<int>(5);
        return c.process(4);
    }
    """
    c = emit_c(src)
    assert "Container_int" in c


def test_gpu_kernel_all_wgsl_expression_forms():
    src = """
    @gpu
    void transform(float[] xs, int[] ks, float scale) {
        int i = gpu_id();
        float v = xs[i];
        int count = ks[i];
        for (int j = 0; j < count; j = j + 1) { v = v + 1.0; }
        bool big = v > 10.0;
        if (big) { v = -v; }
        else { v = v * scale; }
        xs[i] = v;
    }
    int main() { return 0; }
    """
    c = emit_c(src)
    assert "@compute" in c
    assert "var" in c            # WGSL local declaration


def test_inferred_collection_and_mutex_types():
    # Inference contexts for Map / Mutex element types.
    src = """
    int main() {
        Map<string, int> m = new Map<string, int>();
        m.put("k", 1);
        Mutex<int> mu = new Mutex<int>(0);
        mu.set(m.get("k"));
        return mu.get();
    }
    """
    c = emit_c(src)
    assert "Map" in c and "mutex" in c.lower()
