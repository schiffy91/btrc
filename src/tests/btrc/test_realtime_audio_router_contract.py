"""Fixed-capacity realtime audio program routing and barrier conformance."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPOSITORY = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).with_name("fixtures")
CONTRACT_FIXTURE = FIXTURES / "RealtimeAudioRouterContract.btrc"
BARRIER_FIXTURE = FIXTURES / "RealtimeAudioRouterBarrier.btrc"
API = REPOSITORY / "src" / "stdlib" / "RealtimeAudioRouter.btrc"
STRICT_COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _reference(source: Path, output: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(source),
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


def _selfhost(compiler: Path, source: Path, output: Path) -> subprocess.CompletedProcess[str]:
    compiled = subprocess.run(
        [str(compiler), "--no-stdlib", str(source)],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if compiled.returncode == 0:
        output.write_text(compiled.stdout)
    return compiled


def _compile_pair(semantic_btrcc: Path, source: Path, tmp_path: Path) -> dict[str, Path]:
    generated = {
        "reference": tmp_path / f"{source.stem}Reference.c",
        "selfhost": tmp_path / f"{source.stem}Selfhost.c",
    }
    reference = _reference(source, generated["reference"], tmp_path / f"{source.stem}-reference-cache")
    selfhost = _selfhost(semantic_btrcc, source, generated["selfhost"])
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    return generated


def _build_and_run(
    compiler: str,
    generated: Path,
    executable: Path,
    flags: tuple[str, ...] = ("-O2",),
) -> subprocess.CompletedProcess[str]:
    built = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            *flags,
            str(generated),
            "-pthread",
            "-lm",
            *tuple(flag for flag in flags if flag.startswith("-fsanitize=")),
            "-o",
            str(executable),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert built.returncode == 0, built.stderr
    return subprocess.run(
        [str(executable)],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _host_clang() -> str | None:
    if sys.platform == "darwin" and os.access("/usr/bin/clang", os.X_OK):
        return "/usr/bin/clang"
    return shutil.which("clang")


def test_router_contract_is_product_neutral_and_exposes_explicit_generation_barriers() -> None:
    source = API.read_text()
    assert "class RealtimeAudioProgramRouter" in source
    assert "RealtimeAudioProgram providerProgram()" in source
    assert "RealtimeAudioRouteAttachOutcome attach(RealtimeAudioProgram? program)" in source
    assert "RealtimeAudioRouteActivateOutcome activate(RealtimeAudioRouteAttachment? attachment)" in source
    assert "RealtimeAudioRouteOperationOutcome deactivate(RealtimeAudioRouteActivation? activation)" in source
    assert "RealtimeAudioRouteOperationOutcome detach(RealtimeAudioRouteAttachment? attachment)" in source
    assert "RealtimeAudioRouteOperationOutcome closeAfterProviderDrain()" in source
    assert "callbackGateCloseAdmission(gate);" in source
    assert "callbackGateDrain(gate);" in source
    assert source.index("callbackGateDrain(gate);") < source.index("slot->occupied = 0;")
    assert "BTRSmith" not in source
    assert "JUCE" not in source
    assert "CoreAudio" not in source


@pytest.mark.skipif(not STRICT_COMPILERS, reason="requires GCC or Clang")
@pytest.mark.parametrize(
    ("fixture", "expected"),
    (
        (CONTRACT_FIXTURE, "PASS RealtimeAudioRouterContract\n"),
        (BARRIER_FIXTURE, "PASS RealtimeAudioRouterBarrier\n"),
    ),
)
def test_router_runs_from_both_frontends_with_strict_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture: Path,
    expected: str,
) -> None:
    generated = _compile_pair(semantic_btrcc, fixture, tmp_path)
    for frontend, source in generated.items():
        for compiler in STRICT_COMPILERS:
            executable = tmp_path / f"{fixture.stem}-{frontend}-{Path(compiler).name}"
            run = _build_and_run(compiler, source, executable)
            assert run.returncode == 0, run.stderr
            assert run.stdout == expected
            assert run.stderr == ""


def test_detach_barrier_is_address_undefined_and_thread_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    clang = _host_clang()
    if clang is None:
        pytest.skip("sanitizer proof requires Clang")
    generated = _compile_pair(semantic_btrcc, BARRIER_FIXTURE, tmp_path)
    for sanitizer in ("address,undefined", "thread"):
        try:
            for frontend, source in generated.items():
                executable = tmp_path / f"barrier-{frontend}-{sanitizer.replace(',', '-')}"
                run = _build_and_run(
                    clang,
                    source,
                    executable,
                    ("-O1", "-g", "-fno-omit-frame-pointer", f"-fsanitize={sanitizer}"),
                )
                assert run.returncode == 0, run.stderr
                assert run.stdout == "PASS RealtimeAudioRouterBarrier\n"
                assert run.stderr == ""
        except AssertionError as error:
            if "ThreadSanitizer" in str(error) or "-ltsan" in str(error):
                pytest.skip(f"ThreadSanitizer unavailable: {error}")
            raise
