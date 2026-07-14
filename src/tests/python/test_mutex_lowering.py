"""Focused typed-box, lifetime-domain, and helper-DCE Mutex contracts."""

from src.tests.python.test_codegen import emit_c


def test_plain_mutex_omits_managed_lifetime_domains():
    generated = emit_c("""
        int main() {
            Mutex<int> value = Mutex(1);
            value.set(2);
            int result = value.get();
            value.destroy();
            return result;
        }
    """)

    assert "__btrc_mutex_val_create" in generated
    assert "__btrc_mutex_arc_retain" not in generated
    assert "__btrc_mutex_string_retain" not in generated
    assert "__btrc_arc_retain(" not in generated
    assert "__btrc_string_registry" not in generated


def test_mutex_selects_exact_managed_lifetime_callback_domain():
    class_generated = emit_c("""
        class Box { public Box() {} }
        int main() {
            Box item = new Box();
            Mutex<Box> value = Mutex(item);
            value.destroy();
            release item;
            return 0;
        }
    """)
    string_generated = emit_c("""
        int main() {
            Mutex<string> value = Mutex("literal");
            value.destroy();
            return 0;
        }
    """)

    assert "static void __btrc_mutex_arc_retain(" in class_generated
    assert "static void __btrc_mutex_arc_release(" in class_generated
    assert "__btrc_mutex_string_retain" not in class_generated
    assert "static void __btrc_mutex_string_retain(" in string_generated
    assert "static void __btrc_mutex_string_release(" in string_generated
    assert "__btrc_mutex_arc_retain" not in string_generated


def test_mutex_evaluates_initializer_before_transport_allocation():
    generated = emit_c("""
        int nextValue() { return 7; }
        int main() {
            Mutex<int> value = Mutex(nextValue());
            value.destroy();
            return 0;
        }
    """)
    initializer = next(line for line in generated.splitlines() if "__btrc_mutex_val_t* value =" in line)

    assert initializer.index("nextValue()") < initializer.index("__btrc_safe_realloc")


def test_mutex_destroy_consumes_an_addressable_handle():
    generated = emit_c("""
        int main() {
            Mutex<int> value = Mutex(1);
            value.destroy();
            return 0;
        }
    """)

    destroy = next(
        line
        for line in generated.splitlines()
        if "__btrc_mutex_val_destroy(" in line and "__btrc_mutex_val_take(" in line
    )
    assert "__btrc_mutex_val_take((&value))" in destroy
