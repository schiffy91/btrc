"""Array-returning GPU calls require a direct materialization boundary."""

import re
from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import compile_diagnostic_pair
from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

DIAGNOSTIC = "is only valid as an array declaration initializer or direct array assignment statement"

PREFIX = """
@gpu int[] copy(int[] values) {
    int index = gpu_id();
    return values[index];
}

void consume(int[] values) { (void)values; }
"""

INVALID_CONTEXTS = (
    pytest.param(
        "int main() { int values[1] = {7}; return sizeof(copy(values)); }",
        id="sizeof",
    ),
    pytest.param(
        "int main() { int values[1] = {7}; consume(copy(values)); return 0; }",
        id="nested-call-argument",
    ),
    pytest.param(
        "int main() { int values[1] = {7}; return copy(values)[0]; }",
        id="indexed-result",
    ),
    pytest.param(
        "int main() { int values[1] = {7}; return copy(values).length; }",
        id="member-result",
    ),
    pytest.param(
        "int main() { int values[1] = {7}; copy(values); return 0; }",
        id="discarded-result",
    ),
    pytest.param(
        "int main() { int values[1] = {7}; int* output = copy(values); return output[0]; }",
        id="pointer-declaration-is-not-array-storage",
    ),
    pytest.param(
        "int* bad(int[] values) { return copy(values); } int main() { int values[1] = {7}; return bad(values)[0]; }",
        id="returned-result",
    ),
    pytest.param(
        "int main() { int values[1] = {7}; int* selected = true ? copy(values) : values; return selected[0]; }",
        id="ternary-result",
    ),
    pytest.param(
        "int main() { int values[1] = {7}; int* casted = (int*)copy(values); return casted[0]; }",
        id="cast-result",
    ),
    pytest.param(
        "int main() { int values[1] = {7}; int* shifted = copy(values) + 0; return shifted[0]; }",
        id="pointer-arithmetic-result",
    ),
    pytest.param(
        "int main() { int values[1] = {7}; return *copy(values); }",
        id="unary-result",
    ),
    pytest.param(
        "int main() { int values[1] = {7}; int output[1]; return (output = copy(values))[0]; }",
        id="assignment-result-used-as-value",
    ),
    pytest.param(
        "int main() { int values[1] = {7}; int output[1] = copy(copy(values)); return output[0]; }",
        id="nested-output-call",
    ),
)

VALID_CONTEXTS = (
    pytest.param(
        PREFIX + "int main() { int values[1] = {7}; int output[1] = copy(values); return output[0] - 7; }",
        id="explicit-array-initializer",
    ),
    pytest.param(
        PREFIX + "int main() { int values[1] = {7}; var output = copy(values); return output[0] - 7; }",
        id="inferred-array-initializer",
    ),
    pytest.param(
        PREFIX + "int main() { int values[1] = {7}; int output[1]; output = copy(values); return output[0] - 7; }",
        id="direct-array-assignment",
    ),
    pytest.param(
        PREFIX + "@gpu int[] select(int[] source, int[] selected = source) { "
        "int index = gpu_id(); return selected[index]; } "
        "int main() { int values[1] = {7}; "
        "int output[1] = select(values); return output[0] - 7; }",
        id="array-default-inherits-source-capacity",
    ),
    pytest.param(
        PREFIX + "int main() { var copy = (int value) => value; return copy(7) - 7; }",
        id="local-callable-shadow",
    ),
    pytest.param(
        PREFIX + "@gpu void bump(int[] values) { int index = gpu_id(); "
        "values[index] += 1; } "
        "int main() { int values[1] = {7}; bump(values); return 0; }",
        id="void-gpu-call-statement",
    ),
)


@pytest.mark.parametrize("body", INVALID_CONTEXTS)
def test_array_gpu_result_requires_direct_storage_boundary_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
    body: str,
) -> None:
    for result in compile_diagnostic_pair(
        semantic_btrcc,
        tmp_path,
        PREFIX + body,
    ):
        assert result.returncode != 0
        assert DIAGNOSTIC in result.stderr


@pytest.mark.parametrize("source", VALID_CONTEXTS)
def test_array_gpu_result_storage_boundaries_remain_valid_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    for result in compile_diagnostic_pair(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode == 0, result.stderr


def test_volatile_scalar_gpu_parameter_survives_every_generated_signature(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = (
        "@gpu void shift(volatile int delta, int[] values) { "
        "int index = gpu_id(); values[index] += delta; } "
        "int main() { int values[1] = {7}; shift(2, values); return 0; }"
    )
    for result, generated in (
        _compile_source(semantic_btrcc, tmp_path, source),
        _compile_reference_source(tmp_path, source),
    ):
        assert result.returncode == 0, result.stderr
        emitted = generated.read_text()
        assert len(re.findall(r"shift__gpuitem\(volatile int delta,", emitted)) >= 2
        assert len(re.findall(r"shift__gpucpu\(volatile int delta,", emitted)) >= 2
        assert re.search(
            r"(?:__gpu_dispatch_[0-9]+|__btrc_gpu_shift_[0-9]+)_run"
            r"\(volatile int delta,",
            emitted,
        )
