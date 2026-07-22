"""Explicit GPU output bounds preserve declaration order and capacity."""

from pathlib import Path

from src.tests.btrc.test_gpu_boundary import _compile_with_stub, _run
from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _frontend_outputs(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
):
    selfhost_dir = tmp_path / "selfhost"
    reference_dir = tmp_path / "reference"
    selfhost_dir.mkdir()
    reference_dir.mkdir()
    selfhost, selfhost_c = _compile_source(
        semantic_btrcc,
        selfhost_dir,
        source,
    )
    reference, reference_c = _compile_reference_source(
        reference_dir,
        source,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return selfhost_c, reference_c


def _stub_result(generated: Path, tmp_path: Path, name: str):
    build_dir = tmp_path / name
    build_dir.mkdir()
    binary = _compile_with_stub(
        generated.read_text(),
        build_dir,
        "gpu_unavailable_stub.c",
    )
    return _run([str(binary)], timeout=15)


def test_explicit_gpu_bound_runs_before_initializer_arguments(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int trace = 0;
        int outputBound() { trace = trace * 10 + 1; return 2; }
        int inputValue() { trace = trace * 10 + 2; return 9; }
        @gpu int[] fill(int value, int[] shape) {
            int i = gpu_id();
            return value + shape[i];
        }
        int main() {
            int shape[2] = {1, 2};
            int output[outputBound()] = fill(inputValue(), shape);
            return trace == 12 && output[0] == 10 && output[1] == 11
                ? 0 : 1;
        }
    """

    for index, generated in enumerate(_frontend_outputs(semantic_btrcc, tmp_path, source)):
        result = _stub_result(generated, tmp_path, f"order-{index}")
        assert result.returncode == 0, result.stderr


def test_explicit_gpu_bound_is_the_writable_capacity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        @gpu int[] copy(int[] values) {
            int i = gpu_id();
            return values[i];
        }
        int main() {
            int values[2] = {3, 5};
            int output[1] = copy(values);
            return output[0];
        }
    """

    for index, generated in enumerate(_frontend_outputs(semantic_btrcc, tmp_path, source)):
        result = _stub_result(generated, tmp_path, f"capacity-{index}")
        assert result.returncode != 0


def test_generic_explicit_gpu_bound_runs_before_initializer_arguments(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int trace = 0;
        int outputBound() { trace = trace * 10 + 1; return 2; }
        int inputValue() { trace = trace * 10 + 2; return 9; }
        @gpu int[] fill(int value, int[] shape) {
            int i = gpu_id();
            return value + shape[i];
        }
        class Harness<T> {
            public int run() {
                int shape[2] = {1, 2};
                int output[outputBound()] = fill(inputValue(), shape);
                return trace == 12 && output[0] == 10 && output[1] == 11
                    ? 0 : 1;
            }
        }
        int main() {
            Harness<int> harness = new Harness<int>();
            int result = harness.run();
            delete harness;
            return result;
        }
    """

    for index, generated in enumerate(_frontend_outputs(semantic_btrcc, tmp_path, source)):
        result = _stub_result(generated, tmp_path, f"generic-order-{index}")
        assert result.returncode == 0, result.stderr


def test_generic_explicit_gpu_bound_is_the_writable_capacity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int trace = 0;
        int outputBound() { trace = trace * 10 + 1; return 1; }
        int inputValue() { trace = trace * 10 + 2; return 9; }
        @gpu int[] fill(int value, int[] shape) {
            int i = gpu_id();
            return value + shape[i];
        }
        class Harness<T> {
            public int run() {
                int shape[2] = {1, 2};
                int output[outputBound()] = fill(inputValue(), shape);
                return output[0];
            }
        }
        int main() {
            Harness<int> harness = new Harness<int>();
            int result = harness.run();
            delete harness;
            return trace == 12 ? result : 0;
        }
    """

    for index, generated in enumerate(_frontend_outputs(semantic_btrcc, tmp_path, source)):
        result = _stub_result(generated, tmp_path, f"generic-capacity-{index}")
        assert result.returncode != 0


def test_explicit_gpu_capacity_keeps_dispatch_logical_length(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        @gpu int[] copy(int[] values) {
            int i = gpu_id();
            return values[i];
        }
        int main() {
            int values[2] = {3, 5};
            int output[4] = copy(values);
            int count = 0;
            int total = 0;
            for value in output { count++; total += value; }
            int second[4] = {99, 99, 99, 99};
            second = copy(output);
            return count == 2 && total == 8
                && second[0] == 3 && second[1] == 5
                && second[2] == 99 && second[3] == 99 ? 0 : 1;
        }
    """

    for index, generated in enumerate(_frontend_outputs(semantic_btrcc, tmp_path, source)):
        result = _stub_result(generated, tmp_path, f"logical-{index}")
        assert result.returncode == 0, result.stderr


def test_generic_explicit_gpu_capacity_keeps_dispatch_logical_length(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        @gpu int[] copy(int[] values) {
            int i = gpu_id();
            return values[i];
        }
        class Harness<T> {
            public int run() {
                int values[2] = {3, 5};
                int output[4] = copy(values);
                int count = 0;
                int total = 0;
                for value in output { count++; total += value; }
                int second[4] = {99, 99, 99, 99};
                second = copy(output);
                return count == 2 && total == 8
                    && second[0] == 3 && second[1] == 5
                    && second[2] == 99 && second[3] == 99 ? 0 : 1;
            }
        }
        int main() {
            Harness<int> harness = new Harness<int>();
            int result = harness.run();
            delete harness;
            return result;
        }
    """

    for index, generated in enumerate(_frontend_outputs(semantic_btrcc, tmp_path, source)):
        result = _stub_result(
            generated,
            tmp_path,
            f"generic-logical-{index}",
        )
        assert result.returncode == 0, result.stderr
