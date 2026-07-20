"""Source bindings and generated C type identifiers use distinct namespaces."""

from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import run_strict_pair
from src.tests.btrc.string_coercion_harness import compile_pair

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


SCOPE_SHADOW_SOURCES = (
    pytest.param(
        """
            class Item {
                class int marker() { return 42; }
            }

            int main() {
                bool valid = true;
                {
                    int Item = Item.marker();
                    valid = valid && Item == 42;
                }
                valid = valid && Item.marker() == 42;
                for (int Item = Item.marker() - 42; Item < 1; Item++) {
                    valid = valid && Item == 0;
                }
                valid = valid && Item.marker() == 42;
                for Item in range(Item.marker() - 41) {
                    valid = valid && Item == 0;
                }
                valid = valid && Item.marker() == 42;
                return valid ? 0 : 1;
            }
        """,
        "block-cfor-range-type-shadow",
        id="block-cfor-range",
    ),
    pytest.param(
        """
            class Item {
                class int marker() { return 42; }
            }

            class Numbers {
                public int iterLen() { return 1; }
                public int iterGet(int index) {
                    (void)index;
                    return 7;
                }
            }

            int main() {
                bool valid = true;
                for Item in "a" {
                    valid = valid && Item == 'a';
                }
                valid = valid && Item.marker() == 42;
                Numbers numbers = new Numbers();
                for Item in numbers {
                    valid = valid && Item == 7;
                }
                valid = valid && Item.marker() == 42;
                delete numbers;
                return valid ? 0 : 1;
            }
        """,
        "iteration-type-shadow",
        id="string-iterable",
    ),
    pytest.param(
        """
            class Item {
                class int marker() { return 42; }
            }

            int main() {
                bool valid = false;
                try {
                    throw "x";
                } catch (string Item) {
                    valid = Item.length() == 1;
                }
                valid = valid && Item.marker() == 42;
                return valid ? 0 : 1;
            }
        """,
        "catch-type-shadow",
        id="catch",
    ),
    pytest.param(
        """
            int itemsAlive = 0;

            class Item {
                public int value;
                public Item(int value) {
                    self.value = value;
                    itemsAlive++;
                }
                public void __del__() { itemsAlive--; }
            }

            class Items {
                public int iterLen() { return 1; }
                public Item iterGet(int index) {
                    (void)index;
                    return new Item(42);
                }
            }

            Item select(Items items) {
                for Item in items {
                    return Item;
                }
                return null;
            }

            int main() {
                Items items = new Items();
                Item result = select(items);
                bool valid = itemsAlive == 1 && result.value == 42;
                if (!valid) {
                    delete items;
                    return 1;
                }
                delete result;
                valid = itemsAlive == 0;
                delete items;
                return valid ? 0 : 1;
            }
        """,
        "managed-iteration-type-shadow",
        id="managed-iteration-return",
    ),
    pytest.param(
        """
            class Item {
                class int marker() { return 42; }
            }

            string capture() {
                try {
                    throw "caught";
                } catch (string Item) {
                    return Item;
                }
                return "";
            }

            int main() {
                string result = capture();
                return result.equals("caught") && Item.marker() == 42
                    ? 0 : 1;
            }
        """,
        "managed-catch-type-shadow",
        id="managed-catch-return",
    ),
)


PROPERTY_SETTER_SHADOW_SOURCES = (
    pytest.param(
        """
            class value {}

            class Holder {
                public int stored;
                public int number {
                    get { return self.stored; }
                    set {
                        value probe = new value();
                        delete probe;
                        self.stored = value;
                    }
                }
            }

            int main() {
                Holder holder = new Holder();
                holder.number = 42;
                bool valid = holder.number == 42;
                delete holder;
                return valid ? 0 : 1;
            }
        """,
        "property-setter-type-shadow",
        id="ordinary-custom",
    ),
    pytest.param(
        """
            class value {}

            class Base {
                public int number { get; set; }
            }

            class Child extends Base {}

            int main() {
                Child child = new Child();
                child.number = 42;
                value probe = new value();
                bool valid = child.number == 42;
                delete probe;
                delete child;
                return valid ? 0 : 1;
            }
        """,
        "inherited-property-setter-type-shadow",
        id="inherited-auto",
    ),
    pytest.param(
        """
            class value {}

            class Box<T> {
                private T stored;
                public T item {
                    get { return self.stored; }
                    set {
                        value probe = new value();
                        delete probe;
                        self.stored = value;
                    }
                }
            }

            int main() {
                Box<int> box = new Box<int>();
                box.item = 42;
                bool valid = box.item == 42;
                delete box;
                return valid ? 0 : 1;
            }
        """,
        "generic-property-setter-type-shadow",
        id="generic-custom",
    ),
)


LEXICAL_IDENTITY_SOURCES = (
    pytest.param(
        """
            int resourcesAlive = 0;

            class Resource {
                public Resource() { resourcesAlive++; }
                public void __del__() { resourcesAlive--; }
            }

            int run() {
                Resource owner = new Resource();
                {
                    int owner = 7;
                    if (owner == 7) { return 0; }
                }
                return 1;
            }

            int main() {
                int result = run();
                return result == 0 && resourcesAlive == 0 ? 0 : 1;
            }
        """,
        "nested-managed-scalar-return",
        id="outer-managed-inner-scalar-return",
    ),
    pytest.param(
        """
            int resourcesAlive = 0;

            class Resource {
                public int id;
                public Resource(int id) {
                    self.id = id;
                    resourcesAlive++;
                }
                public void __del__() { resourcesAlive--; }
            }

            int run() {
                Resource item = new Resource(1);
                {
                    Resource item = new Resource(2);
                    delete item;
                    if (resourcesAlive != 1) { return 1; }
                }
                if (resourcesAlive != 1 || item.id != 1) { return 2; }
                return 0;
            }

            int main() {
                int result = run();
                return result == 0 && resourcesAlive == 0 ? 0 : 1;
            }
        """,
        "nested-managed-delete",
        id="nested-managed-delete-unregisters-current-owner",
    ),
    pytest.param(
        """
            int resourcesAlive = 0;

            class Resource {
                public int id;
                public Resource(int id) {
                    self.id = id;
                    resourcesAlive++;
                }
                public void __del__() { resourcesAlive--; }
            }

            Resource select() {
                Resource value = new Resource(1);
                try {
                    Resource value = new Resource(2);
                    return value;
                } catch (string problem) {
                    (void)problem;
                }
                return null;
            }

            int main() {
                Resource result = select();
                bool valid = resourcesAlive == 1 && result.id == 2;
                delete result;
                return valid && resourcesAlive == 0 ? 0 : 1;
            }
        """,
        "nested-managed-return-transfer",
        id="nested-managed-return-keeps-current-owner-only",
    ),
    pytest.param(
        """
            int resourcesAlive = 0;

            class Resource {
                public int id;
                public Resource(int id) {
                    self.id = id;
                    resourcesAlive++;
                }
                public void __del__() { resourcesAlive--; }
            }

            class Box<T> {
                public Resource select() {
                    Resource value = new Resource(1);
                    try {
                        Resource value = new Resource(2);
                        return value;
                    } catch (string problem) {
                        (void)problem;
                    }
                    return null;
                }

                public bool destroyInnerThenReturn() {
                    Resource value = new Resource(3);
                    {
                        Resource value = new Resource(4);
                        delete value;
                        return resourcesAlive == 1;
                    }
                    return false;
                }

                public bool verifyLoopBindings(int value) {
                    bool valid = true;
                    for (int value = value - 2; value < 1; value++) {
                        valid = valid && value == 0;
                    }
                    valid = valid && value == 2;
                    for value in range(value - 1) {
                        valid = valid && value == 0;
                    }
                    return valid && value == 2;
                }
            }

            int main() {
                Box<int> box = new Box<int>();
                Resource result = box.select();
                bool valid = resourcesAlive == 1 && result.id == 2;
                delete result;
                valid = valid && resourcesAlive == 0;
                valid = valid && box.destroyInnerThenReturn();
                valid = valid && resourcesAlive == 0;
                valid = valid && box.verifyLoopBindings(2);
                delete box;
                return valid ? 0 : 1;
            }
        """,
        "generic-nested-managed-identity",
        id="generic-managed-return-and-delete-keep-current-owner-only",
    ),
)


def test_rich_enum_payload_name_may_shadow_a_source_type(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Item {}

        enum class Payload {
            Some(int Item),
            Empty
        }

        int main() {
            Payload payload = Payload.Some(42);
            Item value = new Item();
            bool valid = payload.data.Some.Item == 42;
            delete value;
            return valid ? 0 : 1;
        }
    """
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "rich-enum-type-shadow",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)


@pytest.mark.parametrize(("source", "name"), SCOPE_SHADOW_SOURCES)
def test_type_shadow_bindings_restore_every_enclosing_scope(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    name: str,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        name,
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)


@pytest.mark.parametrize(("source", "name"), PROPERTY_SETTER_SHADOW_SOURCES)
def test_implicit_property_value_binding_may_shadow_a_source_type(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    name: str,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        name,
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)


@pytest.mark.parametrize(("source", "name"), LEXICAL_IDENTITY_SOURCES)
def test_nested_bindings_keep_declaration_specific_c_and_ownership_identity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    name: str,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        name,
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)
