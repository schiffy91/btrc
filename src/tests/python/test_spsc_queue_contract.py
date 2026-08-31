"""Bounded FIFO, wraparound, concurrency, and realtime-body proofs."""

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


def _body(generated: str, suffix: str) -> str:
    match = re.search(rf"\b\w*SpscQueue\w*_{suffix}\([^)]*\)\s*\{{(?P<body>.*?)\n\}}", generated, re.DOTALL)
    assert match is not None
    return match.group("body")


def test_queue_operations_are_one_canonical_bounded_composition() -> None:
    generated = _emit_with_stdlib(
        "import std.spsc;\nint main() { SpscQueue<int> q = new SpscQueue<int>(4u); "
        "int value = 0; q.tryPush(1); q.tryPop(&value); delete q; return value; }"
    )
    for method in ("tryPush", "tryPop"):
        body = _body(generated, method)
        assert not re.search(r"\b(malloc|calloc|realloc|free|pthread_mutex|fprintf|printf|sleep)\b", body)
        assert "while (" not in body
        assert "for (" not in body
        assert "%" not in body
        assert "/" not in body
    assert generated.count("class SpscQueue") == 0
    assert "atomic_load_explicit" in generated
    assert "atomic_store_explicit" in generated
    assert "write + 1u" in generated
    assert "nextWrite == self->slotCount" in generated


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
            SpscQueue<int> queue = new SpscQueue<int>(3u);
            int output = -1;
            if (queue.tryPop(&output) || output != -1) { return 1; }
            if (!queue.tryPush(1) || !queue.tryPush(2) || !queue.tryPush(3)) { return 2; }
            if (queue.tryPush(4)) { return 3; }
            if (!queue.tryPop(&output) || output != 1 || !queue.tryPush(4)) { return 4; }
            if (!queue.tryPop(&output) || output != 2) { return 5; }
            if (!queue.tryPop(&output) || output != 3) { return 6; }
            if (!queue.tryPop(&output) || output != 4) { return 7; }
            if (queue.tryPop(&output) || output != 4) { return 8; }
            Thread<int> producer = spawn(() => {
                for (int value = 0; value < 100000; value++) {
                    while (!queue.tryPush(value)) {}
                }
                return 0;
            });
            Thread<int> consumer = spawn(() => {
                int expected = 0;
                while (expected < 100000) {
                    int value = -1;
                    if (queue.tryPop(&value)) {
                        if (value != expected) { return 9; }
                        expected++;
                    }
                }
                return 0;
            });
            int producerResult = producer.join();
            int consumerResult = consumer.join();
            delete queue;
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
