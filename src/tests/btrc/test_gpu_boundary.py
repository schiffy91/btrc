"""Production-driver tests for self-hosted @gpu lowering."""

from __future__ import annotations

import ast
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

REPO = Path(__file__).resolve().parents[3]
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))
BTRCC_SOURCE = REPO / "src/compiler/btrc/btrcc_main.btrc"
FIXTURES = REPO / "src/tests/btrc/fixtures"
GPU_INCLUDE = REPO / "src/stdlib/gpu"
NAGA = shutil.which("naga")
if NAGA is None:
    shared_naga = Path("/tmp/btrc-naga-validator/bin/naga")
    if shared_naga.exists():
        NAGA = str(shared_naga)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not CC or shutil.which(CC[0]) is None,
    reason="requires a hosted C11 compiler",
)


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        **kwargs,
    )


GPU_RUN = r"\b[A-Za-z_][A-Za-z0-9_]*_run"


def _gpu_dispatch_index(
    generated: str,
    start: int = 0,
    arguments: str | None = None,
) -> int:
    pattern = rf"{GPU_RUN}\("
    if arguments is not None:
        pattern += rf"{arguments}\)"
    matches = list(re.finditer(pattern, generated[start:]))
    assert len(matches) == 1
    return start + matches[0].start()


@pytest.fixture(scope="module")
def btrcc_driver(immutable_btrcc: Path) -> Path:
    """The production self-host driver the whole suite already shares.

    This module used to transpile and link its own copy, which under xdist is
    one full compiler build per worker that reaches it.
    """

    return immutable_btrcc


def test_unused_gpu_kernel_is_proven_dead_and_erased(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    source = REPO / "src/tests/gpu/test_gpu_square.btrc"
    generated = _run([str(btrcc_driver), str(source)], timeout=120)

    assert generated.returncode == 0 and generated.stderr == ""
    assert all(marker not in generated.stdout for marker in ("squareElements", "gpu_id", "btrc_gpu", "wgsl"))

    c_path = tmp_path / "unused_gpu.c"
    binary = tmp_path / "unused_gpu"
    c_path.write_text(generated.stdout)
    compile_result = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(c_path),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        timeout=60,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    executed = _run([str(binary)], timeout=15)
    assert executed.returncode == 0
    assert executed.stdout == "PASS: test_gpu_square\n"


def _compile_with_stub(
    generated: str,
    tmp_path: Path,
    stub: str,
    *defines: str,
    extra_sources: tuple[Path, ...] = (),
    sanitize: bool = False,
) -> Path:
    c_path = tmp_path / "generated.c"
    binary = tmp_path / "generated"
    c_path.write_text(generated)
    effective_sanitize = sanitize and sys.platform != "darwin"
    compiler = (
        shlex.split(
            os.environ.get(
                "BTRC_ASAN_CC",
                "/usr/bin/clang" if sys.platform == "darwin" else CC[0],
            )
        )
        if effective_sanitize
        else CC
    )
    result = _run(
        [
            *compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            *(("-fsanitize=address", "-fno-omit-frame-pointer") if effective_sanitize else ()),
            *(f"-D{define}" for define in defines),
            f"-I{GPU_INCLUDE}",
            str(c_path),
            *(str(source) for source in extra_sources),
            str(FIXTURES / stub),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return binary


def _lower_fixture(btrcc_driver: Path, kind: str) -> str:
    result = _run(
        [
            str(btrcc_driver),
            "--no-stdlib",
            str(FIXTURES / f"gpu_called_{kind}.btrc"),
        ],
        timeout=120,
    )
    assert result.returncode == 0 and result.stderr == "", result.stderr
    return result.stdout


def _lower_source(btrcc_driver: Path, tmp_path: Path, source: str) -> str:
    source_path = tmp_path / "source.btrc"
    source_path.write_text(source)
    result = _run(
        [str(btrcc_driver), "--no-stdlib", str(source_path)],
        timeout=120,
    )
    assert result.returncode == 0 and result.stderr == "", result.stderr
    return result.stdout


def test_selfhost_gpu_input_projection_root_is_a_typed_slot_transaction() -> None:
    pipeline = (REPO / "src/compiler/btrc/ir/gpu/pipeline.btrc").read_text()
    expressions = (REPO / "src/compiler/btrc/ir/lowering/expressions.btrc").read_text()

    projection_record = pipeline[
        pipeline.index("class GpuArgumentProjectionRoot {") : pipeline.index("class GpuArgumentLedger {")
    ]
    assert "public RawProjectionStorageRoot storage;" in projection_record
    assert "public Node type;" in projection_record
    assert "public bool owned;" in projection_record
    assert all(f"public Vector<IRNode> {name};" in projection_record for name in ("declarations", "prefix", "cleanup"))

    ledger_record = pipeline[
        pipeline.index("class GpuArgumentLedger {") : pipeline.index("class GpuProjectionReceiver {")
    ]
    assert "Map<string, GpuArgumentProjectionRoot> sourceProjectionRoots" in ledger_record

    lowering = expressions[
        expressions.index("public GpuArgumentLedger lowerGpuArguments(") : expressions.index(
            "public GpuProjectionReceiver lowerGpuProjectionReceiver("
        )
    ]
    assert "projectionStorageRoot(" in lowering
    assert "if (storage != null)" in lowering
    assert "if (storage != null && storage.managed)" not in lowering
    assert "self.callOwnership.boundary()" in lowering
    assert "boundary.addLoweredOperand(" in lowering
    assert "projection.storage.managed" in lowering
    assert "projection.cleanup = boundary.suffix;" in lowering

    materialization = pipeline[
        pipeline.index("public GpuCallInputs loweredCallInputs(") : pipeline.index(
            "public GpuStatementResult materializeStatement("
        )
    ]
    assert "ledger.binding.evaluations" in materialization
    assert "projection.prefix" in materialization
    assert "inputs.cleanup.push(" in materialization


def test_selfhost_gpu_property_output_is_a_typed_managed_transaction() -> None:
    storage = (REPO / "src/compiler/btrc/analyzer/validation/storage.btrc").read_text()
    pipeline = (REPO / "src/compiler/btrc/ir/gpu/pipeline.btrc").read_text()
    expressions = (REPO / "src/compiler/btrc/ir/lowering/expressions.btrc").read_text()
    statements = (REPO / "src/compiler/btrc/ir/lowering/statements.btrc").read_text()

    admission = storage[
        storage.index("public bool gpuOutputCollectionTarget(") : storage.index("public Node? gpuBufferElementType(")
    ]
    assert "member.kind == NK_PROPERTY_DECL" in admission
    assert 'member.access != "class"' in admission
    assert "member.has_getter" in admission

    target_record = pipeline[
        pipeline.index("class GpuCollectionOutputTarget {") : pipeline.index("class GpuStatementPlan {")
    ]
    assert "public IRNode value;" in target_record
    assert "public Node type;" in target_record
    assert "public bool owned;" in target_record
    assert "public bool outputProperty;" in pipeline
    assert "self.semantics.outputCollectionType(" in pipeline

    lowering = expressions[
        expressions.index("public GpuCollectionOutputTarget lowerGpuCollectionOutputTarget(") : expressions.index(
            "/* Lower an f-string"
        )
    ]
    assert "unconsumedOwnedResult(" in lowering
    assert "self.lowerExpr(expression" in lowering
    assert "lowerGpuCollectionOutputTarget(" in statements
    assert "if (!collection.owned)" in pipeline
    assert 'IRNode.binary(stable, "=", IRNode.literal("NULL"))' in pipeline


def test_selfhost_gpu_physical_collection_output_requires_managed_storage() -> None:
    storage = (REPO / "src/compiler/btrc/analyzer/validation/storage.btrc").read_text()
    pipeline = (REPO / "src/compiler/btrc/ir/gpu/pipeline.btrc").read_text()

    admission = storage[
        storage.index("public bool gpuOutputCollectionTarget(") : storage.index("public Node? gpuBufferElementType(")
    ]
    assert "self.types.managedOwnershipType(receiverType)" in admission
    assert "member.kind == NK_FIELD_DECL" in admission
    assert 'member.access != "class"' in admission
    assert "public bool outputPhysicalCollection;" in pipeline
    assert "physicalCollection = managedProjection" in pipeline
    assert "plan.outputPhysicalCollection = physicalCollection;" in pipeline


def test_reachable_void_kernel_lowers_and_uses_checked_cpu_fallback(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_fixture(btrcc_driver, "void")
    assert "struct BtrcStatus { code: atomic<u32>, }" in generated
    assert "btrc_gpu_read_buffer_checked" in generated
    assert generated.index("buf_status") < generated.index("status == 0U")
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_array_kernel_lowers_with_capacity_guard_and_cpu_fallback(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_fixture(btrcc_driver, "array")
    assert "__gpu_output_capacity < __gpu_n" in generated
    declaration = re.search(
        r"int (__gpu_output_len_\d+) = .*?;\n"
        r"\s*int output\[\(\(\1 > 0\) \? \1 : 1\)\];",
        generated,
    )
    assert declaration is not None
    _gpu_dispatch_index(
        generated,
        arguments=(rf"__gpu_arg_\d+, __gpu_len_\d+, output, {declaration.group(1)}"),
    )
    assert "int output[] = doubleValues(values)" not in generated
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""


def test_array_kernel_may_write_a_fixed_output_buffer(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        semantic_btrcc,
        tmp_path,
        "@gpu int[] doubled(int[] values) { int i = gpu_id(); "
        "return values[i] * 2; } int main() { int[] values = {1, 2}; "
        "int output[2]; output = doubled(values); "
        "return output[0] == 2 && output[1] == 4 ? 0 : 1; }",
    )
    assert generated.count("int output[2];") == 1
    _gpu_dispatch_index(
        generated,
        arguments=(
            r"__gpu_arg_\d+, __gpu_len_\d+, output, "
            r"\(sizeof\(output\) / sizeof\(output\[0\]\)\)"
        ),
    )
    assert "output = doubled(values)" not in generated
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_generic_specialization_dispatches_void_kernel_strictly(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "@gpu void bump(int[] values) { int i = gpu_id(); values[i] += 1; } "
        "class Harness<T> { public int run() { int values[2] = {1, 2}; "
        "for values in range(1) { } "
        "bump(values); return values[0] + values[1]; } } "
        "int main() { Harness<int> harness = new Harness<int>(); "
        "int result = harness.run(); delete harness; "
        "return result == 5 ? 0 : 1; }"
    )
    generated = (
        emit_c(source)
        if frontend == "python"
        else _lower_source(
            semantic_btrcc,
            tmp_path,
            source,
        )
    )
    assert "bump(values)" not in generated
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_generic_specialization_dispatches_array_declaration_and_assignment(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
        "class Harness<T> { public int run() { int values[2] = {1, 2}; "
        "int[] first = copy(values); int second[2]; second = copy(first); "
        "return second[0] + second[1]; } } "
        "int main() { Harness<int> harness = new Harness<int>(); "
        "int result = harness.run(); delete harness; "
        "return result == 3 ? 0 : 1; }"
    )
    generated = (
        emit_c(source)
        if frontend == "python"
        else _lower_source(
            semantic_btrcc,
            tmp_path,
            source,
        )
    )
    assert "int first[] = copy(values);" not in generated
    assert "second = copy(first)" not in generated
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""


def test_array_kernel_may_write_a_fixed_struct_field(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        semantic_btrcc,
        tmp_path,
        "@gpu int[] doubled(int[] values) { int i = gpu_id(); "
        "return values[i] * 2; } struct Output { int values[2]; }; "
        "int main() { int[] input = {1, 2}; Output output; "
        "output.values = doubled(input); "
        "return output.values[0] == 2 && output.values[1] == 4 ? 0 : 1; }",
    )
    data = re.search(
        r"int\* (__gpu_output_data_\d+);.*?\(\1 = output\.values\)",
        generated,
        re.DOTALL,
    )
    length = re.search(
        r"int (__gpu_output_len_\d+);.*?\(\1 = 2\)",
        generated,
        re.DOTALL,
    )
    assert data is not None
    assert length is not None
    assert re.search(
        rf"_run\([^;]*{data.group(1)}, {length.group(1)}\)",
        generated,
    )
    assert "output.values = doubled(input)" not in generated
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""


def test_array_kernel_may_write_a_heap_collection_through_one_stable_target(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        semantic_btrcc,
        tmp_path,
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } } "
        "@gpu int[] doubled(int[] values) { int i = gpu_id(); "
        "return values[i] * 2; } int main() { int[] input = {1, 2}; "
        "int outputData[2]; Vector<int> output = "
        "new Vector<int>(outputData, 2); output = doubled(input); "
        "return outputData[0] == 2 && outputData[1] == 4 ? 0 : 1; }",
    )
    match = re.search(
        r"btrc_Vector_int\* (\w+)(?: = NULL)?;.*?\(\1 = output\)",
        generated,
        re.DOTALL,
    )
    assert match is not None
    stable = match.group(1)
    assert generated.count(f"{stable} = output") == 1
    assert f"{stable}->data" in generated
    assert f"{stable}->len" in generated
    assert re.search(rf"__btrc_arc_retain\({stable}\)", generated)
    released = re.search(rf"\((__gpu_output_target_released_\d+) = {stable}\)", generated)
    assert released is not None
    target_at = generated.index(f"{stable} = output")
    data_at = generated.index(f"{stable}->data", target_at)
    length_at = generated.index(f"{stable}->len", data_at)
    dispatch_at = _gpu_dispatch_index(generated, length_at)
    save_at = released.start()
    clear_at = generated.index(f"{stable} = NULL", save_at)
    release_at = generated.index("__btrc_arc_release", clear_at)
    assert released.group(1) in generated[release_at:]
    assert target_at < data_at < length_at < dispatch_at < save_at < clear_at < release_at
    assert "output = doubled(input)" not in generated
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""

    ordinary = tmp_path / "ordinary_array_assignment.btrc"
    ordinary.write_text(
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } } "
        "int main() { int[] input = {1, 2}; int outputData[2]; "
        "Vector<int> output = new Vector<int>(outputData, 2); "
        "output = input; return 0; }"
    )
    rejected = _run(
        [str(semantic_btrcc), "--no-stdlib", str(ordinary)],
        timeout=120,
    )
    assert rejected.returncode != 0
    assert "expects 'Vector<int>' but got 'int[]'" in rejected.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_array_kernel_may_write_inferred_global_and_static_backing(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "#include <btrc_gpu.h>\n"
        "class Outputs { class int[] values = {0, 0}; } "
        "int global_values[] = {0, 0}; "
        "@gpu int[] doubled(int[] values) { int i = gpu_id(); "
        "return values[i] * 2; } int main() { int[] input = {1, 2}; "
        "global_values = doubled(input); Outputs.values = doubled(input); "
        "return global_values[0] == 2 && global_values[1] == 4 "
        "&& Outputs.values[0] == 2 && Outputs.values[1] == 4 ? 0 : 1; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    assert "sizeof(global_values)" in generated
    assert "sizeof(Outputs_values)" in generated
    input_capacity = re.escape("(sizeof(input) / sizeof(input[0]))")
    for output in ("global_values", "Outputs_values"):
        output_name = re.escape(output)
        output_capacity = re.escape(f"(sizeof({output}) / sizeof({output}[0]))")
        direct = list(
            re.finditer(
                rf"{GPU_RUN}\((__gpu_arg_\d+), (__gpu_len_\d+), "
                rf"{output_name}, {output_capacity}\)",
                generated,
            )
        )
        staged = list(
            re.finditer(
                rf"{GPU_RUN}\((__gpu_arg_\d+), (__gpu_len_\d+), "
                r"(__gpu_output_data_\d+), (__gpu_output_len_\d+)\)",
                generated,
            )
        )
        staged = [
            match
            for match in staged
            if re.search(
                rf"\({re.escape(match.group(3))} = {output_name}\)",
                generated[: match.start()],
            )
            and re.search(
                rf"\({re.escape(match.group(4))} = {output_capacity}\)",
                generated[: match.start()],
            )
        ]
        dispatches = direct + staged
        assert len(dispatches) == 1
        dispatch = dispatches[0]
        prefix = generated[: dispatch.start()]
        assert re.search(rf"\({re.escape(dispatch.group(1))} = input\)", prefix)
        assert re.search(rf"\({re.escape(dispatch.group(2))} = {input_capacity}\)", prefix)
    assert "global_values = doubled(input)" not in generated
    assert "Outputs.values = doubled(input)" not in generated
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_gpu_fixed_struct_and_static_array_inputs_keep_physical_capacity(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "#include <btrc_gpu.h>\n"
        "class StaticInput { class int[] values = {1, 2}; } "
        "struct StructInput { int values[2]; }; "
        "@gpu int[] doubled(int[] values) { int i = gpu_id(); "
        "return values[i] * 2; } int main() { "
        "StructInput input; input.values[0] = 3; input.values[1] = 5; "
        "int static_output[2]; int struct_output[2]; "
        "static_output = doubled(StaticInput.values); "
        "struct_output = doubled(input.values); "
        "return static_output[0] == 2 && static_output[1] == 4 "
        "&& struct_output[0] == 6 && struct_output[1] == 10 ? 0 : 1; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    assert "sizeof(StaticInput_values)" in generated
    assert "sizeof(input.values)" in generated
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_array_kernel_may_write_complete_global_and_block_extern_arrays(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "#include <btrc_gpu.h>\n"
        "extern int global_output[2]; "
        "@gpu int[] doubled(int[] values) { int i = gpu_id(); "
        "return values[i] * 2; } int main() { "
        "extern int block_output[2]; "
        "global_output = doubled(block_output); "
        "block_output = doubled(global_output); "
        "return global_output[0] == 2 && global_output[1] == 4 "
        "&& block_output[0] == 4 && block_output[1] == 8 ? 0 : 1; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    assert "extern int global_output[2];" in generated
    assert "extern int block_output[2];" in generated
    companion = tmp_path / "gpu_extern_outputs.c"
    companion.write_text("int global_output[2] = {1, 2};\nint block_output[2] = {1, 2};\n")
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        extra_sources=(companion,),
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_gpu_heap_collection_input_is_evaluated_once_and_passes_data_length(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "#include <btrc_gpu.h>\n"
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } } "
        "int calls = 0; Vector<int> acquire(Vector<int> value) { "
        "calls++; return value; } "
        "@gpu void bump(int[] values) { int i = gpu_id(); values[i] += 1; } "
        "int main() { int[] raw = {1, 2}; Vector<int> value = "
        "new Vector<int>(raw, 2); bump(acquire(value)); "
        "return calls == 1 && raw[0] == 2 && raw[1] == 3 ? 0 : 1; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    match = re.search(
        r"btrc_Vector_int\* (__(?:(?:btrc_)?gpu_arg|btrc_operand)_\d+)",
        generated,
    )
    assert match is not None
    stable = match.group(1)
    assert generated.count("acquire(value)") == 1
    assert f"{stable}->data" in generated
    assert f"{stable}->len" in generated
    stable_at = generated.index(f"{stable} = acquire(value)")
    data_at = generated.index(f"{stable}->data", stable_at)
    length_at = generated.index(f"{stable}->len", data_at)
    data = re.search(
        rf"\(([A-Za-z_][A-Za-z0-9_]*) = {re.escape(stable)}->data\)",
        generated[stable_at:],
    )
    length = re.search(
        rf"\(([A-Za-z_][A-Za-z0-9_]*) = {re.escape(stable)}->len\)",
        generated[stable_at:],
    )
    assert data is not None and length is not None
    dispatch_at = _gpu_dispatch_index(
        generated,
        length_at,
        rf"{re.escape(data.group(1))}, {re.escape(length.group(1))}",
    )
    release_at = generated.index("__btrc_arc_release", dispatch_at)
    assert stable_at < data_at < length_at < dispatch_at < release_at
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("status", "diagnostic"),
    [
        (1, "GPU array index out of bounds\n"),
        (2, "Division by zero\n"),
        (3, "Modulo by zero\n"),
        (4, "Integer division overflow\n"),
    ],
)
def test_checked_shader_status_cleans_up_then_exits_with_exact_diagnostic(
    btrcc_driver: Path,
    tmp_path: Path,
    status: int,
    diagnostic: str,
) -> None:
    generated = _lower_fixture(btrcc_driver, "void")
    cleanup = generated.index("btrc_gpu_buffer_destroy")
    failure = generated.index(f"status == {status}")
    assert cleanup < failure
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_checked_stub.c",
        f"STUB_STATUS_CODE={status}",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 1
    assert result.stderr == diagnostic


def test_status_readback_failure_after_submit_cleans_up_and_fails_closed(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_fixture(btrcc_driver, "void")
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_checked_stub.c",
        "STUB_FAIL_READBACK=1",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 1
    assert result.stderr == ("[btrc-gpu] GPU dispatch or result transfer failed after submission\n")


def test_dispatch_rejection_before_any_submit_uses_cpu_fallback(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_fixture(btrcc_driver, "void")
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_checked_stub.c",
        "STUB_DISPATCH_FAIL=1",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""


def test_unknown_shader_status_fails_closed_with_exact_diagnostic(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_fixture(btrcc_driver, "void")
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_checked_stub.c",
        "STUB_STATUS_CODE=99",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 1
    assert result.stderr == ("[btrc-gpu] GPU kernel reported an unknown failure status\n")


@pytest.mark.parametrize(
    ("operation", "divisor", "diagnostic"),
    [
        ("xs[i + 1] = 7", "1", "GPU array index out of bounds\n"),
        ("xs[i] = xs[i] / divisor", "0", "Division by zero\n"),
        ("xs[i] = xs[i] % divisor", "0", "Modulo by zero\n"),
        ("xs[i] = xs[i] / divisor", "-1", "Integer division overflow\n"),
    ],
)
def test_cpu_fallback_checked_failures_match_language_diagnostics(
    btrcc_driver: Path,
    tmp_path: Path,
    operation: str,
    divisor: str,
    diagnostic: str,
) -> None:
    generated = _lower_source(
        btrcc_driver,
        tmp_path,
        "@gpu void checked(int[] xs, int divisor) { "
        f"int i = gpu_id(); {operation}; }} "
        "int main() { int[] xs = {-2147483648}; "
        f"checked(xs, {divisor}); return 0; }}",
    )
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 1
    assert result.stderr == diagnostic


def test_cpu_fallback_min_mod_minus_one_is_defined_zero(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        btrcc_driver,
        tmp_path,
        "@gpu void checked(int[] xs, int divisor) { int i = gpu_id(); "
        "xs[i] = xs[i] % divisor; } int main() { "
        "int[] xs = {-2147483648}; checked(xs, -1); return xs[0]; }",
    )
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


def test_round_uses_gpu_float_signature_and_hosted_double_signature(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        semantic_btrcc,
        tmp_path,
        "#include <math.h>\n"
        "double hostedRound(double value) { return round(value); } "
        "@gpu void rounded(float[] xs) { int i = gpu_id(); "
        "xs[i] = round(xs[i]); } int main() { float[] xs = {-1.5}; "
        "rounded(xs); return hostedRound(2.5) == 3.0 && xs[0] == -2.0 "
        "? 0 : 1; }",
    )
    assert "roundf(" in generated
    assert "round(" in generated
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


def test_cpu_fallback_return_only_ends_the_current_invocation(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        btrcc_driver,
        tmp_path,
        "@gpu void early(int[] xs) { int i = gpu_id(); "
        "if (i == 0) { return; } xs[i] += 1; } int main() { "
        "int[] xs = {1, 2}; early(xs); "
        "return xs[0] == 1 && xs[1] == 3 ? 0 : 1; }",
    )
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


def test_hosted_macro_parameter_names_cross_gpu_host_and_cpu_paths(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        semantic_btrcc,
        tmp_path,
        "@gpu void update(int[] stdin, int stdout, int stderr) { "
        "int i = gpu_id(); stdin[i] += stdout + stderr; } "
        "int main() { int[] values = {1}; "
        "update(stderr=3, stdin=values, stdout=2); "
        "return values[0] == 6 ? 0 : 1; }",
    )
    assert "__btrc_source_stdin" in generated
    assert "__btrc_source_stdout" in generated
    assert "__btrc_source_stderr" in generated
    stderr_assignment = re.search(r"\((__gpu_arg_\d+) = 3\)", generated)
    input_assignment = re.search(r"\((__gpu_arg_\d+) = values\)", generated)
    stdout_assignment = re.search(r"\((__gpu_arg_\d+) = 2\)", generated)
    length_assignment = re.search(r"\((__gpu_len_\d+) = [^)]+\)", generated)
    assert stderr_assignment is not None
    assert input_assignment is not None
    assert stdout_assignment is not None
    assert length_assignment is not None
    stderr_value = stderr_assignment.group(1)
    input_value = input_assignment.group(1)
    stdout_value = stdout_assignment.group(1)
    input_length = length_assignment.group(1)
    dispatch = _gpu_dispatch_index(
        generated,
        arguments=(rf"{input_value}, {input_length}, {stdout_value}, {stderr_value}"),
    )
    assert stderr_assignment.start() < input_assignment.start() < stdout_assignment.start() < dispatch
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_type_named_parameters_cross_gpu_host_and_cpu_paths(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = """
        #include <btrc_gpu.h>

        class values {}
        class scale {}

        @gpu
        void update(int[] values, int scale) {
            int index = gpu_id();
            values[index] += scale;
        }

        int main() {
            values valuesMarker = new values();
            scale scaleMarker = new scale();
            int[] data = {1};
            update(data, 2);
            bool valid = data[0] == 3;
            delete scaleMarker;
            delete valuesMarker;
            return valid ? 0 : 1;
        }
    """
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    assert "int* __btrc_source_values" in generated
    assert "int __btrc_source_scale" in generated
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


def test_contextual_float_results_match_wgsl_and_cpu_fallback(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        btrcc_driver,
        tmp_path,
        "@gpu void update(float[] xs, bool choose) { int i = gpu_id(); "
        "var adjusted = choose ? -(xs[i] + 1.0) : (float)sqrt(4.0f); "
        "xs[i] = adjusted; } int main() { float[] xs = {2.0f}; "
        "update(xs, true); return xs[0] == -3.0f ? 0 : 1; }",
    )
    match = re.search(r'static char\* update_wgsl = ("(?:\\.|[^"])*");', generated)
    assert match is not None
    shader = ast.literal_eval(match.group(1))
    assert "1.0f" not in shader
    assert "4.0f" not in shader
    assert "1.0" in shader and "sqrt(4.0)" in shader
    assert "1.0f" in generated and "sqrtf(4.0f)" in generated
    assert "float adjusted" in generated
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


@pytest.mark.parametrize("literal", ["1e100", "1e-50"])
def test_contextual_float_rejects_f32_overflow_and_underflow(
    btrcc_driver: Path,
    tmp_path: Path,
    literal: str,
) -> None:
    source = tmp_path / "invalid_gpu_float.btrc"
    source.write_text(
        "@gpu void invalid(float[] xs) { int i = gpu_id(); "
        f"xs[i] = {literal}; }} int main() {{ float[] xs = {{1.0f}}; "
        "invalid(xs); return 0; }"
    )
    result = _run([str(btrcc_driver), "--no-stdlib", str(source)], timeout=120)
    assert result.returncode == 1
    assert "floating literal is outside the WGSL f32 range" in result.stderr


def test_named_and_default_gpu_arguments_preserve_declared_parameter_order(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        semantic_btrcc,
        tmp_path,
        "int trace = 0; int defaultCalls = 0; "
        "int mark(int value) { trace = trace * 10 + value; return value; } "
        "int defaultScale() { defaultCalls++; trace = trace * 10 + 8; return 2; } "
        "@gpu void affine(int[] xs, int scale = defaultScale(), "
        "int bias = 1, int extra = 0) { int i = gpu_id(); "
        "xs[i] = xs[i] * scale + bias + extra; } "
        "int main() { int[] xs = {4}; "
        "affine(xs, extra=mark(4), bias=mark(3)); "
        "return xs[0] == 15 && trace == 438 && defaultCalls == 1 ? 0 : 1; }",
    )
    assert generated.count("mark(4)") == 1
    assert generated.count("mark(3)") == 1
    explicit_extra = generated.index("= mark(4)")
    explicit_bias = generated.index("= mark(3)", explicit_extra)
    default_call = generated.index("__btrc_default_affine_2", explicit_bias)
    dispatch = _gpu_dispatch_index(generated, default_call)
    assert explicit_extra < explicit_bias < default_call < dispatch
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_named_gpu_arguments_preserve_source_order_for_direct_call_forms(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "int trace = 0; int mark(int value) { trace = trace * 10 + value; return value; } "
        "@gpu void touch(int[] values, int first, int second) { "
        "int i = gpu_id(); values[i] += first + second; } "
        "@gpu int[] add(int[] values, int first, int second) { "
        "int i = gpu_id(); return values[i] + first + second; } "
        "int main() { int[] values = {1}; "
        "touch(second=mark(2), values=values, first=mark(1)); "
        "if (trace != 21 || values[0] != 4) { return 1; } "
        "trace = 0; int[] declared = "
        "add(second=mark(4), values=values, first=mark(3)); "
        "if (trace != 43 || declared[0] != 11) { return 2; } "
        "trace = 0; int assigned[1]; assigned = "
        "add(second=mark(6), values=declared, first=mark(5)); "
        "return trace == 65 && assigned[0] == 22 ? 0 : 3; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_generic_direct_gpu_outputs_preserve_named_argument_source_order(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "int trace = 0; int mark(int value) { trace = trace * 10 + value; return value; } "
        "@gpu int[] add(int[] values, int first, int second) { "
        "int i = gpu_id(); return values[i] + first + second; } "
        "class Harness<T> { public int run() { int[] values = {1}; "
        "int[] declared = add(second=mark(2), values=values, first=mark(1)); "
        "if (trace != 21 || declared[0] != 4) { return 1; } "
        "trace = 0; int assigned[1]; assigned = "
        "add(second=mark(4), values=declared, first=mark(3)); "
        "return trace == 43 && assigned[0] == 11 ? 0 : 2; } } "
        "int main() { Harness<int> harness = new Harness<int>(); "
        "int result = harness.run(); delete harness; return result; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_capacity_known_omitted_gpu_array_default_has_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "int defaults[2] = {3, 5}; "
        "@gpu int[] copy(int[] values = defaults) { "
        "int i = gpu_id(); return values[i]; } "
        "int main() { int[] output = copy(); "
        "return output[0] == 3 && output[1] == 5 ? 0 : 1; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


def test_selfhost_rejects_unknown_capacity_gpu_array_default_before_ir(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "unknown_gpu_default.btrc"
    source.write_text(
        "extern int defaults[]; "
        "@gpu int[] copy(int[] values = defaults) { "
        "int i = gpu_id(); return values[i]; } "
        "int main() { int[] output = copy(); return output[0]; }"
    )
    result = _run(
        [str(semantic_btrcc), "--no-stdlib", str(source)],
        timeout=120,
    )
    assert result.returncode == 1
    assert "Default for parameter 'values' has no provable readable GPU buffer capacity" in result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_scalar_only_gpu_array_result_uses_one_dispatch_element(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "@gpu int[] fill(int value) { return value; } "
        "int main() { int[] output = fill(7); "
        "return output[0] == 7 ? 0 : 1; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_owned_gpu_output_receiver_lives_through_dispatch(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "#include <assert.h>\n"
        "int drops = 0; class Holder { public int values[1]; "
        "public Holder() { self.values[0] = 0; } "
        "public void __del__() { assert(self.values[0] == 7); drops++; } } "
        "Holder makeHolder() { return new Holder(); } "
        "@gpu int[] copy(int[] input) { int i = gpu_id(); return input[i]; } "
        "int main() { int[] input = {7}; try { "
        "makeHolder().values = copy(input); "
        "} catch (string error) { return 2; } "
        "assert(drops == 1); return 0; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    assert generated.count("makeHolder()") == 1
    main = generated[generated.index("int main(") :]
    producer = re.search(
        r"\(([A-Za-z_][A-Za-z0-9_]*) = makeHolder\(\)\)",
        main,
    )
    assert producer is not None
    stable = producer.group(1)
    assignment = producer.start()
    data = main.index(f"{stable}->values", producer.end())
    dispatch = _gpu_dispatch_index(main, data)
    clear = main.index(f"{stable} = NULL", data)
    release = main.index("__btrc_arc_release", clear)
    assert f"__btrc_arc_retain({stable})" not in main
    cleanup_match = re.search(
        rf"__btrc_register_cleanup\([^;]*{re.escape(stable)}",
        main,
    )
    assert cleanup_match is not None
    cleanup = cleanup_match.start()
    assert main.count(f"{stable} = makeHolder()") == 1
    assert max(assignment, cleanup) < data < dispatch < clear < release
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        sanitize=True,
    )
    result = _run(
        [str(binary)],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=15,
    )
    assert result.returncode == 0


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_borrowed_fixed_array_gpu_input_is_pinned_and_snapshotted(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "#include <assert.h>\n"
        "int drops = 0; class Owner { public int a[1]; "
        "public Owner(int value) { self.a[0] = value; } "
        "public void __del__() { drops++; } } "
        "class Holder { public Owner owner; "
        "public Holder() { self.owner = new Owner(7); } "
        "public int replace() { self.owner = new Owner(9); return 0; } "
        "public int run() { int[] result = "
        "copy(self.owner.a, self.replace()); return result[0]; } } "
        "@gpu int[] copy(int[] values, int ignored) { "
        "int i = gpu_id(); return values[i]; } "
        "int main() { Holder holder = new Holder(); "
        "int value = holder.run(); assert(value == 7); assert(drops == 1); "
        "delete holder; assert(drops == 2); return 0; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    if frontend == "btrc":
        run_start = generated.index("int Holder_run(Holder* self) {")
        run_end = generated.index("\nint main(", run_start)
        run_body = generated[run_start:run_end]
        root_match = re.search(r"Owner\* (__btrc_operand_\d+);", run_body)
        kept_match = re.search(r"Owner\* (__btrc_kept_operand_\d+);", run_body)
        assert root_match is not None and kept_match is not None
        root = root_match.group(1)
        kept = kept_match.group(1)
        root_assignment = run_body.index(f"{root} = self->owner")
        retain = run_body.index(f"__btrc_arc_retain({root})", root_assignment)
        projection = run_body.index(f"{root}->a", retain)
        later_effect = run_body.index("Holder_replace(self)", projection)
        dispatch = _gpu_dispatch_index(run_body, later_effect)
        clear = run_body.index(f"{kept} = NULL", dispatch)
        release = run_body.index("__btrc_arc_release", clear)
        assert run_body.count("self->owner") == 1
        assert run_body.count("Holder_replace(self)") == 1
        assert root_assignment < retain < projection < later_effect < dispatch < clear < release
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        sanitize=True,
    )
    result = _run(
        [str(binary)],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_borrowed_fixed_array_gpu_input_projection_is_exception_safe(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = (
        "#include <assert.h>\n"
        "int drops = 0; class Owner { public int values[1]; "
        "public Owner(int value) { self.values[0] = value; } "
        "public void __del__() { drops++; } } "
        "class Holder { public Owner owner; "
        "public Holder() { self.owner = new Owner(7); } "
        "public int replace() { self.owner = new Owner(9); return 0; } "
        "public int run() { try { int[] result = "
        "copy(self.owner.values, self.replace()); return result[0]; "
        "} catch (string error) { return -1; } } } "
        "@gpu int[] copy(int[] values, int ignored) { "
        "int i = gpu_id(); return values[i]; } "
        "int main() { Holder holder = new Holder(); int result = holder.run(); "
        "assert(result == 7); assert(drops == 1); delete holder; "
        "assert(drops == 2); return 0; }"
    )
    generated = _lower_source(semantic_btrcc, tmp_path, source)
    run_start = generated.index("int Holder_run(Holder* self) {")
    run_end = generated.index("\nint main(", run_start)
    run_body = generated[run_start:run_end]
    kept_match = re.search(r"Owner\*(?: volatile)? (__btrc_kept_operand_\d+);", run_body)
    assert kept_match is not None
    kept = kept_match.group(1)
    registration = run_body.index("__btrc_register_cleanup")
    projection = run_body.index("->values", registration)
    later_effect = run_body.index("Holder_replace(self)", projection)
    dispatch = _gpu_dispatch_index(run_body, later_effect)
    clear = run_body.index(f"{kept} = NULL", dispatch)
    release = run_body.index("__btrc_arc_release", clear)
    assert run_body.count("self->owner") == 1
    assert registration < projection < later_effect < dispatch < clear < release
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        sanitize=True,
    )
    result = _run(
        [str(binary)],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_owned_fixed_array_gpu_input_projection_lives_through_dispatch(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = (
        "#include <assert.h>\n"
        "int drops = 0; int makes = 0; int effects = 0; "
        "class Owner { public int values[1]; "
        "public Owner(int value) { self.values[0] = value; } "
        "public void __del__() { drops++; } } "
        "Owner makeOwner() { makes++; return new Owner(7); } "
        "int laterEffect() { effects++; return 0; } "
        "@gpu int[] copy(int[] values, int ignored) { "
        "int i = gpu_id(); return values[i]; } "
        "int main() { try { int[] result = "
        "copy(makeOwner().values, laterEffect()); "
        "assert(result[0] == 7); "
        "} catch (string error) { return 2; } "
        "assert(makes == 1); assert(effects == 1); assert(drops == 1); "
        "return 0; }"
    )
    generated = _lower_source(semantic_btrcc, tmp_path, source)
    main_start = generated.index("int main(")
    main_body = generated[main_start:]
    root_match = re.search(r"Owner\*(?: volatile)? (__btrc_operand_\d+);", main_body)
    assert root_match is not None
    root = root_match.group(1)
    make = main_body.index("makeOwner()")
    projection = main_body.index(f"{root}->values", make)
    later_effect = main_body.index("laterEffect()", projection)
    dispatch = _gpu_dispatch_index(main_body, later_effect)
    clear = main_body.index(f"{root} = NULL", dispatch)
    release = main_body.index("__btrc_arc_release", clear)
    assert main_body.count("makeOwner()") == 1
    assert main_body.count("laterEffect()") == 1
    assert f"__btrc_arc_retain({root})" not in main_body
    assert "__btrc_register_cleanup" in main_body
    assert make < projection < later_effect < dispatch < clear < release
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        sanitize=True,
    )
    result = _run(
        [str(binary)],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_borrowed_collection_gpu_input_is_pinned_and_snapshotted(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "int drops = 0; int oldRaw[1] = {7}; int newRaw[1] = {9}; "
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } "
        "public void __del__() { drops++; } } "
        "class Holder { public Vector<int> values; "
        "public Holder() { self.values = new Vector<int>(oldRaw, 1); } "
        "public int replace() { "
        "self.values = new Vector<int>(newRaw, 1); return 0; } "
        "public int run() { int[] result = "
        "copy(self.values, self.replace()); return result[0]; } } "
        "@gpu int[] copy(int[] values, int ignored) { "
        "int i = gpu_id(); return values[i]; } "
        "int main() { Holder holder = new Holder(); int result = holder.run(); "
        "bool ok = result == 7 && drops == 1; delete holder; "
        "return ok && drops == 2 ? 0 : 1; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        sanitize=True,
    )
    result = _run(
        [str(binary)],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_borrowed_gpu_output_receiver_uses_a_void_result_boundary(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "#include <assert.h>\n"
        "class Holder { public int values[1]; "
        "public Holder() { self.values[0] = 0; } } "
        "@gpu int[] copy(int[] input) { int i = gpu_id(); return input[i]; } "
        "int main() { int[] input = {7}; Holder holder = new Holder(); "
        "holder.values = copy(input); assert(holder.values[0] == 7); "
        "delete holder; return 0; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    main = generated[generated.index("int main(") :]
    receivers = re.findall(
        r"\(([A-Za-z_][A-Za-z0-9_]*) = holder\)",
        main,
    )
    receivers = [receiver for receiver in receivers if f"{receiver}->values" in main]
    assert len(receivers) == 1
    stable = receivers[0]
    assignment = main.index(f"({stable} = holder)")
    retain = main.index(f"__btrc_arc_retain({stable})", assignment)
    data = main.index(f"{stable}->values", retain)
    kept_match = re.search(
        rf"\(([A-Za-z_][A-Za-z0-9_]*) = {re.escape(stable)}\)",
        main[retain:data],
    )
    cleanup_owner = kept_match.group(1) if kept_match is not None else stable
    dispatch = _gpu_dispatch_index(main, data)
    clear = main.index(f"{cleanup_owner} = NULL", dispatch)
    release = main.index("__btrc_arc_release", clear)
    assert main.count(f"{stable} = holder") == 1
    assert assignment < retain < data < dispatch < clear < release
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_gpu_vla_capacity_does_not_replay_the_declared_bound(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "int calls = 0; int size() { calls++; return 2; } "
        "@gpu void bump(int[] values) { int i = gpu_id(); values[i]++; } "
        "int main() { int values[size()]; values[0] = 1; values[1] = 2; "
        "bump(values); bump(values); "
        "return calls == 1 && values[0] == 3 && values[1] == 4 ? 0 : 1; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    assert generated.count("size()") == 1
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_owned_gpu_collection_input_is_released_after_dispatch(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "#include <assert.h>\n"
        "int drops = 0; int raw[1] = {7}; "
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } "
        "public void __del__() { drops++; } } "
        "Vector<int> makeValues() { return new Vector<int>(raw, 1); } "
        "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
        "int main() { int[] output = copy(makeValues()); "
        "assert(output[0] == 7); assert(drops == 1); return 0; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    assert generated.count("makeValues()") == 1
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_owned_custom_property_gpu_output_is_consumed_without_a_leak(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "#include <assert.h>\n"
        "int drops = 0; int getterCalls = 0; int raw[1] = {0}; "
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } "
        "public void __del__() { drops++; } } "
        "class Holder { public Vector<int> output { get { "
        "getterCalls++; return new Vector<int>(raw, 1); } } } "
        "@gpu int[] copy(int[] input) { int i = gpu_id(); return input[i]; } "
        "int main() { int[] input = {7}; Holder holder = new Holder(); "
        "holder.output = copy(input); assert(raw[0] == 7); "
        "assert(getterCalls == 1); assert(drops == 1); delete holder; return 0; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    if frontend == "btrc":
        main_start = generated.index("int main(")
        main_body = generated[main_start:]
        target_match = re.search(
            r"Vector_int\*(?: volatile)? (__gpu_output_target_\d+) = NULL;",
            main_body,
        )
        assert target_match is not None
        target = target_match.group(1)
        getter = main_body.index("Holder_get_output(")
        data = main_body.index(f"{target}->data", getter)
        length = main_body.index(f"{target}->len", data)
        dispatch = _gpu_dispatch_index(main_body, length)
        clear = main_body.index(f"{target} = NULL", dispatch)
        release = main_body.index("__btrc_arc_release", clear)
        assert main_body.count("Holder_get_output(") == 1
        assert f"__btrc_arc_retain({target})" not in main_body
        assert getter < data < length < dispatch < clear < release
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0, result.stderr


def test_borrowed_auto_property_gpu_output_is_pinned_before_rhs_effect(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = (
        "#include <assert.h>\n"
        "int drops = 0; int oldRaw[1] = {0}; int newRaw[1] = {0}; "
        "int inputRaw[1] = {7}; "
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } "
        "public void __del__() { drops++; } } "
        "class Holder { public Vector<int> output { get; set; } "
        "public Vector<int> input; "
        "public Holder() { self.output = new Vector<int>(oldRaw, 1); "
        "self.input = new Vector<int>(inputRaw, 1); } "
        "public Vector<int> mutate() { "
        "self.output = new Vector<int>(newRaw, 1); return self.input; } "
        "public int run() { try { self.output = copy(self.mutate()); "
        "return oldRaw[0] == 7 && newRaw[0] == 0 ? 0 : 1; "
        "} catch (string error) { return 2; } } } "
        "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
        "int main() { Holder holder = new Holder(); int result = holder.run(); "
        "assert(result == 0); assert(drops == 1); delete holder; "
        "assert(drops == 3); return 0; }"
    )
    generated = _lower_source(semantic_btrcc, tmp_path, source)
    run_start = generated.index("int Holder_run(Holder* self) {")
    run_end = generated.index("\nint main(", run_start)
    run_body = generated[run_start:run_end]
    target_match = re.search(
        r"Vector_int\*(?: volatile)? (__gpu_output_target_\d+) = NULL;",
        run_body,
    )
    assert target_match is not None
    target = target_match.group(1)
    getter = run_body.index("Holder_get_output(self)")
    retain = run_body.index(f"__btrc_arc_retain({target})", getter)
    data = run_body.index(f"{target}->data", retain)
    length = run_body.index(f"{target}->len", data)
    later_effect = run_body.index("Holder_mutate(self)", length)
    dispatch = _gpu_dispatch_index(run_body, later_effect)
    clear = run_body.index(f"{target} = NULL", dispatch)
    release = run_body.index("__btrc_arc_release", clear)
    assert run_body.count("Holder_get_output(self)") == 1
    assert run_body.count("Holder_mutate(self)") == 1
    assert "__btrc_register_cleanup" in run_body
    assert getter < retain < data < length < later_effect < dispatch < clear < release
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        sanitize=True,
    )
    result = _run(
        [str(binary)],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_owned_receiver_custom_property_gpu_output_is_single_evaluation(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = (
        "#include <assert.h>\n"
        "int holderMakes = 0; int holderDrops = 0; "
        "int getterCalls = 0; int vectorDrops = 0; int raw[1] = {0}; "
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } "
        "public void __del__() { vectorDrops++; } } "
        "class Holder { public void __del__() { holderDrops++; } "
        "public Vector<int> output { get { getterCalls++; "
        "return new Vector<int>(raw, 1); } } } "
        "Holder makeHolder() { holderMakes++; return new Holder(); } "
        "@gpu int[] copy(int[] input) { int i = gpu_id(); return input[i]; } "
        "int main() { int[] input = {7}; try { "
        "makeHolder().output = copy(input); assert(raw[0] == 7); "
        "} catch (string error) { return 2; } "
        "assert(holderMakes == 1); assert(holderDrops == 1); "
        "assert(getterCalls == 1); assert(vectorDrops == 1); return 0; }"
    )
    generated = _lower_source(semantic_btrcc, tmp_path, source)
    main_start = generated.index("int main(")
    main_body = generated[main_start:]
    target_match = re.search(
        r"Vector_int\*(?: volatile)? (__gpu_output_target_\d+) = NULL;",
        main_body,
    )
    assert target_match is not None
    target = target_match.group(1)
    make = main_body.index("makeHolder()")
    getter = main_body.index("Holder_get_output", make)
    dispatch = _gpu_dispatch_index(main_body, getter)
    clear = main_body.index(f"{target} = NULL", dispatch)
    release = main_body.index("__btrc_arc_release", clear)
    assert main_body.count("makeHolder()") == 1
    assert main_body.count("Holder_get_output") == 1
    assert f"__btrc_arc_retain({target})" not in main_body
    assert "__btrc_register_cleanup" in main_body
    assert make < getter < dispatch < clear < release
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        sanitize=True,
    )
    result = _run(
        [str(binary)],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_gpu_dependent_defaults_bind_stable_earlier_parameters(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "@gpu int[] add(int[] values, int value = 2, int plus = value + 1) { "
        "int i = gpu_id(); return values[i] + value + plus; } "
        "int main() { int[] values = {1}; int[] declared = add(values, value=3); "
        "int assigned[1]; assigned = add(declared, value=4); "
        "return declared[0] == 8 && assigned[0] == 17 ? 0 : 1; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_gpu_array_default_inherits_an_earlier_buffer_snapshot(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } } "
        "@gpu int[] copy(int[] source, int[] selected = source) { "
        "int i = gpu_id(); return selected[i]; } "
        "int main() { int[] raw = {3, 5}; Vector<int> values = "
        "new Vector<int>(raw, 2); int[] output = copy(values); "
        "int[] explicit = copy(values, values); delete values; "
        "return output[0] == 3 && output[1] == 5 "
        "&& explicit[0] == 3 && explicit[1] == 5 ? 0 : 1; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
@pytest.mark.parametrize("generic", [False, True])
def test_empty_gpu_result_keeps_zero_logical_length_when_chained(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
    generic: bool,
) -> None:
    body = (
        "int raw[1] = {42}; Vector<int> empty = new Vector<int>(raw, 0); "
        "int[] first = copy(empty); int output[1] = {99}; "
        "output = copy(first); delete empty; return output[0] == 99 ? 0 : 1;"
    )
    harness = (
        f"class Harness<T> {{ public int run() {{ {body} }} }} "
        "int main() { Harness<int> harness = new Harness<int>(); "
        "int result = harness.run(); delete harness; return result; }"
        if generic
        else f"int main() {{ {body} }}"
    )
    source = (
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } } "
        "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } " + harness
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_gpu_array_capacity_shadowing_is_lexically_scoped(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "@gpu void bump(int[] values) { int i = gpu_id(); values[i]++; } "
        "int main() { int values[2] = {1, 2}; { "
        "int values[5] = {1, 2, 3, 4, 5}; bump(values); "
        "if (values[4] != 6) { return 1; } } bump(values); "
        "return values[0] == 2 && values[1] == 3 ? 0 : 2; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        sanitize=True,
    )
    result = _run(
        [str(binary)],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_generic_embedded_class_array_is_a_gpu_input_and_output(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "class Box { public int values[2]; public Box() { "
        "self.values[0] = 3; self.values[1] = 5; } } "
        "@gpu int[] twice(int[] values) { "
        "int i = gpu_id(); return values[i] * 2; } "
        "class Harness<T> { public int run() { Box box = new Box(); "
        "int[] first = twice(box.values); box.values = twice(first); "
        "int result = box.values[0] + box.values[1]; "
        "delete box; return result; } } "
        "int main() { Harness<int> harness = new Harness<int>(); "
        "int result = harness.run(); delete harness; return result == 32 ? 0 : 1; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_temporary_fixed_array_gpu_projections_have_stable_storage(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "int drops = 0; class Box { public int values[1]; "
        "public Box() { self.values[0] = 7; } "
        "public void __del__() { drops++; } } "
        "struct ValueBox { int values[1]; }; "
        "ValueBox makeBox() { ValueBox box; box.values[0] = 9; return box; } "
        "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
        "int main() { int[] owned = copy((new Box()).values); "
        "int[] byValue = copy(makeBox().values); "
        "return owned[0] == 7 && byValue[0] == 9 && drops == 1 ? 0 : 1; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    assert generated.count("makeBox()") == 1
    if frontend == "btrc":
        root_match = re.search(
            r"(?:struct )?ValueBox (__btrc_operand_\d+);",
            generated,
        )
        assert root_match is not None
        root = root_match.group(1)
        assignment = generated.index(f"{root} = makeBox()")
        data = generated.index(f"{root}.values", assignment)
        length = generated.index(f"sizeof({root}.values)", data)
        dispatch = _gpu_dispatch_index(generated, length)
        assert generated.count(f"{root} = makeBox()") == 1
        assert f"__btrc_arc_retain({root})" not in generated
        assert f"__btrc_arc_release({root}" not in generated
        assert f"__btrc_arc_release_acyclic({root}" not in generated
        assert assignment < data < length < dispatch
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        sanitize=True,
    )
    result = _run(
        [str(binary)],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_gpu_collection_output_target_is_snapshotted_before_rhs_mutation(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "int oldRaw[1] = {0}; int newRaw[1] = {0}; int inputRaw[1] = {7}; "
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } } "
        "class Holder { public Vector<int> output; public Vector<int> input; "
        "public Holder() { self.output = new Vector<int>(oldRaw, 1); "
        "self.input = new Vector<int>(inputRaw, 1); } "
        "public Vector<int> mutate() { "
        "self.output = new Vector<int>(newRaw, 1); return self.input; } "
        "public int run() { self.output = copy(self.mutate()); "
        "return oldRaw[0] == 7 && newRaw[0] == 0 ? 0 : 1; } } "
        "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
        "int main() { Holder holder = new Holder(); int result = holder.run(); "
        "delete holder; return result; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    if frontend == "btrc":
        run_start = generated.index("int Holder_run(Holder* self) {")
        run_end = generated.index("\nint main(", run_start)
        run_body = generated[run_start:run_end]
        target_match = re.search(
            r"Vector_int\*(?: volatile)? (__gpu_output_target_\d+) = NULL;",
            run_body,
        )
        assert target_match is not None
        target = target_match.group(1)
        assignment = run_body.index(f"{target} = self->output")
        retain = run_body.index(f"__btrc_arc_retain({target})", assignment)
        data = run_body.index(f"{target}->data", retain)
        length = run_body.index(f"{target}->len", data)
        mutation = run_body.index("Holder_mutate(self)", length)
        dispatch = _gpu_dispatch_index(run_body, mutation)
        clear = run_body.index(f"{target} = NULL", dispatch)
        release = run_body.index("__btrc_arc_release", clear)
        assert run_body.count("self->output") == 1
        assert run_body.count("Holder_mutate(self)") == 1
        assert assignment < retain < data < length < mutation < dispatch < clear < release
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        sanitize=True,
    )
    result = _run(
        [str(binary)],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_owned_receiver_collection_field_gpu_output_is_single_evaluation(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = (
        "#include <assert.h>\n"
        "int holderMakes = 0; int holderDrops = 0; "
        "int vectorDrops = 0; int raw[1] = {0}; "
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } "
        "public void __del__() { vectorDrops++; } } "
        "class Holder { public Vector<int> output; "
        "public Holder() { self.output = new Vector<int>(raw, 1); } "
        "public void __del__() { holderDrops++; } } "
        "Holder makeHolder() { holderMakes++; return new Holder(); } "
        "@gpu int[] copy(int[] input) { int i = gpu_id(); return input[i]; } "
        "int main() { int[] input = {7}; try { "
        "makeHolder().output = copy(input); assert(raw[0] == 7); "
        "} catch (string error) { return 2; } "
        "assert(holderMakes == 1); assert(holderDrops == 1); "
        "assert(vectorDrops == 1); return 0; }"
    )
    generated = _lower_source(semantic_btrcc, tmp_path, source)
    main_start = generated.index("int main(")
    main_body = generated[main_start:]
    target_match = re.search(
        r"Vector_int\*(?: volatile)? (__gpu_output_target_\d+) = NULL;",
        main_body,
    )
    assert target_match is not None
    target = target_match.group(1)
    make = main_body.index("makeHolder()")
    data = main_body.index(f"{target}->data", make)
    dispatch = _gpu_dispatch_index(main_body, data)
    clear = main_body.index(f"{target} = NULL", dispatch)
    release = main_body.index("__btrc_arc_release", clear)
    assert main_body.count("makeHolder()") == 1
    assert f"__btrc_arc_retain({target})" not in main_body
    assert "__btrc_register_cleanup" in main_body
    assert make < data < dispatch < clear < release
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        sanitize=True,
    )
    result = _run(
        [str(binary)],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_gpu_fixed_array_output_projection_is_chosen_before_rhs_mutation(
    semantic_btrcc: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    source = (
        "int calls = 0; class Holder { public int values[1]; "
        "public Holder() { self.values[0] = 0; } } "
        "class Router { public Holder current; public Holder other; "
        "public Router() { self.current = new Holder(); self.other = new Holder(); } "
        "public Holder choose() { calls++; return self.current; } "
        "public int switchTarget() { self.current = self.other; return 0; } "
        "public int run() { Holder first = self.current; int[] input = {7}; "
        "self.choose().values = copy(input, self.switchTarget()); "
        "bool ok = first.values[0] == 7 && self.other.values[0] == 0 "
        "&& calls == 1; delete first; return ok ? 0 : 1; } } "
        "@gpu int[] copy(int[] values, int ignored) { "
        "int i = gpu_id(); return values[i]; } "
        "int main() { Router router = new Router(); int result = router.run(); "
        "delete router; return result; }"
    )
    generated = emit_c(source) if frontend == "python" else _lower_source(semantic_btrcc, tmp_path, source)
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_unavailable_stub.c",
        sanitize=True,
    )
    result = _run(
        [str(binary)],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(NAGA is None, reason="naga WGSL validator is not installed")
def test_selfhost_checked_shader_validates_with_naga(
    btrcc_driver: Path,
) -> None:
    result = _run(
        [
            str(btrcc_driver),
            "--no-stdlib",
            str(FIXTURES / "gpu_checked_semantics.btrc"),
        ],
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    match = re.search(
        r'static char\* checked_wgsl = ("(?:\\.|[^"])*");',
        result.stdout,
    )
    assert match is not None
    shader = ast.literal_eval(match.group(1))
    validated = subprocess.run(
        [NAGA, "--stdin-file-path", "generated.wgsl"],
        input=shader,
        capture_output=True,
        text=True,
    )
    assert validated.returncode == 0, validated.stderr


@pytest.mark.skipif(NAGA is None, reason="naga WGSL validator is not installed")
def test_selfhost_compound_assignment_shader_validates_with_naga(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        btrcc_driver,
        tmp_path,
        "@gpu void compound(int[] xs, bool toggle) { int i = gpu_id(); "
        "int shift = 1; bool flag = toggle; xs[i] <<= shift; flag ^= true; "
        "xs[i] /= 2; xs[i] %= 3; } int main() { int[] xs = {8}; "
        "compound(xs, true); return 0; }",
    )
    match = re.search(r'static char\* compound_wgsl = ("(?:\\.|[^"])*");', generated)
    assert match is not None
    shader = ast.literal_eval(match.group(1))
    assert "u32(" in shader
    assert " != true" in shader
    assert "atomicMax(&btrc_status.code, 2u)" in shader
    assert "atomicMax(&btrc_status.code, 3u)" in shader
    validated = subprocess.run(
        [NAGA, "--stdin-file-path", "generated.wgsl"],
        input=shader,
        capture_output=True,
        text=True,
    )
    assert validated.returncode == 0, validated.stderr


def test_float_remainder_assignment_fails_closed(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid_gpu.btrc"
    source.write_text("@gpu void invalid(float[] xs) { int i = gpu_id(); xs[i] %= 2.0; } int main() { return 0; }")
    result = _run([str(btrcc_driver), "--no-stdlib", str(source)], timeout=120)
    assert result.returncode == 1
    assert "GPU remainder assignment requires integer operands" in result.stderr
