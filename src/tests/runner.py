"""Unified pytest runner: every .btrc language test runs through BOTH compilers.

For each test_*.btrc under src/tests/ (the shared language corpus — excluding the
compiler-specific python/ and btrc/ subtrees), and for each selected compiler
(--compilers, default "python,btrc"):

1. Transpile to C -- via the Python reference compiler's API, or by running the
   self-hosted btrc compiler (btrcc) binary on the same file.
2. Compile the C with the configured C compiler (C11).
3. Run it; assert exit code 0 and "PASS" in stdout.
4. Compare stdout against the required golden expected/<name>.stdout.
5. Require empty stderr, or compare it against expected/<name>.stderr when
   that explicit golden exists.

The same corpus and the same goldens hold both compilers to identical behavior,
so the self-hosted compiler is verified against the reference for free. Select a
single compiler with `pytest --compilers=python` (or `=btrc`); the Makefile wires
`make test-btrc` (python) and `make test-btrc-selfhost` (btrc).
"""

import json
import math
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile

import pytest

from src.compiler.python import Compiler, CompilerOptions
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.tests.corpus_files import language_test_files
from src.tests.runner_capabilities import (
    TARGET_CAPABILITIES,
    darwin_gpu_flags,
    darwin_tray_backend_error,
    declared_capabilities,
    linux_tray_backend_error,
    loopback_listener_error,
    target_capability_error,
)

BTRC_TEST_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.dirname(os.path.dirname(BTRC_TEST_DIR))
_GPU_DIR = os.path.join(_REPO_ROOT, "src", "runtime", "gpu")
_GPU_BUILD = os.path.join(_REPO_ROOT, "build", "stdlib", "GPU")

# Compiler and flags configurable via environment.
# Default to "cc" (the system C compiler), which resolves to the nix
# gcc-wrapper that knows where glibc crt objects live.


def default_c_compiler() -> str:
    """The host C compiler when BTRC_CC is unset.

    Nix's `cc` on macOS is GCC, which emulates thread-local storage through
    pthread keys, so every compiled btrc program pays a call per access where
    Apple's clang reads a native TLV descriptor. Measured on one identical
    generated btrcc.c, a cold BTRSmith compile takes 74.9 s from the GCC build
    against 62.3 s from the clang build: GCC's takes 20% longer over the whole
    compile, and 79% longer on the generic-instance closure, the phase densest in thread-local and ARC
    traffic.
    """
    if sys.platform == "darwin" and shutil.which("clang"):
        return "clang"
    return "cc"


BTRC_CC = shlex.split(os.environ.get("BTRC_CC", default_c_compiler()))
BTRC_CFLAGS = shlex.split(os.environ.get("BTRC_CFLAGS", "-std=c11 -pedantic"))
if not BTRC_CC:
    raise ValueError("BTRC_CC must name a C compiler")

_PYTHON_COMPILER = Compiler()

# Module-unit mode compiles every corpus program as one C unit per source
# compilation group (each stdlib module is its own group), linked together.
MODULE_UNITS = os.environ.get("BTRC_TEST_MODULE_UNITS") == "1"


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

# How long a compiled corpus program may run. The default suits the corpus,
# where all but a handful finish in well under a second, and it is what catches
# a program that hangs. The heaviest test is an order of magnitude slower than
# the rest at -O0, so a slower machine -- a VM, an emulated architecture -- can
# need a larger budget without anything being wrong.
BTRC_RUN_TIMEOUT = _positive_timeout_seconds(
    os.environ.get("BTRC_TEST_RUN_TIMEOUT"),
    name="BTRC_TEST_RUN_TIMEOUT",
    default=15.0,
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
    if "native-tray" in required and platform.system() not in ("Darwin", "Linux"):
        pytest.skip("native tray provider is not implemented for this target")
    if "native-tray" in required and platform.system() == "Darwin":
        error = darwin_tray_backend_error(tuple(BTRC_CC), tuple(BTRC_CFLAGS))
        if error:
            pytest.skip(error)
    if "native-tray" in required and platform.system() == "Linux":
        if error := linux_tray_backend_error():
            pytest.skip(error)
    for capability in sorted(required & TARGET_CAPABILITIES):
        if error := target_capability_error(capability):
            pytest.skip(error)


def _transpile_python(btrc_path, btrc_file):
    """Transpile a .btrc file to C via the reference Python compiler API."""
    with open(btrc_path) as f:
        source = f.read()
    options = CompilerOptions(map_stdlib_positions=True)
    frontend = _PYTHON_COMPILER.compile_frontend(
        source,
        btrc_path,
        options,
        filename=os.path.basename(btrc_file),
    )
    analyzed = frontend.analyzed
    assert not analyzed.errors, f"Analyzer errors: {analyzed.errors}"
    source_map = frontend.source_bundle.source_map(
        split_spaces=bool(frontend.stdlib_source and frontend.user_program is not None),
    )
    ir_module = IRLowerer(
        analyzed,
        source_file=os.path.basename(btrc_file),
        source_map=source_map,
        prune_stdlib=options.dce,
    ).lower()
    ir_module = _PYTHON_COMPILER.pipeline.optimize(ir_module, options)
    return _PYTHON_COMPILER.pipeline.emit(ir_module)


def _transpile_python_module_units(btrc_path, btrc_file):
    """Transpile through the public compiler API into module units."""
    with open(btrc_path) as f:
        source = f.read()
    prefix = os.path.join(tempfile.mkdtemp(prefix="btrc-module-units-"), "program")
    options = CompilerOptions(
        map_stdlib_positions=True,
        use_cache=False,
        units_prefix=prefix,
        module_units=True,
    )
    result = _PYTHON_COMPILER.compile(source, btrc_path, options)
    assert result.failure is None, f"module-unit compile failed: {result.failure}"
    return (result.c_source, *result.c_units)


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


def _transpile_btrc_module_units(btrcc, btrc_path):
    """Transpile with the self-hosted compiler into module units."""
    directory = tempfile.mkdtemp(prefix="btrc-module-units-")
    primary = os.path.join(directory, "program.c")
    plan = os.path.join(directory, "program.json")
    r = subprocess.run(
        [
            btrcc,
            "--no-cache",
            btrc_path,
            "-o",
            primary,
            "--emit-units",
            os.path.join(directory, "program"),
            "--module-units",
            # Forked workers, but few: the corpus already runs in parallel.
            "--jobs",
            "2",
            "--emit-link-plan",
            plan,
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=BTRC_TRANSPILE_TIMEOUT,
    )
    assert r.returncode == 0, f"btrcc failed to transpile module units:\nstderr: {r.stderr[:2000]}"
    with open(plan) as plan_file:
        units = json.load(plan_file).get("emitted-units", [])
    texts = []
    for path in (primary, *units):
        with open(path) as unit_file:
            texts.append(unit_file.read())
    return tuple(texts)


def _gcc_flags(c_source, c_path, bin_path):
    """Build the emitted-C command, including the compiler-only compute runtime."""
    gcc_flags = [*BTRC_CC, *BTRC_CFLAGS, c_path, "-o", bin_path, "-lm"]
    if "pthread.h" in c_source:
        gcc_flags.append("-lpthread")
    if "btrc_gpu_compute_internal.h" in c_source:
        if not os.path.isfile(os.path.join(_GPU_BUILD, "libbtrc_gpu.a")):
            pytest.skip("Compute runtime not built (run make gpu)")
        gcc_flags.extend([f"-I{_GPU_DIR}", f"-L{_GPU_BUILD}", "-lbtrc_gpu"])
        dependency_cflags = os.environ.get("GPU_CFLAGS")
        dependency_ldflags = os.environ.get("GPU_LDFLAGS")
        if bool(dependency_cflags) != bool(dependency_ldflags):
            pytest.skip("WebGPU toolchain is unavailable: GPU_CFLAGS and GPU_LDFLAGS must be set together")
        if dependency_cflags and dependency_ldflags:
            gcc_flags.extend(shlex.split(dependency_cflags))
            gcc_flags.extend(shlex.split(dependency_ldflags))
        elif platform.system() == "Darwin":
            platform_flags, error = darwin_gpu_flags()
            if error:
                pytest.skip(error)
            gcc_flags.extend(platform_flags)
        elif platform.system() == "Linux":
            gcc_flags.extend(["-lwgpu_native", "-lpthread"])
        else:
            pytest.skip(f"WebGPU toolchain is unavailable on {platform.system()}: set GPU_CFLAGS and GPU_LDFLAGS")
    return gcc_flags


def _compile_run_check(c_source, btrc_path, btrc_file):
    """Compile emitted C, run it, assert PASS + exit 0, and match the golden.

    `c_source` is one translation unit, or a tuple whose first unit is the
    primary and whose others are linked with it."""
    units = c_source if isinstance(c_source, tuple) else (c_source,)
    c_source = "\n".join(units)
    with tempfile.NamedTemporaryFile(suffix=".c", delete=False, mode="w") as f:
        f.write(units[0])
        c_path = f.name
    unit_paths = []
    for index, unit in enumerate(units[1:], start=1):
        unit_paths.append(f"{c_path}.unit-{index}.c")
        with open(unit_paths[-1], "w") as unit_file:
            unit_file.write(unit)
    bin_path = c_path.removesuffix(".c")
    try:
        gcc_flags = _gcc_flags(c_source, c_path, bin_path)
        if unit_paths:
            gcc_flags[gcc_flags.index(c_path) + 1 : gcc_flags.index(c_path) + 1] = unit_paths
        compile_result = subprocess.run(gcc_flags, capture_output=True, text=True, timeout=60)
        assert compile_result.returncode == 0, (
            f"gcc failed:\nstdout: {compile_result.stdout}\nstderr: {compile_result.stderr}"
        )
        _require_test_capabilities(btrc_path)
        run_result = subprocess.run([bin_path], capture_output=True, text=True, timeout=BTRC_RUN_TIMEOUT)
        assert run_result.returncode == 0, (
            f"Program exited with {run_result.returncode}:\nstdout: {run_result.stdout}\nstderr: {run_result.stderr}"
        )
        assert "PASS" in run_result.stdout, f"No PASS in output:\n{run_result.stdout}"
        test_dir = os.path.dirname(btrc_path)
        test_name = os.path.basename(btrc_file).replace(".btrc", ".stdout")
        expected_dir = os.path.join(test_dir, "expected")
        expected_stdout_path = os.path.join(expected_dir, test_name)
        assert os.path.isfile(expected_stdout_path), (
            f"Runnable corpus case is missing its stdout golden: {expected_stdout_path}"
        )
        with open(expected_stdout_path) as expected_file:
            expected_stdout = expected_file.read()
        assert run_result.stdout == expected_stdout, (
            f"Stdout mismatch vs golden file:\nExpected:\n{expected_stdout}\nGot:\n{run_result.stdout}"
        )

        expected_stderr_path = expected_stdout_path.removesuffix(".stdout") + ".stderr"
        expected_stderr = ""
        if os.path.isfile(expected_stderr_path):
            with open(expected_stderr_path) as expected_file:
                expected_stderr = expected_file.read()
        assert run_result.stderr == expected_stderr, (
            f"Stderr mismatch vs golden file:\nExpected:\n{expected_stderr}\nGot:\n{run_result.stderr}"
        )
    finally:
        for p in [c_path, bin_path, *unit_paths]:
            if os.path.exists(p):
                os.unlink(p)


@pytest.mark.parametrize("btrc_file", get_btrc_test_files())
def test_btrc_file(compiler, btrc_file, request):
    """Run one language test through the selected compiler."""
    btrc_path = os.path.join(BTRC_TEST_DIR, btrc_file)
    if compiler == "python" and MODULE_UNITS:
        c_source = _transpile_python_module_units(btrc_path, btrc_file)
    elif compiler == "python":
        c_source = _transpile_python(btrc_path, btrc_file)
    elif MODULE_UNITS:
        btrcc = request.getfixturevalue("btrcc_bin")
        c_source = _transpile_btrc_module_units(btrcc, btrc_path)
    else:
        btrcc = request.getfixturevalue("btrcc_bin")
        c_source = _transpile_btrc(btrcc, btrc_path)
    _compile_run_check(c_source, btrc_path, btrc_file)
