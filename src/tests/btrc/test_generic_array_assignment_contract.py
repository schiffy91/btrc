"""Array assignment follows runtime storage provenance in both frontends."""

from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _compile_both(semantic_btrcc: Path, tmp_path: Path, source: str):
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    return (selfhost, selfhost_source), (reference, reference_source)


def test_pointer_backed_array_bindings_rebind_and_index_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Buffer<T> {
            public T[] data;
            public Buffer(T[] data) { self.data = data; }
            public void reset(T[] data) { self.data = data; }
            public T get(int index) { return self.data[index]; }
        }

        class StaticSlot {
            class int[] values;
        }

        class View {
            public int[] values { get; set; }
        }

        struct Slice { int[] data; };

        int reboundFirst(int target[2], int[] source) {
            target = source;
            var alias = target;
            alias = source;
            return alias[0];
        }

        int main() {
            int first[2] = {7, 3};
            int second[2] = {42, 9};
            Buffer<int> values = new Buffer<int>(first);
            values.reset(second);
            Slice slice;
            slice.data = first;
            slice.data = second;
            StaticSlot.values = first;
            StaticSlot.values = second;
            View view = new View();
            view.values = first;
            view.values = second;
            bool valid = values.get(0) == 42
                && slice.data[1] == 9
                && StaticSlot.values[0] == 42
                && view.values[1] == 9
                && reboundFirst(first, second) == 42;
            delete view;
            delete values;
            return valid ? 0 : 1;
        }
    """
    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stderr
        _strict_build_and_run(generated, tmp_path / f"array-pointer-slots-{index}")


def test_array_typedefs_are_pointer_values_across_storage_boundaries(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        typedef int[] Values;

        int defaults[2] = {5, 6};
        Values globalValues = defaults;

        Values choose(Values values) { return values; }
        int defaultSecond(Values values = defaults) { return values[1]; }

        class AliasBox {
            public Values data;
            public AliasBox(Values data) { self.data = data; }
            public void reset(int* data) { self.data = data; }
            public Values get() { return self.data; }
        }

        struct AliasSlice { Values data; };

        int first(Values values) {
            Values local = values;
            int* raw = local;
            local = raw;
            return local[0];
        }

        int main() {
            int firstBacking[2] = {7, 3};
            int secondBacking[2] = {42, 9};
            Values selected = firstBacking;
            selected = secondBacking;
            Values returned = choose(selected);
            AliasBox box = new AliasBox(firstBacking);
            box.reset(secondBacking);
            AliasSlice slice = {firstBacking};
            slice.data = secondBacking;
            bool valid = globalValues[0] == 5
                && defaultSecond() == 6
                && returned[1] == 9
                && box.get()[0] == 42
                && slice.data[1] == 9
                && first(selected) == 42;
            delete box;
            return valid ? 0 : 1;
        }
    """
    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stderr
        _strict_build_and_run(generated, tmp_path / f"array-typedef-values-{index}")


def test_gpu_outputs_accept_exact_element_storage_with_provable_capacity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Vector<T> {
            public T* data;
            public int len;
            public Vector(T* data, int len) { self.data = data; self.len = len; }
        }

        class StaticOutput { class int[] values = {0, 0}; }

        extern int externalOutput[2];

        @gpu int[] copy(int[] values) {
            int index = gpu_id();
            return values[index];
        }

        int main() {
            int input[2] = {1, 2};
            int fixed[2];
            int heapData[2];
            Vector<int> heap = new Vector<int>(heapData, 2);
            fixed = copy(input);
            heap = copy(input);
            StaticOutput.values = copy(input);
            externalOutput = copy(input);
            fixed = copy(heap);
            fixed = copy(StaticOutput.values);
            fixed = copy(externalOutput);
            delete heap;
            return 0;
        }
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("source", "diagnostic"),
    (
        (
            "int main() { int[] source = {1}; int[] copy = source; return 0; }",
            "array initializer",
        ),
        (
            "int main() { int source[1] = {1}; int copy[1] = {0}; copy = source; return 0; }",
            "array",
        ),
        (
            "int main() { int[] source = {1}; int[] target = {0}; target = source; return 0; }",
            "array",
        ),
        (
            "int source[] = {1}; int target[] = {0}; int main() { target = source; return 0; }",
            "array",
        ),
        (
            "class Slots { class int[] target = {0}; } "
            "int main() { int source[1] = {1}; Slots.target = source; return 0; }",
            "array",
        ),
        (
            "extern int target[]; int main() { int source[1] = {1}; target = source; return 0; }",
            "array",
        ),
        (
            "int main() { int values[]; return 0; }",
            "requires an array bound or initializer",
        ),
        (
            "int values[]; int main() { return 0; }",
            "requires an array bound or initializer",
        ),
        (
            "typedef int[] Values; Values slots[2]; int main() { return 0; }",
            "nested array composition",
        ),
        (
            "typedef int[] Values; int main() { Values values = {1}; return 0; }",
            "initializer",
        ),
        (
            "typedef int[] Values; class Slots { class Values values = {1}; } int main() { return 0; }",
            "array",
        ),
        (
            "class Slots { public int[] values = {1}; } int main() { return 0; }",
            "array",
        ),
        (
            "typedef int[] Values; struct Slice { Values data; }; int main() { Slice slice = {{1}}; return 0; }",
            "aggregate",
        ),
        (
            "int first(int[] values = {1}) { return values[0]; } int main() { return first(); }",
            "parameter",
        ),
        (
            "@gpu int[] copy(int[] values) { int i = gpu_id(); "
            "return values[i]; } int run(int[] output) { int values[1] = {1}; "
            "output = copy(values); return 0; } int main() { return 0; }",
            "no provable writable capacity",
        ),
        (
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            "class Output { public int[] values { get; set; } } "
            "int run(Output output) { int values[1] = {1}; "
            "output.values = copy(values); return 0; } "
            "int main() { return 0; }",
            "no provable writable capacity",
        ),
        (
            "class Vector<T> { public T* data; public int len; "
            "public Vector(T* data, int len) { self.data = data; self.len = len; } } "
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            'int main() { string data[1] = {"x"}; int values[1] = {1}; '
            "Vector<string> output = new Vector<string>(data, 1); "
            "output = copy(values); return 0; }",
            "output element type",
        ),
        (
            "class Vector<T> { public T* data; public int len; "
            "public Vector(T* data, int len) { self.data = data; self.len = len; } } "
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            "int main() { float data[2] = {1.0, 2.0}; "
            "Vector<float> input = new Vector<float>(data, 2); int output[2]; "
            "output = copy(input); return 0; }",
            "abi-compatible gpu buffer element",
        ),
        (
            "typedef int[] Values; int backing[2] = {1, 2}; Values view = backing; "
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            "int main() { int output[2]; output = copy(view); return 0; }",
            "no provable readable gpu buffer capacity",
        ),
        (
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            "int run(int input[2]) { int output[2]; output = copy(input); return 0; } "
            "int main() { return 0; }",
            "no provable readable gpu buffer capacity",
        ),
        (
            "extern int input[]; "
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            "int main() { int output[2]; output = copy(input); return 0; }",
            "no provable readable gpu buffer capacity",
        ),
        (
            "volatile int input[2]; "
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            "int main() { int output[2]; output = copy(input); return 0; }",
            "abi-compatible gpu buffer element",
        ),
        (
            "@gpu void inspect(const int[] values) { int i = gpu_id(); "
            "int value = values[i]; } int main() { return 0; }",
            "gpu array buffers are read-write",
        ),
        (
            "@gpu void inspect(volatile int[] values) { int i = gpu_id(); "
            "int value = values[i]; } int main() { return 0; }",
            "gpu array buffers are read-write",
        ),
        (
            "@gpu int[] copy(int[] values) { int i = gpu_id(); "
            "return values[i]; } int run(int output[2]) { int values[1] = {1}; "
            "output = copy(values); return 0; } int main() { return 0; }",
            "no provable writable capacity",
        ),
        (
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            "int main() { int input[2] = {1, 2}; string output[2]; "
            "output = copy(input); return 0; }",
            "output element type",
        ),
        (
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            "int main() { int input[2] = {1, 2}; float output[2]; "
            "output = copy(input); return 0; }",
            "output element type",
        ),
        (
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            "int main() { int input[2] = {1, 2}; volatile int output[2]; "
            "output = copy(input); return 0; }",
            "output element type",
        ),
        (
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            "extern int output[]; int main() { int input[2] = {1, 2}; "
            "output = copy(input); return 0; }",
            "no provable writable capacity",
        ),
        (
            "class Vector<T> { public T* data; public int len; } "
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            "class Sink<T> { public Vector<T> output; public void fill() { "
            "int values[1] = {1}; self.output = copy(values); } } int main() { return 0; }",
            "output element type",
        ),
    ),
    ids=(
        "declaration-copy",
        "fixed-array-assignment",
        "inferred-local-array-object",
        "inferred-global-array-object",
        "inferred-static-field-array-object",
        "extern-array-object",
        "unbacked-local-array",
        "unbacked-global-array",
        "typedef-nested-array",
        "typedef-aggregate-local",
        "typedef-aggregate-static-field",
        "instance-field-aggregate-default",
        "typedef-aggregate-struct-element",
        "array-parameter-aggregate-default",
        "gpu-pointer-target",
        "gpu-property-target",
        "gpu-vector-wrong-element",
        "gpu-vector-input-wrong-element",
        "gpu-typedef-pointer-input",
        "gpu-fixed-bound-parameter-input",
        "gpu-incomplete-extern-input",
        "gpu-volatile-input",
        "gpu-const-parameter",
        "gpu-volatile-parameter",
        "gpu-fixed-bound-parameter-output",
        "gpu-fixed-wrong-element",
        "gpu-fixed-numeric-layout-mismatch",
        "gpu-volatile-target",
        "gpu-incomplete-extern-target",
        "gpu-unresolved-generic-target",
    ),
)
def test_invalid_array_storage_operations_are_rejected_by_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode == 1
        assert diagnostic in result.stderr.lower()
