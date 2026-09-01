"""Reference/self-host, payload-rejection, and strict-C OwnedBuffer proofs."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[3]
FIXTURE = REPOSITORY / "src/tests/memory/OwnedBuffer.btrc"
EXPECTED = "PASS OwnedBuffer\n"
STRICT_COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _reference(
    source: Path,
    output: Path,
    cache: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(source),
            "--no-cache",
            "-o",
            str(output),
        ],
        cwd=REPOSITORY,
        env={**os.environ, "BTRC_CACHE_DIR": str(cache)},
        capture_output=True,
        text=True,
        timeout=120,
    )


def _selfhost(
    compiler: Path,
    source: Path,
    output: Path,
) -> subprocess.CompletedProcess[str]:
    compiled = subprocess.run(
        [str(compiler), str(source)],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if compiled.returncode == 0:
        output.write_text(compiled.stdout)
    return compiled


@pytest.mark.skipif(not STRICT_COMPILERS, reason="requires a strict C11 compiler")
def test_fixture_runs_from_both_frontends_with_gcc_and_clang(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = {
        "reference": tmp_path / "OwnedBufferReference.c",
        "selfhost": tmp_path / "OwnedBufferSelfhost.c",
    }
    reference = _reference(FIXTURE, generated["reference"], tmp_path / "reference-cache")
    selfhost = _selfhost(semantic_btrcc, FIXTURE, generated["selfhost"])
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr

    for frontend, source in generated.items():
        emitted = source.read_text()
        assert "OwnedBuffers_tryOpen" in emitted
        assert "_Atomic(unsigned int)* counterBorrow" in emitted
        assert "atomic_load_explicit" in emitted
        for compiler in STRICT_COMPILERS:
            executable = tmp_path / f"OwnedBuffer-{frontend}-{Path(compiler).name}"
            built = subprocess.run(
                [
                    compiler,
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
                cwd=REPOSITORY,
                capture_output=True,
                text=True,
                timeout=90,
            )
            assert built.returncode == 0, built.stderr
            run = subprocess.run(
                [str(executable)],
                cwd=REPOSITORY,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert run.returncode == 0, run.stderr
            assert run.stdout == EXPECTED


@pytest.mark.parametrize(
    ("source_text", "reference_diagnostic", "selfhost_diagnostic"),
    (
        (
            "import std.OwnedBuffer;\nint main() { OwnedBuffer<string> values; return 0; }",
            "OwnedBuffer<T> payload must be realtime POD without managed or atomic ownership",
            "OwnedBuffer<T> payload must be realtime POD without managed or atomic ownership",
        ),
        (
            "import std.OwnedBuffer;\nint main() { OwnedBuffer<Atomic<uint>> values; return 0; }",
            "OwnedBuffer<T> payload must be realtime POD without managed or atomic ownership",
            "OwnedBuffer<T> payload must be realtime POD without managed or atomic ownership",
        ),
        (
            "import std.OwnedBuffer;\n"
            "int main() { AtomicBuffer<uint> values = AtomicBuffer((size_t)1); "
            "values.tryGet((size_t)0, null); return 0; }",
            "Class 'AtomicBuffer' has no field or method 'tryGet'",
            "Type 'AtomicBuffer<uint>' has no method 'tryGet'",
        ),
        (
            "import std.array;\nint main() { Array<Atomic<uint>> values; return 0; }",
            "cannot embed an Atomic<T> owner in shallow copyable storage",
            "cannot embed an Atomic<T> owner in shallow copyable storage",
        ),
    ),
)
def test_payload_rejections_match_both_frontends_without_relaxing_array_rules(
    semantic_btrcc: Path,
    tmp_path: Path,
    source_text: str,
    reference_diagnostic: str,
    selfhost_diagnostic: str,
) -> None:
    source = tmp_path / "OwnedBufferRejected.btrc"
    source.write_text(source_text)
    reference = _reference(
        source,
        tmp_path / "OwnedBufferRejectedReference.c",
        tmp_path / "rejection-cache",
    )
    selfhost = _selfhost(
        semantic_btrcc,
        source,
        tmp_path / "OwnedBufferRejectedSelfhost.c",
    )
    assert reference.returncode != 0
    assert selfhost.returncode != 0
    assert reference_diagnostic in reference.stderr
    assert selfhost_diagnostic in selfhost.stderr
