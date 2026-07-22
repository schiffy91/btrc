"""Frontend parity for inferred array-returning GPU bindings."""

from pathlib import Path

import pytest

from src.tests.btrc.test_gpu_boundary import _compile_with_stub, _run
from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def test_inferred_gpu_results_materialize_capacity_known_arrays(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = (
        "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
        "@gpu int[] fill(int value) { return value; } "
        "int main() { int[] values = {3, 5}; var output = copy(values); "
        "output = copy(output); var singleton = fill(7); "
        "return output[1] == 5 && singleton[0] == 7 ? 0 : 1; }"
    )
    self_dir = tmp_path / "selfhost"
    reference_dir = tmp_path / "reference"
    self_dir.mkdir()
    reference_dir.mkdir()
    selfhost, selfhost_c = _compile_source(semantic_btrcc, self_dir, source)
    reference, reference_c = _compile_reference_source(reference_dir, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    for index, generated in enumerate((selfhost_c, reference_c)):
        build_dir = tmp_path / f"run-{index}"
        build_dir.mkdir()
        binary = _compile_with_stub(
            generated.read_text(),
            build_dir,
            "gpu_unavailable_stub.c",
        )
        result = _run([str(binary)], timeout=15)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        (
            "typedef int[] Values; "
            "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
            "int main() { int[] values = {3, 5}; "
            "Values output = copy(values); return 0; }",
            "pointer-valued array alias",
        ),
        (
            "int main() { var values = {1, 2}; return 0; }",
            "Cannot infer array storage for 'var'",
        ),
    ],
)
def test_unsafe_inferred_array_forms_are_rejected_with_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 1
    assert reference.returncode == 1
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr
