"""Cross-front qualifier provenance and strict-C contracts."""

from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


@pytest.mark.parametrize(
    "source",
    [
        "volatile int value = 0; int* alias = &value; int main(){ return 0; }",
        "struct S { volatile int value; }; int main(){ S s = {0}; int* p = &s.value; return 0; }",
        "void take(int* p){} int main(){ volatile int values[1]={0}; take(values); return 0; }",
        """
            typedef volatile int V;
            typedef V* P;
            int main() {
                V value = 0;
                P pointer = &value;
                int* bad = &pointer[0];
                return 0;
            }
        """,
        """
            typedef volatile int V;
            typedef V* P;
            int main() {
                V value = 0;
                P pointer = &value;
                int* bad = &*pointer;
                return 0;
            }
        """,
        """
            typedef volatile int V;
            typedef V* P;
            int main() {
                V value = 0;
                Vector<P> pointers = [&value];
                int* bad = pointers[0];
                return 0;
            }
        """,
        """
            typedef volatile int V;
            class Box<T> {
                public T value;
                public Box(T value) { self.value = value; }
            }
            int main() {
                Box<V> box = new Box<V>(0);
                int* bad = &box.value;
                return 0;
            }
        """,
        """
            typedef volatile int V;
            typedef V* P;
            class Source<T> {
                public Source() {}
                public T getValue() { return (T)null; }
            }
            int main() {
                Source<P> source = new Source<P>();
                int* bad = source.getValue();
                return 0;
            }
        """,
        """
            typedef volatile int V;
            typedef V* P;
            class Source<T> {
                public Source() {}
                public T __neg__() { return (T)null; }
            }
            int main() {
                Source<P> source = new Source<P>();
                int* bad = -source;
                return 0;
            }
        """,
        """
            typedef volatile int V;
            typedef V* P;
            class Source<T> {
                public Source() {}
                public T get(int index) { return (T)null; }
            }
            int main() {
                Source<P> source = new Source<P>();
                int* bad = source[0];
                return 0;
            }
        """,
    ],
)
def test_selfhost_rejects_nested_volatile_loss(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert "would discard volatile storage qualification" in result.stderr
    assert "unsupported layered pointer qualifiers" in result.stderr


@pytest.mark.parametrize(
    "source, subject",
    [
        ("const int f(){ return 1; } int main(){ return 0; }", "function 'f'"),
        (
            "class C { public volatile int* f(){ return null; } } int main(){ return 0; }",
            "method 'C.f'",
        ),
        ("__fn_ptr<const int> callback; int main(){ return 0; }", "Global 'callback'"),
        (
            "int main(){ var callback = const int function(){ return 1; }; return 0; }",
            "Lambda return type",
        ),
    ],
)
def test_selfhost_rejects_callable_outer_cv_results(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    subject: str,
) -> None:
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert subject in result.stderr
    assert "C discards qualifiers" in result.stderr


def test_selfhost_rejects_const_rich_enum_payload(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    result, _ = _compile_source(
        semantic_btrcc,
        tmp_path,
        "enum class Payload { Some(const int value), None } int main(){ return 0; }",
    )
    assert result.returncode == 1
    assert "cannot use const storage" in result.stderr


def test_selfhost_preserves_typedef_qualified_pointees(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        typedef volatile int V;
        typedef V* P;
        struct Probe { V value; };
        void writeValue(V* value) { *value = 7; }
        int main() {
            V value = 0;
            V values[1] = {0};
            P pointer = &value;
            long distance = pointer - pointer;
            bool absent = !pointer;
            struct Probe probe = {0};
            writeValue(&value);
            writeValue(values);
            writeValue(&pointer[0]);
            writeValue(&*pointer);
            writeValue(&probe.value);
            return value == 7 && values[0] == 7 && probe.value == 7
                && distance == 0 && !absent ? 0 : 1;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    assert "volatile V" not in generated.read_text()
    _strict_build_and_run(generated, tmp_path / "qualifier-provenance")
