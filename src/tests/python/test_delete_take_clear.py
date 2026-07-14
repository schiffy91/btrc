"""Structured IR contracts for terminal deletion."""

from src.tests.python.test_codegen import emit_c


def test_delete_clears_saved_class_slot_before_destroy() -> None:
    generated = emit_c("class Item {} int main() { Item value = new Item(); delete value; return 0; }")
    main = generated[generated.rindex("int main(") :]
    saved = main.index("__btrc_delete_value")
    clear = main.index(" = NULL;", saved)
    destroy = main.index("__btrc_arc_destroy(", clear)
    assert saved < clear < destroy


def test_generic_class_and_raw_delete_use_the_shared_boundary() -> None:
    generated = emit_c(
        "class Item {} "
        "class Drop<T> { "
        "  public void dropNull() { Item value = (Item)null; delete value; } "
        "} "
        "int main() { "
        "  int* raw = null; delete raw; "
        "  Drop<string> drop = new Drop<string>(); drop.dropNull(); "
        "  return 0; "
        "}"
    )
    assert generated.count("__btrc_delete_slot") >= 2
    assert "__btrc_arc_destroy(__btrc_delete_value" in generated
    assert "free(__btrc_delete_value" in generated
