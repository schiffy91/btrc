"""Fallible fixed ownership, stable borrows, and typed payload contracts."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python import Compiler, CompilerOptions
from src.compiler.python.ir.lowering.lowerer import IRLowerer

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _emit_with_stdlib(source: str) -> str:
    compiler = Compiler()
    options = CompilerOptions(map_stdlib_positions=True)
    frontend = compiler.compile_frontend(
        source,
        "<owned-buffer-contract>",
        options,
        filename="OwnedBufferContract.btrc",
    )
    assert frontend.analyzed.errors == []
    source_map = frontend.source_bundle.source_map(
        split_spaces=bool(frontend.stdlib_source and frontend.user_program is not None)
    )
    module = IRLowerer(
        frontend.analyzed,
        source_file="OwnedBufferContract.btrc",
        source_map=source_map,
    ).lower()
    return compiler.pipeline.emit(compiler.pipeline.optimize(module, options))


def _body(generated: str, symbol: str) -> str:
    match = re.search(
        rf"\b{re.escape(symbol)}\([^;]*?\)\s*\{{(?P<body>.*?)\n\}}",
        generated,
        re.DOTALL,
    )
    assert match is not None
    return match.group("body")


RAW_CALLBACK_SOURCE = """
import std.OwnedBuffer;
struct CallbackContext { Atomic<uint>* counters; };
@realtime uint readCounter(void* opaque) {
    struct CallbackContext* context = (struct CallbackContext*)opaque;
    return context->counters[0].load(MemoryOrder.ACQUIRE);
}
int main() {
    struct OwnedBufferStorage* owner = null;
    if (OwnedBuffers.tryOpen(
            (size_t)2, sizeof(Atomic<uint>), &owner)
            != OWNED_BUFFER_OPENED) { return 1; }
    Atomic<uint>* counters = (Atomic<uint>*)OwnedBuffers.borrow(
        owner, sizeof(Atomic<uint>));
    if (counters == null) { OwnedBuffers.close(&owner); return 2; }
    counters[0].init(7u);
    counters[1].init(0u);
    struct CallbackContext context = {counters};
    uint value = readCounter(&context);
    OwnedBuffers.close(&owner);
    return value == 7u && owner == null ? 0 : 3;
}
"""


def test_callback_receives_only_a_stable_raw_borrow() -> None:
    generated = _emit_with_stdlib(RAW_CALLBACK_SOURCE)
    callback = _body(generated, "readCounter")
    forbidden = re.compile(
        r"\b(malloc|calloc|realloc|free|pthread_mutex|fprintf|printf|sleep|"
        r"__btrc_arc_retain|__btrc_arc_release)\b"
    )
    assert not forbidden.search(callback)
    borrow = _body(generated, "OwnedBuffers_borrow")
    assert not forbidden.search(borrow)
    assert "struct OwnedBufferStorage* storage" in generated
    assert "_Atomic(unsigned int)* counters" in generated


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_raw_atomic_owner_and_borrow_run_under_strict_c11(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    generated = _emit_with_stdlib(RAW_CALLBACK_SOURCE)
    source = tmp_path / "OwnedBufferRawCallback.c"
    executable = tmp_path / "OwnedBufferRawCallback"
    source.write_text(generated)
    built = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(executable)], check=False, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("failed_allocation", (1, 2))
def test_every_raw_owner_allocation_failure_returns_typed_oom(
    tmp_path: Path,
    c_compiler: str,
    failed_allocation: int,
) -> None:
    generated = (
        _emit_with_stdlib(
            """
        import std.OwnedBuffer;
        extern int ownedBufferTestLeaks();
        int main() {
            struct OwnedBufferStorage* owner = null;
            OwnedBufferOpenKind opened = OwnedBuffers.tryOpen(
                (size_t)4, sizeof(float), &owner);
            if (opened != OWNED_BUFFER_OUT_OF_MEMORY || owner != null) {
                OwnedBuffers.close(&owner);
                return 1;
            }
            return ownedBufferTestLeaks();
        }
        """
        )
        .replace("calloc(", "ownedBufferTestCalloc(")
        .replace("free(", "ownedBufferTestFree(")
    )
    hook = f"""
static unsigned int ownedBufferTestAllocation = 0u;
static unsigned int ownedBufferTestLiveAllocations = 0u;
static bool ownedBufferTestInvalidFree = false;
static void* ownedBufferTestCalloc(size_t count, size_t size) {{
    ownedBufferTestAllocation++;
    if (ownedBufferTestAllocation == {failed_allocation}u) {{ return NULL; }}
    if (count != 0u && size > SIZE_MAX / count) {{ return NULL; }}
    size_t total = count * size;
    void* memory = realloc(NULL, total);
    if (memory != NULL) {{
        memset(memory, 0, total);
        ownedBufferTestLiveAllocations++;
    }}
    return memory;
}}
static void ownedBufferTestFree(void* memory) {{
    if (memory == NULL) {{ return; }}
    if (ownedBufferTestLiveAllocations == 0u) {{
        ownedBufferTestInvalidFree = true;
    }} else {{
        ownedBufferTestLiveAllocations--;
    }}
    free(memory);
}}
int ownedBufferTestLeaks(void) {{
    return ownedBufferTestInvalidFree
        || ownedBufferTestLiveAllocations != 0u ? 1 : 0;
}}
"""
    insertion = generated.index("\n\n", generated.index("#include")) + 2
    generated = generated[:insertion] + hook + generated[insertion:]
    source = tmp_path / f"OwnedBufferOom{failed_allocation}.c"
    executable = tmp_path / f"OwnedBufferOom{failed_allocation}"
    source.write_text(generated)
    built = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(executable)], check=False, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr


def _errors(source: str) -> list[str]:
    frontend = Compiler().compile_frontend(
        source,
        "<owned-buffer-payload>",
        CompilerOptions(),
        filename="OwnedBufferPayload.btrc",
    )
    return frontend.analyzed.errors


def test_managed_payload_is_rejected_but_atomic_buffer_is_accepted() -> None:
    managed = _errors("import std.OwnedBuffer;\nint main() { OwnedBuffer<string> values; return 0; }")
    assert any(
        "OwnedBuffer<T> payload must be realtime POD without managed or atomic ownership" in error for error in managed
    )
    assert (
        _errors(
            "import std.OwnedBuffer;\n"
            "int main() { "
            "AtomicBuffer<uint> values = AtomicBuffer((size_t)1); "
            "Atomic<uint>* raw = values.borrow(); raw[0].init(0u); return 0; }"
        )
        == []
    )


def test_owned_atomic_exception_does_not_relax_inline_atomic_storage() -> None:
    errors = _errors("import std.array;\nint main() { Array<Atomic<uint>> values; return 0; }")
    assert any("cannot embed an Atomic<T> owner" in error for error in errors)

    owned_atomic = _errors("import std.OwnedBuffer;\nint main() { OwnedBuffer<Atomic<uint>> values; return 0; }")
    assert any(
        "OwnedBuffer<T> payload must be realtime POD without managed or atomic ownership" in error
        for error in owned_atomic
    )


def test_atomic_buffer_cannot_express_owner_copying() -> None:
    errors = _errors(
        "import std.OwnedBuffer;\n"
        "int main() { AtomicBuffer<uint> values = AtomicBuffer((size_t)1); "
        "values.get((size_t)0); return 0; }"
    )
    assert any("Class 'AtomicBuffer' has no field or method 'get'" in error for error in errors)

    invalid_payload = _errors("import std.OwnedBuffer;\nint main() { AtomicBuffer<string> values; return 0; }")
    assert any(
        "AtomicBuffer<T> payload must be bool, int, uint, or a raw pointer" in error for error in invalid_payload
    )
