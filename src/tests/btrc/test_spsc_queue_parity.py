"""Reference/self-host and strict-C proofs for raw realtime SPSC use."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "src/tests/threads/test_spsc_raw_callback.btrc"
EXPECTED = "PASS spsc_raw_callback\n"
STRICT_COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _reference(output: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(FIXTURE),
            "--no-cache",
            "-o",
            str(output),
        ],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(cache)},
        capture_output=True,
        text=True,
        timeout=120,
    )


def _selfhost(compiler: Path, output: Path) -> subprocess.CompletedProcess[str]:
    compiled = subprocess.run(
        [str(compiler), str(FIXTURE)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if compiled.returncode == 0:
        output.write_text(compiled.stdout)
    return compiled


@pytest.mark.skipif(not STRICT_COMPILERS, reason="requires a strict C11 compiler")
def test_raw_callback_queue_runs_from_both_frontends_with_gcc_and_clang(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = {
        "reference": tmp_path / "spsc-reference.c",
        "selfhost": tmp_path / "spsc-selfhost.c",
    }
    reference = _reference(generated["reference"], tmp_path / "reference-cache")
    selfhost = _selfhost(semantic_btrcc, generated["selfhost"])
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr

    for frontend, source in generated.items():
        emitted = source.read_text()
        assert "SpscQueues_tryPushBorrowed" in emitted
        assert "SpscQueues_tryPopBorrowed" in emitted
        assert "atomic_load_explicit" in emitted
        assert "atomic_store_explicit" in emitted
        for compiler in STRICT_COMPILERS:
            executable = tmp_path / f"spsc-{frontend}-{Path(compiler).name}"
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
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=90,
            )
            assert built.returncode == 0, built.stderr
            run = subprocess.run(
                [str(executable)],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert run.returncode == 0, run.stderr
            assert run.stdout == EXPECTED
