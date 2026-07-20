"""Structured IR contracts for terminal deletion."""

from src.tests.python.test_codegen import emit_c


def test_delete_clears_saved_class_slot_before_destroy() -> None:
    generated = emit_c("class Item {} int main() { Item value = new Item(); delete value; return 0; }")
    main = generated[generated.rindex("int main(") :]
    slot = main.index("Item* volatile* __btrc_delete_slot")
    destroy = main.index("__btrc_arc_destroy_slot(", slot)
    assert slot < destroy
    assert "__btrc_arc_slot_access_" in main[destroy : destroy + 300]
    assert "Item* volatile* typed_slot" in generated
    assert "(*typed_slot) = ((Item*)replacement);" in generated


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
    assert "__btrc_arc_destroy_slot(((volatile void*)__btrc_delete_slot" in generated
    assert "__btrc_arc_slot_access_" in generated
    assert "free(__btrc_delete_value" in generated
    assert "__btrc_arc_destroy(" not in generated
