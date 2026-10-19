"""Windows executables built on any host, for windows.yml's win32-native job to run.

The Windows rows build with zig's MinGW-w64 toolchain and the overlay in
src/runtime/windows, which builds on Linux and macOS; executing the result
needs Windows. These helpers build a corpus program through either compiler
exactly as the target runner does (src/tests/target_runner.py's
ProgramBuilder, with the row's toolchain and strict flags), or a plain C
fixture with the same flags, and publish each executable with the output it
must produce. With BTRC_WIN32_EVIDENCE_DIR set, `publish` copies them there:
the win32-native-build job uploads that directory and each Windows runner
runs the executables of its own architecture and compares (windows.yml).
On Windows itself `publish` runs the executable and compares at once.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT
from src.tests.target_runner import (
    STRICT_CFLAGS,
    BuildConfiguration,
    CorpusProgram,
    ProgramBuilder,
    TargetEnvironment,
    TargetRows,
)
from tools.native_plan import NativePlanError, TargetToolchain

REPO = Path(__file__).resolve().parents[3]
OVERLAY = REPO / "src" / "runtime" / "windows"

# The evidence names (windows.yml's matrix targets) and their targets.toml rows.
WINDOWS_TARGETS = {"windows-x64": "windows-x86_64", "windows-arm64": "windows-aarch64"}


def windows_toolchain(label: str) -> TargetToolchain:
    """The row's zig toolchain, or a skip when zig is not on PATH."""
    try:
        return TargetToolchain(TargetRows.row(label))
    except NativePlanError as error:
        pytest.skip(f"requires zig for {label}: {error}")


def build_corpus_program(source: str, frontend: str, target: str, btrcc: Path | None, work: Path) -> Path:
    """`source` (a corpus path) through `frontend` for `target`, as the target runner builds it."""
    label = WINDOWS_TARGETS[target]
    toolchain = windows_toolchain(label)
    bundle = work / "bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    configuration = BuildConfiguration(
        label=label,
        work=work / "units",
        bundle=bundle,
        btrcc=btrcc,
        cflags=STRICT_CFLAGS,
        compute="no Windows program here dispatches @gpu work",
        facility=None,
    )
    with TargetEnvironment(TargetRows.row(label), toolchain, work / "scratch").applied():
        result = ProgramBuilder(configuration, toolchain).build(CorpusProgram(source), frontend)
    assert result.status == "built", (result.phase, result.reason)
    return bundle / result.artifact


def build_c_fixture(sources: list[Path], target: str, output: Path, *, libraries: tuple[str, ...] = ()) -> Path:
    """Plain C `sources` for `target` with the overlay and the strict flags every Windows unit gets."""
    toolchain = windows_toolchain(WINDOWS_TARGETS[target])
    command = [
        *toolchain.drivers["cc"],
        *toolchain.arguments,
        "-std=c11",
        *toolchain.generated_arguments,
        *STRICT_CFLAGS,
        *(str(source) for source in sources),
        "-o",
        str(output),
        *(f"-l{library}" for library in libraries),
        *toolchain.runtime_libraries(),
    ]
    built = subprocess.run(command, capture_output=True, text=True, timeout=C_COMPILE_TIMEOUT * 5, check=False)
    assert built.returncode == 0, built.stderr
    assert output.read_bytes()[:2] == b"MZ"
    return output


def publish(executable: Path, name: str, stdout: bytes, stderr: bytes | None = None) -> None:
    """Copy `executable` and the output it must print to the evidence directory as `name`."""
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if evidence:
        directory = Path(evidence)
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(executable, directory / f"{name}.exe")
        (directory / f"{name}.stdout").write_bytes(stdout)
        if stderr is not None:
            (directory / f"{name}.stderr").write_bytes(stderr)
    if sys.platform == "win32":
        ran = subprocess.run([str(executable)], capture_output=True, timeout=RUN_TIMEOUT * 4, check=False)
        assert ran.returncode == 0, (ran.returncode, ran.stdout, ran.stderr)
        assert ran.stdout.replace(b"\r\n", b"\n") == stdout, ran.stdout
        if stderr is not None:
            assert ran.stderr.replace(b"\r\n", b"\n") == stderr, ran.stderr
