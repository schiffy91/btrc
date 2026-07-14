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

import os
import shlex
import subprocess
import tempfile

import pytest

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.frontend import get_stdlib_source
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.optimizer import optimize
from src.compiler.python.lexer import Lexer
from src.compiler.python.main import resolve_includes
from src.compiler.python.parser.parser import Parser
from src.tests.corpus_files import language_test_files

BTRC_TEST_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.dirname(os.path.dirname(BTRC_TEST_DIR))
_BTRCC_MAIN = os.path.join(_REPO_ROOT, "src", "compiler", "btrc", "btrcc_main.btrc")

# Compiler and flags configurable via environment.
# Default to "cc" (the system C compiler), which resolves to the nix
# gcc-wrapper that knows where glibc crt objects live.
BTRC_CC = shlex.split(os.environ.get("BTRC_CC", "cc"))
BTRC_CFLAGS = shlex.split(os.environ.get("BTRC_CFLAGS", "-std=c11 -pedantic"))
_BTRCC_BUILD_FLAGS = [
    "-std=c11",
    "-pedantic-errors",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-O2",
]
if not BTRC_CC:
    raise ValueError("BTRC_CC must name a C compiler")


def get_btrc_test_files():
    """Recursively find all test_*.btrc files in the shared language corpus."""
    return language_test_files(BTRC_TEST_DIR)


@pytest.fixture(scope="session")
def btrcc_bin(tmp_path_factory):
    """Build the self-hosted compiler once per session (only if btrc selected)."""
    out = tmp_path_factory.mktemp("btrcc")
    csrc = str(out / "btrcc.c")
    binp = str(out / "btrcc")
    r = subprocess.run(
        ["python3", "-m", "src.compiler.python.main", _BTRCC_MAIN, "--no-cache", "-o", csrc],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "BTRC_CACHE_DIR": str(out / "cache")},
        timeout=180,
    )
    assert r.returncode == 0 and os.path.exists(csrc), f"transpiling btrcc failed:\n{r.stderr}"
    r = subprocess.run(
        [*BTRC_CC, *_BTRCC_BUILD_FLAGS, csrc, "-o", binp, "-lm", "-lpthread"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0 and os.path.exists(binp), f"compiling btrcc failed:\n{r.stderr}"
    return binp


def _transpile_python(btrc_path, btrc_file):
    """Transpile a .btrc file to C via the reference Python compiler API."""
    with open(btrc_path) as f:
        source = f.read()
    source = resolve_includes(source, btrc_path)
    stdlib_source = get_stdlib_source(source)
    if stdlib_source:
        source = stdlib_source + "\n" + source
    tokens = Lexer(source, os.path.basename(btrc_file)).tokenize()
    program = Parser(tokens).parse()
    analyzed = Analyzer().analyze(program)
    assert not analyzed.errors, f"Analyzer errors: {analyzed.errors}"
    ir_module = IRGenerator(analyzed).generate()
    ir_module = optimize(ir_module)
    return CEmitter().emit(ir_module)


def _transpile_btrc(btrcc, btrc_path):
    """Transpile a .btrc file to C by running the self-hosted compiler binary.

    btrcc composes the stdlib + resolves includes itself (default mode) and
    writes the C to stdout; it reads src/language/grammar.ebnf relative to cwd,
    so it must run at the repo root.
    """
    r = subprocess.run([btrcc, btrc_path], cwd=_REPO_ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.strip(), f"btrcc failed to transpile:\nstderr: {r.stderr[:2000]}"
    return r.stdout


def _gcc_flags(c_source, c_path, bin_path):
    """Build the C-compiler command for emitted btrc output (shared by both
    compilers): base flags + the tray / GPU / pthread extras the program needs."""
    gcc_flags = [*BTRC_CC, *BTRC_CFLAGS, c_path, "-o", bin_path, "-lm"]
    if "pthread.h" in c_source:
        gcc_flags.append("-lpthread")
    if "btrc_tray.h" in c_source:
        import platform

        tray_dir = os.path.join(BTRC_TEST_DIR, "..", "stdlib", "tray")
        if platform.system() == "Darwin":
            import subprocess as _sp

            try:
                _ver = _sp.run([*BTRC_CC, "--version"], capture_output=True, text=True).stdout.lower()
            except OSError:
                _ver = ""
            if "clang" not in _ver:
                pytest.skip("tray shim needs clang (Objective-C/Cocoa) on macOS")
            shim = os.path.join(tray_dir, "btrc_tray_macos.m")
            gcc_flags = [
                *BTRC_CC,
                "-fobjc-arc",
                "-std=c11",
                f"-I{tray_dir}",
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
        else:
            import shutil
            import subprocess as _sp

            if not shutil.which("pkg-config") or _sp.run(["pkg-config", "--exists", "dbus-1"]).returncode != 0:
                pytest.skip("tray shim needs dbus-1 (pkg-config) on Linux")
            shim = os.path.join(tray_dir, "btrc_tray_linux.c")
            cflags = _sp.check_output(["pkg-config", "--cflags", "dbus-1"], text=True).split()
            libs = _sp.check_output(["pkg-config", "--libs", "dbus-1"], text=True).split()
            gcc_flags.extend([f"-I{tray_dir}", shim, *cflags, *libs])
    if "btrc_gpu.h" in c_source:
        gpu_build = os.path.join(BTRC_TEST_DIR, "..", "stdlib", "gpu", "build")
        gpu_dir = os.path.join(BTRC_TEST_DIR, "..", "stdlib", "gpu")
        if not os.path.exists(os.path.join(gpu_build, "libbtrc_gpu.a")):
            pytest.skip("GPU runtime not built (run make gpu)")
        gcc_flags.extend([f"-I{gpu_dir}", f"-L{gpu_build}", "-lbtrc_gpu"])
        import platform

        gpu_cflags = os.environ.get("GPU_CFLAGS")
        gpu_ldflags = os.environ.get("GPU_LDFLAGS")
        if gpu_cflags and gpu_ldflags:
            gcc_flags.extend(shlex.split(gpu_cflags))
            gcc_flags.extend(shlex.split(gpu_ldflags))
        elif platform.system() == "Darwin":
            import subprocess as _sp

            wgpu_prefix = _sp.check_output(["brew", "--prefix", "wgpu-native"], text=True).strip()
            glfw_prefix = _sp.check_output(["brew", "--prefix", "glfw"], text=True).strip()
            gcc_flags.extend(
                [
                    f"-I{wgpu_prefix}/include",
                    f"-L{wgpu_prefix}/lib",
                    "-lwgpu_native",
                    f"-I{glfw_prefix}/include",
                    f"-L{glfw_prefix}/lib",
                    "-lglfw",
                    "-framework",
                    "Metal",
                    "-framework",
                    "QuartzCore",
                    "-framework",
                    "Cocoa",
                    "-framework",
                    "IOKit",
                    "-framework",
                    "CoreVideo",
                ]
            )
        else:
            gcc_flags.extend(["-lwgpu_native", "-lglfw", "-lpthread"])
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
