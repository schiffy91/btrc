"""Dual-frontend ownership contracts for custom property projections."""

from pathlib import Path

import pytest

from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def test_custom_property_getter_abi_is_owned_in_every_lowerer() -> None:
    repository = Path(__file__).resolve().parents[3]
    generic_python = (repository / "src/compiler/python/ir/gen/generics/user_properties.py").read_text()
    ordinary_selfhost = (repository / "src/compiler/btrc/irgen.btrc").read_text()
    generic_selfhost = (repository / "src/compiler/btrc/class_property_lowering.btrc").read_text()

    assert "emitter.reset_var_types(return_type=prop.type, return_owned=True)" in generic_python
    assert "return_owned=False" not in generic_python
    assert (
        "Custom getters are call-shaped +1 projections. */\n"
        "                self.currentReturnOwned = true;" in ordinary_selfhost
    )
    assert (
        "Custom getters are call-shaped +1 projections. */\n"
        "                    generator.currentReturnOwned = true;" in generic_selfhost
    )


def test_custom_property_getter_abi_has_no_borrowed_return_policy() -> None:
    repository = Path(__file__).resolve().parents[3]
    semantic_sources = (
        "semantic_validation_types.btrc",
        "semantic_validation_decls.btrc",
        "semantic_validation_stmts.btrc",
    )
    for name in semantic_sources:
        source = (repository / "src/compiler/btrc" / name).read_text()
        assert "borrowedReturn" not in source

    selfhost_returns = (repository / "src/compiler/btrc/ownership_returns.btrc").read_text()
    selfhost_classification = (repository / "src/compiler/btrc/ownership_classification.btrc").read_text()
    python_returns = (repository / "src/compiler/python/ir/gen/arc_returns.py").read_text()
    assert "borrowed property getter" not in selfhost_returns
    assert "irBorrowsFromManagedLocal" not in selfhost_classification
    assert "borrowed property getter" not in python_returns
    assert "_borrows_from_owned_local" not in python_returns


def _strict_dual_frontend_runtime(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    stem: str,
) -> None:
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_source = _compile_reference_source(
        tmp_path,
        source,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(
        selfhost_source,
        tmp_path / f"selfhost-{stem}",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / f"reference-{stem}",
    )


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_custom_property_getter_transfers_nested_local_owners(
    semantic_btrcc: Path,
    tmp_path: Path,
    generic: bool,
) -> None:
    parameters = "<T>" if generic else ""
    owner_type = "Owner<int>" if generic else "Owner"
    source = f"""
        #include <assert.h>

        int alive = 0;

        class Item {{
            public Item() {{ alive++; }}
            public void __del__() {{ alive--; }}
        }}

        class Owner{parameters} {{
            public Owner() {{}}

            public Item selected {{
                get {{
                    Item local = new Item();
                    return true ? local : local;
                }}
            }}

            public Item casted {{
                get {{
                    Item local = new Item();
                    return (Item)local;
                }}
            }}

            public Item assigned {{
                get {{
                    Item local = new Item();
                    return local = local;
                }}
            }}
        }}

        int main() {{
            {owner_type} owner = new {owner_type}();
            assert(alive == 0);
            {{
                Item selected = owner.selected;
                assert(selected != null && alive == 1);
            }}
            assert(alive == 0);
            {{
                Item casted = owner.casted;
                assert(casted != null && alive == 1);
            }}
            assert(alive == 0);
            {{
                Item assigned = owner.assigned;
                assert(assigned != null && alive == 1);
            }}
            assert(alive == 0);
            delete owner;
            assert(alive == 0);
            return 0;
        }}
    """
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_source = _compile_reference_source(
        tmp_path,
        source,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    toolchain = require_sanitizers(tmp_path)
    sanitized_build_and_run(
        selfhost_source,
        tmp_path / f"selfhost-nested-local-{generic}",
        toolchain,
    )
    sanitized_build_and_run(
        reference_source,
        tmp_path / f"reference-nested-local-{generic}",
        toolchain,
    )


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_custom_property_getter_owns_implicit_string_conversion(
    semantic_btrcc: Path,
    tmp_path: Path,
    generic: bool,
) -> None:
    parameters = "<T>" if generic else ""
    box_type = "Box<int>" if generic else "Box"
    source = f"""
        #include <assert.h>

        int tokensAlive = 0;

        class Token {{
            public Token() {{ tokensAlive++; }}
            public void __del__() {{ tokensAlive--; }}
            public string toString() {{ return "token"; }}
        }}

        class Box{parameters} {{
            public Box() {{}}
            public string label {{
                get {{ return new Token(); }}
            }}
        }}

        int main() {{
            {box_type} box = new {box_type}();
            {{
                string label = box.label;
                assert(label == "token");
                assert(tokensAlive == 0);
            }}
            delete box;
            assert(tokensAlive == 0);
            return 0;
        }}
    """
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_source = _compile_reference_source(
        tmp_path,
        source,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    toolchain = require_sanitizers(tmp_path)
    sanitized_build_and_run(
        selfhost_source,
        tmp_path / f"selfhost-string-conversion-{generic}",
        toolchain,
    )
    sanitized_build_and_run(
        reference_source,
        tmp_path / f"reference-string-conversion-{generic}",
        toolchain,
    )


def test_managed_custom_self_property_return_has_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int alive = 0;
        class Item {
            public Item() { alive++; }
            public void __del__() { alive--; }
        }
        class Owner {
            private Item stored;
            public Owner() { self.stored = new Item(); }
            public Item current { get { return self.stored; } }
            public Item read() { return self.current; }
        }
        int main() {
            {
                Owner owner = new Owner();
                {
                    Item item = owner.read();
                    assert(alive == 1);
                }
                assert(alive == 1);
            }
            assert(alive == 0);
            return 0;
        }
    """
    _strict_dual_frontend_runtime(
        semantic_btrcc,
        tmp_path,
        source,
        "managed-self-property",
    )


def test_generic_managed_custom_self_property_return_has_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int alive = 0;
        class Item {
            public Item() { alive++; }
            public void __del__() { alive--; }
        }
        class Owner<T> {
            private Item stored;
            public Owner() { self.stored = new Item(); }
            public Item current { get { return self.stored; } }
            public Item read() { return self.current; }
        }
        int main() {
            {
                Owner<int> owner = new Owner<int>();
                {
                    Item item = owner.read();
                    assert(alive == 1);
                }
                assert(alive == 1);
            }
            assert(alive == 0);
            return 0;
        }
    """
    _strict_dual_frontend_runtime(
        semantic_btrcc,
        tmp_path,
        source,
        "generic-managed-self-property",
    )


def test_super_properties_use_parent_accessors_with_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int alive = 0;
        class Item {
            public Item() { alive++; }
            public void __del__() { alive--; }
        }
        class BaseOwner {
            public Item stored;
            public int scalar;
            public Item current { get { return self.stored; } }
            public int answer { get { return self.scalar; } }
        }
        class ChildOwner extends BaseOwner {
            public ChildOwner() {
                self.stored = new Item();
                self.scalar = 42;
            }
            public Item readManaged() { return super.current; }
            public int readScalar() { return super.answer; }
        }
        int main() {
            {
                ChildOwner owner = new ChildOwner();
                assert(owner.readScalar() == 42);
                {
                    Item item = owner.readManaged();
                    assert(alive == 1);
                }
                assert(alive == 1);
            }
            assert(alive == 0);
            return 0;
        }
    """
    _strict_dual_frontend_runtime(
        semantic_btrcc,
        tmp_path,
        source,
        "super-properties",
    )
