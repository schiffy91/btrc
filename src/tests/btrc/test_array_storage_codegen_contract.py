"""C storage-shape parity for class and file-scope array declarations."""

from __future__ import annotations

from pathlib import Path

from src.tests.btrc.test_semantic_validation import (
    CC,
    _compile_reference_source,
    _compile_source,
    _run,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _compile_both(semantic_btrcc: Path, tmp_path: Path, source: str):
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return selfhost_source, reference_source


def _strict_link_and_run(generated: Path, companion: Path, output: Path) -> None:
    build = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(generated),
            str(companion),
            "-o",
            str(output),
            "-lm",
            "-lpthread",
        ],
        timeout=60,
    )
    assert build.returncode == 0, build.stderr
    run = _run([str(output)], timeout=30)
    assert run.returncode == 0, run.stderr


def test_unsized_static_class_array_is_a_rebindable_pointer_slot(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int backing[2] = {11, 31};

        class ArraySlot {
            class int[] values;
        }

        int main() {
            ArraySlot.values = backing;
            return ArraySlot.values[1] == 31 ? 0 : 1;
        }
    """
    generated = _compile_both(semantic_btrcc, tmp_path, source)

    for index, path in enumerate(generated):
        assert "static int* ArraySlot_values;" in path.read_text()
        _strict_build_and_run(path, tmp_path / f"static-array-pointer-{index}")


def test_unsized_global_initializer_infers_real_array_backing(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int values[] = {11, 31};
        int main() { return values[1] == 31 ? 0 : 1; }
    """
    generated = _compile_both(semantic_btrcc, tmp_path, source)

    for index, path in enumerate(generated):
        assert "static int values[2] = {11, 31};" in path.read_text()
        _strict_build_and_run(path, tmp_path / f"inferred-global-array-{index}")


def test_extern_unsized_arrays_keep_incomplete_declarators_and_link(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        extern int global_values[];

        int main() {
            extern int block_values[];
            return global_values[0] == 11 && block_values[0] == 31 ? 0 : 1;
        }
    """
    generated = _compile_both(semantic_btrcc, tmp_path, source)
    companion = tmp_path / "array-definitions.c"
    companion.write_text("int global_values[] = {11};\nint block_values[] = {31};\n")

    for index, path in enumerate(generated):
        c_source = path.read_text()
        assert "extern int global_values[];" in c_source
        assert "extern int block_values[];" in c_source
        assert "extern int* global_values;" not in c_source
        assert "extern int* block_values;" not in c_source
        _strict_link_and_run(
            path,
            companion,
            tmp_path / f"extern-unsized-array-{index}",
        )


def test_generic_method_array_locals_preserve_declarators_and_storage(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int shared[1] = {13};

        class Generic<Value> {
            public int run() {
                static int cached[2] = {7, 11};
                volatile Value local[2];
                local[0] = (Value)3;
                local[1] = (Value)5;
                extern int shared[];
                return cached[1] + (int)local[1] + shared[0] == 29 ? 0 : 1;
            }
        }

        int main() {
            Generic<int> value = new Generic<int>();
            int result = value.run();
            delete value;
            return result;
        }
    """
    generated = _compile_both(semantic_btrcc, tmp_path, source)

    for index, path in enumerate(generated):
        c_source = path.read_text()
        assert "static int cached[2] = {7, 11};" in c_source
        assert "volatile int local[2];" in c_source
        assert "extern int shared[];" in c_source
        _strict_build_and_run(path, tmp_path / f"generic-array-locals-{index}")


def test_aggregate_fields_and_typedefs_preserve_object_qualifiers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        typedef volatile int VolatileInt;
        typedef volatile int* VolatilePointer;

        struct Storage {
            volatile int scalar;
            volatile int* pointer;
            volatile int values[2];
            const int constant;
        };

        class Box {
            public volatile int scalar;
            public volatile int* pointer;
            public volatile int values[2];
        }

        enum class Payload {
            Value(volatile int scalar, volatile int* pointer),
            Empty
        }

        int inspect((volatile int, volatile int*) tuple) { return 0; }
        int main() { return 0; }
    """
    generated = _compile_both(semantic_btrcc, tmp_path, source)

    for index, path in enumerate(generated):
        c_source = path.read_text()
        assert "typedef volatile int VolatileInt;" in c_source
        assert "typedef int* volatile VolatilePointer;" in c_source
        assert c_source.count("volatile int scalar;") >= 3
        assert c_source.count("int* volatile pointer;") >= 3
        assert c_source.count("volatile int values[2];") >= 2
        assert "const int constant;" in c_source
        assert "volatile int _0;" in c_source
        assert "int* volatile _1;" in c_source
        _strict_build_and_run(path, tmp_path / f"aggregate-qualifiers-{index}")
