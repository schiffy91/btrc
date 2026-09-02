"""Concrete realtime clip transport ownership and callback conformance."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPOSITORY = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).with_name("fixtures") / "RealtimeClipTransportRuntime.btrc"
PUBLIC_API = REPOSITORY / "src" / "stdlib" / "RealtimeClipTransport.btrc"
RUNTIME = REPOSITORY / "src" / "stdlib" / "realtime_clip_transport" / "Runtime.btrc"
PRACTICE_RUNTIME = REPOSITORY / "src" / "stdlib" / "realtime_clip_transport" / "PracticeRuntime.btrc"
STRICT_COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _reference(output: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(FIXTURE),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(output),
        ],
        cwd=REPOSITORY,
        env={**os.environ, "BTRC_CACHE_DIR": str(cache)},
        capture_output=True,
        text=True,
        timeout=180,
    )


def _selfhost(compiler: Path, output: Path) -> subprocess.CompletedProcess[str]:
    compiled = subprocess.run(
        [str(compiler), "--no-stdlib", str(FIXTURE)],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if compiled.returncode == 0:
        output.write_text(compiled.stdout)
    return compiled


def _strict_build(compiler: str, generated: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(generated),
            "-pthread",
            "-lm",
            "-o",
            str(output),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_runtime_is_product_neutral_and_keeps_callback_mechanics_private() -> None:
    public_api = PUBLIC_API.read_text()
    private_runtime = RUNTIME.read_text() + PRACTICE_RUNTIME.read_text()
    assert "class RealtimeClipTransport implements RealtimeClipTransportPort" in public_api
    assert "class RealtimeClipTransportOpenOutcome open(RealtimeClipTransportConfiguration configuration)" in public_api
    assert "btrcRealtimeClipTransportProcess" in private_runtime
    assert "@realtime static int btrcRealtimeClipTransportRenderRaw" in private_runtime
    assert "struct BtrcRealtimeClipTransportContext" in private_runtime
    assert "BTRSmith" not in public_api + private_runtime


@pytest.mark.skipif(not STRICT_COMPILERS, reason="requires GCC or Clang")
def test_real_runtime_runs_from_both_frontends_with_strict_compilers(semantic_btrcc: Path, tmp_path: Path) -> None:
    generated = {
        "reference": tmp_path / "RealtimeClipTransportRuntimeReference.c",
        "selfhost": tmp_path / "RealtimeClipTransportRuntimeSelfhost.c",
    }
    reference = _reference(generated["reference"], tmp_path / "reference-cache")
    selfhost = _selfhost(semantic_btrcc, generated["selfhost"])
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr

    for frontend, source in generated.items():
        emitted = source.read_text()
        assert "btrcRealtimeClipTransportProcess" in emitted
        assert "RealtimeClipTransport_open" in emitted
        for compiler in STRICT_COMPILERS:
            executable = tmp_path / f"runtime-{frontend}-{Path(compiler).name}"
            built = _strict_build(compiler, source, executable)
            assert built.returncode == 0, built.stderr
            run = subprocess.run([str(executable)], cwd=REPOSITORY, capture_output=True, text=True, timeout=30)
            assert run.returncode == 0, run.stderr
            assert run.stdout == "PASS RealtimeClipTransportRuntime\n"
            assert run.stderr == ""
