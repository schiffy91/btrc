"""Independent value/member namespaces in self-hosted method resolution."""

from pathlib import Path

from src.tests.btrc.test_semantic_validation import _compile_source, _strict_build_and_run

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def test_method_lookup_ignores_same_named_field(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int alive = 0;
        class Item {
            public int id;
            public Item(int id) { self.id = id; alive++; }
            public void __del__() { alive--; }
        }
        class Factory<T> {
            public T* build;
            public Factory() {}
            public Item build<U>(U marker) {
                assert(sizeof(marker) != (size_t)0);
                return new Item(7);
            }
        }
        class Plain {
            public int value;
            public Plain() {}
            public int value() { return 9; }
        }
        void verify() {
            Factory<int> factory = new Factory<int>();
            var item = factory.build(42);
            Plain plain = new Plain();
            var number = plain.value();
            assert(item.id == 7);
            assert(number == 9);
        }
        int main() {
            verify();
            assert(alive == 0);
            return 0;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    _strict_build_and_run(generated, tmp_path / "method-field-collision")
