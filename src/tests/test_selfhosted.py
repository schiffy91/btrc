"""Pytest runner for btrc self-hosted compiler tests.

Builds the self-hosted compiler, then runs each .btrc test through it.
Also verifies the compiler can bootstrap (compile its own source).
"""

import glob
import os
import subprocess
import tempfile

import pytest

from src.compiler.python.lexer import Lexer
from src.compiler.python.parser import Parser
from src.compiler.python.analyzer import Analyzer
from src.compiler.python.codegen import CodeGen
from src.compiler.python.main import resolve_includes

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BTRC_TEST_DIR = os.path.dirname(__file__)
COMPILER_SRC = os.path.join(PROJECT_ROOT, "src", "compiler", "btrc", "btrc_compiler.btrc")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")


def _build_selfhosted_compiler():
    """Build the self-hosted compiler using the Python compiler."""
    with open(COMPILER_SRC, "r") as f:
        source = f.read()
    source = resolve_includes(source, COMPILER_SRC)
    tokens = Lexer(source, "btrc_compiler.btrc").tokenize()
    program = Parser(tokens).parse()
    analyzed = Analyzer().analyze(program)
    assert not analyzed.errors, f"Analyzer errors: {analyzed.errors}"
    c_source = CodeGen(analyzed).generate()

    os.makedirs(BUILD_DIR, exist_ok=True)
    c_path = os.path.join(BUILD_DIR, "btrc_compiler.c")
    bin_path = os.path.join(BUILD_DIR, "btrc_compiler")
    with open(c_path, "w") as f:
        f.write(c_source)

    result = subprocess.run(
        ["gcc", c_path, "-o", bin_path, "-lm", "-Wno-parentheses-equality"],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"gcc failed: {result.stderr}"
    return bin_path


@pytest.fixture(scope="module")
def selfhosted_compiler():
    """Module-scoped fixture that builds the self-hosted compiler once."""
    return _build_selfhosted_compiler()


# Tests that use features not yet implemented in the self-hosted compiler
_SELFHOSTED_SKIP = {"test_set.btrc", "test_set_methods.btrc", "test_list_edge_cases.btrc", "test_forward_decl.btrc", "test_range_and_math.btrc", "test_string_iteration.btrc", "test_collection_ops.btrc", "test_safety.btrc", "test_new_methods.btrc", "test_string_instance.btrc", "test_stdlib_collections.btrc", "test_stdlib_datetime.btrc", "test_stdlib_math.btrc", "test_stdlib_random.btrc"}


def get_btrc_test_files():
    pattern = os.path.join(BTRC_TEST_DIR, "test_*.btrc")
    files = sorted(glob.glob(pattern))
    return [os.path.basename(f) for f in files if "_helper" not in f]


@pytest.mark.parametrize("btrc_file", get_btrc_test_files())
def test_selfhosted_btrc_file(selfhosted_compiler, btrc_file):
    """Run a btrc test file through the self-hosted compiler."""
    if btrc_file in _SELFHOSTED_SKIP:
        pytest.skip(f"Self-hosted compiler does not yet support features in {btrc_file}")
    btrc_path = os.path.join(BTRC_TEST_DIR, btrc_file)

    with tempfile.NamedTemporaryFile(suffix=".c", delete=False) as f:
        c_path = f.name
    bin_path = c_path.replace(".c", "")

    try:
        # Transpile with self-hosted compiler
        result = subprocess.run(
            [selfhosted_compiler, btrc_path, "-o", c_path],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"Self-hosted transpile failed:\nstderr: {result.stderr}"
        )

        # Compile with gcc
        result = subprocess.run(
            ["gcc", c_path, "-o", bin_path, "-lm", "-Wno-parentheses-equality"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"gcc failed:\nstderr: {result.stderr}"
        )

        # Run
        result = subprocess.run(
            [bin_path], capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Program exited with {result.returncode}:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PASS" in result.stdout, (
            f"No PASS in output:\n{result.stdout}"
        )
    finally:
        for p in [c_path, bin_path]:
            if os.path.exists(p):
                os.unlink(p)


def test_selfhosted_bootstrap(selfhosted_compiler):
    """Verify the self-hosted compiler can compile its own source (stage 2)."""
    with tempfile.NamedTemporaryFile(suffix=".c", delete=False) as f:
        stage2_c = f.name
    stage2_bin = stage2_c.replace(".c", "")

    try:
        # Stage 2: self-hosted compiles itself
        result = subprocess.run(
            [selfhosted_compiler, COMPILER_SRC, "-o", stage2_c],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"Stage 2 transpile failed:\nstderr: {result.stderr}"
        )

        # Compile stage 2
        result = subprocess.run(
            ["gcc", stage2_c, "-o", stage2_bin, "-lm", "-Wno-parentheses-equality"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"Stage 2 gcc failed:\nstderr: {result.stderr}"
        )

        # Stage 2 compiler should work on a simple test
        test_path = os.path.join(BTRC_TEST_DIR, "test_basic_types.btrc")
        with tempfile.NamedTemporaryFile(suffix=".c", delete=False) as f:
            test_c = f.name
        test_bin = test_c.replace(".c", "")

        try:
            result = subprocess.run(
                [stage2_bin, test_path, "-o", test_c],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, (
                f"Stage 2 test transpile failed:\nstderr: {result.stderr}"
            )

            result = subprocess.run(
                ["gcc", test_c, "-o", test_bin, "-lm", "-Wno-parentheses-equality"],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0

            result = subprocess.run(
                [test_bin], capture_output=True, text=True, timeout=10
            )
            assert result.returncode == 0
            assert "PASS" in result.stdout
        finally:
            for p in [test_c, test_bin]:
                if os.path.exists(p):
                    os.unlink(p)
    finally:
        for p in [stage2_c, stage2_bin]:
            if os.path.exists(p):
                os.unlink(p)
