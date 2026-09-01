"""Fallible ownership, borrowed realtime, FIFO, and concurrency proofs."""

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
    frontend = compiler.compile_frontend(source, "<spsc-contract>", options, filename="spsc_contract.btrc")
    assert frontend.analyzed.errors == []
    source_map = frontend.source_bundle.source_map(
        split_spaces=bool(frontend.stdlib_source and frontend.user_program is not None)
    )
    module = IRLowerer(
        frontend.analyzed,
        source_file="spsc_contract.btrc",
        source_map=source_map,
    ).lower()
    return compiler.pipeline.emit(compiler.pipeline.optimize(module, options))


def _body(generated: str, symbol: str) -> str:
    match = re.search(rf"\b{re.escape(symbol)}\([^;]*?\)\s*\{{(?P<body>.*?)\n\}}", generated, re.DOTALL)
    assert match is not None
    return match.group("body")


RAW_CALLBACK_SOURCE = """
import std.spsc;
struct Command { int kind; unsigned long long token; };
struct CallbackContext { struct SpscQueueStorage* commands; };
@realtime bool consume(void* opaque, struct Command* output) {
    struct CallbackContext* context = (struct CallbackContext*)opaque;
    return SpscQueues.tryPopBorrowed(context->commands, output);
}
int main() {
    struct SpscQueueStorage* commands = null;
    if (SpscQueues.tryOpen(4u, sizeof(struct Command), &commands)
            != SPSC_QUEUE_OPENED) { return 1; }
    struct Command sent = {7, 11ULL};
    struct Command received = {0, 0ULL};
    struct CallbackContext context = {commands};
    if (!SpscQueues.tryPushBorrowed(commands, &sent)) { return 2; }
    if (!consume(&context, &received)) { return 3; }
    SpscQueues.close(commands);
    return received.kind == 7 && received.token == 11ULL ? 0 : 4;
}
"""


def test_borrowed_operations_are_one_realtime_safe_composition() -> None:
    generated = _emit_with_stdlib(RAW_CALLBACK_SOURCE)
    forbidden = re.compile(
        r"\b(malloc|calloc|realloc|free|pthread_mutex|fprintf|printf|sleep|"
        r"__btrc_arc_retain|__btrc_arc_release)\b"
    )
    for symbol in ("SpscQueues_tryPushBorrowed", "SpscQueues_tryPopBorrowed"):
        body = _body(generated, symbol)
        assert not forbidden.search(body)
        assert "while (" not in body
        assert "for (" not in body
        assert "%" not in body
        assert "/" not in body
    copy_body = _body(generated, "btrcSpscCopy")
    assert copy_body.count("for (") == 1
    assert not forbidden.search(copy_body)
    assert "while (" not in copy_body

    push = _body(generated, "SpscQueues_tryPushBorrowed")
    pop = _body(generated, "SpscQueues_tryPopBorrowed")
    assert "memory_order_relaxed" in push
    assert "memory_order_acquire" in push
    assert "memory_order_release" in push
    assert "memory_order_relaxed" in pop
    assert "memory_order_acquire" in pop
    assert "memory_order_release" in pop
    assert "btrcSpscNextCursor" in push
    assert "btrcSpscNextCursor" in pop
    assert "const void* value" in generated
    assert "struct SpscQueueStorage* queue" in generated


def test_managed_typed_wrapper_delegates_to_the_canonical_storage() -> None:
    generated = _emit_with_stdlib(
        "import std.spsc;\nint main() { SpscQueue<int> q = new SpscQueue<int>(4u); "
        "int value = 0; q.tryPush(1); q.tryPop(&value); delete q; return value; }"
    )
    for method in ("tryPush", "tryPop"):
        body = _body(generated, f"btrc_SpscQueue_int_{method}")
        assert not re.search(r"\b(malloc|calloc|realloc|free|pthread_mutex|fprintf|printf|sleep)\b", body)
        assert f"SpscQueues_{'tryPushBorrowed' if method == 'tryPush' else 'tryPopBorrowed'}" in body
    assert generated.count("class SpscQueue") == 0


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_fifo_full_empty_wraparound_and_thread_stress(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    generated = _emit_with_stdlib(
        """
        import std.spsc;
        int main() {
            struct SpscQueueStorage* queue = null;
            if (SpscQueues.tryOpen(3u, sizeof(int), &queue)
                    != SPSC_QUEUE_OPENED) { return 12; }
            int output = -1;
            int one = 1;
            int two = 2;
            int three = 3;
            int four = 4;
            if (SpscQueues.tryPopBorrowed(queue, &output) || output != -1) { return 1; }
            if (!SpscQueues.tryPushBorrowed(queue, &one)
                    || !SpscQueues.tryPushBorrowed(queue, &two)
                    || !SpscQueues.tryPushBorrowed(queue, &three)) { return 2; }
            if (SpscQueues.tryPushBorrowed(queue, &four)) { return 3; }
            if (!SpscQueues.tryPopBorrowed(queue, &output) || output != 1
                    || !SpscQueues.tryPushBorrowed(queue, &four)) { return 4; }
            if (!SpscQueues.tryPopBorrowed(queue, &output) || output != 2) { return 5; }
            if (!SpscQueues.tryPopBorrowed(queue, &output) || output != 3) { return 6; }
            if (!SpscQueues.tryPopBorrowed(queue, &output) || output != 4) { return 7; }
            if (SpscQueues.tryPopBorrowed(queue, &output) || output != 4) { return 8; }
            Thread<int> producer = spawn(() => {
                for (int value = 0; value < 100000; value++) {
                    while (!SpscQueues.tryPushBorrowed(queue, &value)) {}
                }
                return 0;
            });
            Thread<int> consumer = spawn(() => {
                int expected = 0;
                while (expected < 100000) {
                    int value = -1;
                    if (SpscQueues.tryPopBorrowed(queue, &value)) {
                        if (value != expected) { return 9; }
                        expected++;
                    }
                }
                return 0;
            });
            int producerResult = producer.join();
            int consumerResult = consumer.join();
            SpscQueues.close(queue);
            return producerResult + consumerResult;
        }
        """
    )
    source = tmp_path / "spsc.c"
    executable = tmp_path / "spsc"
    source.write_text(generated)
    compiled = subprocess.run(
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
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run([str(executable)], check=False, capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stderr


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("failed_allocation", (1, 2, 3))
def test_every_allocation_failure_returns_typed_oom(
    tmp_path: Path,
    c_compiler: str,
    failed_allocation: int,
) -> None:
    generated = _emit_with_stdlib(
        """
        import std.spsc;
        int main() {
            struct SpscQueueStorage* queue = null;
            SpscQueueOpenKind opened = SpscQueues.tryOpen(
                4u, sizeof(int), &queue);
            if (opened != SPSC_QUEUE_OUT_OF_MEMORY || queue != null) {
                if (queue != null) { SpscQueues.close(queue); }
                return 1;
            }
            return 0;
        }
        """
    ).replace("calloc(", "spscTestCalloc(")
    allocation_hook = f"""
static unsigned int spscTestAllocation = 0u;
static void* spscTestCalloc(size_t count, size_t size) {{
    spscTestAllocation++;
    if (spscTestAllocation == {failed_allocation}u) {{ return NULL; }}
    if (count != 0u && size > SIZE_MAX / count) {{ return NULL; }}
    size_t total = count * size;
    void* memory = realloc(NULL, total);
    if (memory != NULL) {{ memset(memory, 0, total); }}
    return memory;
}}
"""
    insertion = generated.index("\n\n", generated.index("#include")) + 2
    generated = generated[:insertion] + allocation_hook + generated[insertion:]
    source = tmp_path / f"spsc-oom-{failed_allocation}.c"
    executable = tmp_path / f"spsc-oom-{failed_allocation}"
    source.write_text(generated)
    compiled = subprocess.run(
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
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run([str(executable)], check=False, capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stderr


def test_managed_payload_is_rejected_before_specialization() -> None:
    compiler = Compiler()
    frontend = compiler.compile_frontend(
        "import std.spsc;\nint main() { SpscQueue<string> queue; return 0; }",
        "<spsc-managed>",
        CompilerOptions(),
        filename="spsc_managed.btrc",
    )
    assert any(
        "SpscQueue<T> payload must be realtime POD without managed ownership" in error
        for error in frontend.analyzed.errors
    )


def test_managed_queue_handle_is_rejected_from_realtime_while_raw_borrow_is_accepted() -> None:
    compiler = Compiler()
    managed = compiler.compile_frontend(
        "import std.spsc;\n@realtime bool pop(SpscQueue<int> queue, int* output) { return queue.tryPop(output); }",
        "<spsc-managed-realtime>",
        CompilerOptions(),
        filename="spsc_managed_realtime.btrc",
    )
    assert any("managed parameter 'queue'" in error for error in managed.analyzed.errors)
    assert _emit_with_stdlib(RAW_CALLBACK_SOURCE)
