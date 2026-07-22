"""Unified pytest runner: every .btrc language test runs through BOTH compilers.

For each test_*.btrc under src/tests/ (the shared language corpus — excluding the
compiler-specific python/ and btrc/ subtrees), and for each selected compiler
(--compilers, default "python,btrc"):

1. Transpile to C -- via the Python reference compiler's API, or by running the
   self-hosted btrc compiler (btrcc) binary on the same file.
2. Compile the C with the configured C compiler (C11).
3. Run it; assert exit code 0 and "PASS" in stdout.
4. Compare against the golden expected/<name>.stdout if one exists.

The same corpus and the same goldens hold both compilers to identical behavior,
so the self-hosted compiler is verified against the reference for free. Select a
single compiler with `pytest --compilers=python` (or `=btrc`); the Makefile wires
`make test-btrc` (python) and `make test-btrc-selfhost` (btrc).
"""

import math
import os
import platform
import shlex
import shutil
import subprocess
import tempfile

import pytest

from src.compiler.python import Compiler, CompilerOptions
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.optimizer import optimize
from src.compiler.python.source_provenance import make_ir_source_maps
from src.tests.corpus_files import language_test_files
from src.tests.runner_capabilities import (
    darwin_gpu_flags,
    darwin_tray_backend_error,
    declared_capabilities,
    loopback_listener_error,
)

BTRC_TEST_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.dirname(os.path.dirname(BTRC_TEST_DIR))
_TRAY_DIR = os.path.join(BTRC_TEST_DIR, "..", "stdlib", "tray")
_GPU_DIR = os.path.join(BTRC_TEST_DIR, "..", "stdlib", "gpu")
_GPU_BUILD = os.path.join(_GPU_DIR, "build")

# Compiler and flags configurable via environment.
# Default to "cc" (the system C compiler), which resolves to the nix
# gcc-wrapper that knows where glibc crt objects live.
BTRC_CC = shlex.split(os.environ.get("BTRC_CC", "cc"))
BTRC_CFLAGS = shlex.split(os.environ.get("BTRC_CFLAGS", "-std=c11 -pedantic"))
if not BTRC_CC:
    raise ValueError("BTRC_CC must name a C compiler")

_PYTHON_COMPILER = Compiler()


def _positive_timeout_seconds(raw: str | None, *, name: str, default: float) -> float:
    """Parse a positive finite subprocess timeout from the environment."""
    if raw is None:
        return default
    try:
        seconds = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive number of seconds") from error
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"{name} must be a positive number of seconds")
    return seconds


BTRC_TRANSPILE_TIMEOUT = _positive_timeout_seconds(
    os.environ.get("BTRC_TEST_TRANSPILE_TIMEOUT"),
    name="BTRC_TEST_TRANSPILE_TIMEOUT",
    default=300.0,
)


def get_btrc_test_files():
    """Recursively find all test_*.btrc files in the shared language corpus."""
    return language_test_files(BTRC_TEST_DIR)


def _require_test_capabilities(btrc_path):
    """Skip corpus cases whose explicitly declared host facility is absent."""
    required = declared_capabilities(btrc_path)
    if "loopback-listener" in required:
        if error := loopback_listener_error():
            pytest.skip(error)
    if "native-tray" in required and platform.system() == "Darwin":
        error = darwin_tray_backend_error(tuple(BTRC_CC), tuple(BTRC_CFLAGS), _TRAY_DIR)
        if error:
            pytest.skip(error)


def _transpile_python(btrc_path, btrc_file):
    """Transpile a .btrc file to C via the reference Python compiler API."""
    with open(btrc_path) as f:
        source = f.read()
    frontend = _PYTHON_COMPILER.compile_frontend(
        source,
        btrc_path,
        CompilerOptions(map_stdlib_positions=True),
        filename=os.path.basename(btrc_file),
    )
    analyzed = frontend.analyzed
    assert not analyzed.errors, f"Analyzer errors: {analyzed.errors}"
    line_map, declaration_line_map = make_ir_source_maps(
        frontend.source_bundle,
        split_spaces=bool(frontend.stdlib_source and frontend.user_program is not None),
    )
    ir_module = IRGenerator(
        analyzed,
        source_file=os.path.basename(btrc_file),
        line_map=line_map,
        declaration_line_map=declaration_line_map,
    ).generate()
    ir_module = optimize(ir_module)
    return CEmitter().emit(ir_module)


def _transpile_btrc(btrcc, btrc_path):
    """Transpile a .btrc file to C by running the self-hosted compiler binary.

    btrcc composes the stdlib + resolves includes itself (default mode) and
    writes the C to stdout. The shared fixture supplies an explicit runtime data
    root; the repository cwd keeps test paths and diagnostics deterministic.
    """
    r = subprocess.run(
        [btrcc, btrc_path],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=BTRC_TRANSPILE_TIMEOUT,
    )
    assert r.returncode == 0 and r.stdout.strip(), f"btrcc failed to transpile:\nstderr: {r.stderr[:2000]}"
    return r.stdout


def _gcc_flags(c_source, c_path, bin_path):
    """Build the C-compiler command for emitted btrc output (shared by both
    compilers): base flags + the tray / GPU / pthread extras the program needs."""
    gcc_flags = [*BTRC_CC, *BTRC_CFLAGS, c_path, "-o", bin_path, "-lm"]
    if "pthread.h" in c_source:
        gcc_flags.append("-lpthread")
    if "btrc_tray.h" in c_source:
        system = platform.system()
        if system == "Darwin":
            try:
                _ver = subprocess.run([*BTRC_CC, "--version"], capture_output=True, text=True).stdout.lower()
            except OSError as error:
                pytest.skip(f"tray shim compiler is unavailable: {error}")
            if "clang" not in _ver:
                pytest.skip("tray shim needs clang (Objective-C/Cocoa) on macOS")
            shim = os.path.join(_TRAY_DIR, "btrc_tray_macos.m")
            gcc_flags = [
                *BTRC_CC,
                *BTRC_CFLAGS,
                "-fobjc-arc",
                f"-I{_TRAY_DIR}",
                c_path,
                shim,
                "-framework",
                "Cocoa",
                "-lm",
                "-o",
                bin_path,
            ]
            if "pthread.h" in c_source:
                gcc_flags.append("-lpthread")
        elif system == "Linux":
            pkg_config = shutil.which("pkg-config")
            if pkg_config is None:
                pytest.skip("tray shim needs dbus-1 (pkg-config) on Linux")
            dependency = subprocess.run(
                [pkg_config, "--cflags", "--libs", "dbus-1"],
                capture_output=True,
                text=True,
            )
            if dependency.returncode != 0:
                pytest.skip("tray shim needs dbus-1 development files (pkg-config) on Linux")
            shim = os.path.join(_TRAY_DIR, "btrc_tray_linux.c")
            gcc_flags.extend([f"-I{_TRAY_DIR}", shim, *dependency.stdout.split()])
        else:
            pytest.skip(f"native tray corpus is unsupported on {system}")
    if "btrc_gpu.h" in c_source:
        if not os.path.isfile(os.path.join(_GPU_BUILD, "libbtrc_gpu.a")):
            pytest.skip("GPU runtime not built (run make gpu)")
        gcc_flags.extend([f"-I{_GPU_DIR}", f"-L{_GPU_BUILD}", "-lbtrc_gpu"])
        gpu_cflags = os.environ.get("GPU_CFLAGS")
        gpu_ldflags = os.environ.get("GPU_LDFLAGS")
        if bool(gpu_cflags) != bool(gpu_ldflags):
            pytest.skip("WebGPU toolchain is unavailable: GPU_CFLAGS and GPU_LDFLAGS must be set together")
        if gpu_cflags and gpu_ldflags:
            gcc_flags.extend(shlex.split(gpu_cflags))
            gcc_flags.extend(shlex.split(gpu_ldflags))
        elif platform.system() == "Darwin":
            platform_flags, error = darwin_gpu_flags()
            if error:
                pytest.skip(error)
            gcc_flags.extend(platform_flags)
        elif platform.system() == "Linux":
            gcc_flags.extend(["-lwgpu_native", "-lglfw", "-lpthread"])
        else:
            pytest.skip(f"WebGPU toolchain is unavailable on {platform.system()}: set GPU_CFLAGS and GPU_LDFLAGS")
    return gcc_flags


def _compile_run_check(c_source, btrc_path, btrc_file):
    """Compile emitted C, run it, assert PASS + exit 0, and match the golden."""
    with tempfile.NamedTemporaryFile(suffix=".c", delete=False, mode="w") as f:
        f.write(c_source)
        c_path = f.name
    bin_path = c_path.removesuffix(".c")
    try:
        gcc_flags = _gcc_flags(c_source, c_path, bin_path)
        compile_result = subprocess.run(gcc_flags, capture_output=True, text=True, timeout=60)
        assert compile_result.returncode == 0, (
            f"gcc failed:\nstdout: {compile_result.stdout}\nstderr: {compile_result.stderr}"
        )
        _require_test_capabilities(btrc_path)
        run_result = subprocess.run([bin_path], capture_output=True, text=True, timeout=15)
        assert run_result.returncode == 0, (
            f"Program exited with {run_result.returncode}:\nstdout: {run_result.stdout}\nstderr: {run_result.stderr}"
        )
        assert "PASS" in run_result.stdout, f"No PASS in output:\n{run_result.stdout}"
        test_dir = os.path.dirname(btrc_path)
        test_name = os.path.basename(btrc_file).replace(".btrc", ".stdout")
        expected_path = os.path.join(test_dir, "expected", test_name)
        if os.path.exists(expected_path):
            with open(expected_path) as ef:
                expected = ef.read()
            assert run_result.stdout == expected, (
                f"Output mismatch vs golden file:\nExpected:\n{expected}\nGot:\n{run_result.stdout}"
            )
    finally:
        for p in [c_path, bin_path]:
            if os.path.exists(p):
                os.unlink(p)


@pytest.mark.parametrize("btrc_file", get_btrc_test_files())
def test_btrc_file(compiler, btrc_file, request):
    """Run one language test through the selected compiler."""
    btrc_path = os.path.join(BTRC_TEST_DIR, btrc_file)
    if compiler == "python":
        c_source = _transpile_python(btrc_path, btrc_file)
    else:
        btrcc = request.getfixturevalue("btrcc_bin")
        c_source = _transpile_btrc(btrcc, btrc_path)
    _compile_run_check(c_source, btrc_path, btrc_file)
