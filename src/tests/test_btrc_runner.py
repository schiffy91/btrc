"""Pytest runner for btrc test files.

For each .btrc file in this directory:
1. Transpile to C via the Python compiler
2. Compile with gcc
3. Run the binary
4. Assert exit code 0 and "PASS" in stdout
"""

import glob
import os
import subprocess
import tempfile

import pytest

from src.compiler.python.lexer import Lexer
from src.compiler.python.parser import Parser
from src.compiler.python.analyzer import Analyzer
from src.compiler.python.ir.gen import IRGenerator
from src.compiler.python.ir.optimizer import optimize
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.main import resolve_includes, get_stdlib_source

BTRC_TEST_DIR = os.path.dirname(__file__)


def get_btrc_test_files():
    pattern = os.path.join(BTRC_TEST_DIR, "test_*.btrc")
    files = sorted(glob.glob(pattern))
    # Exclude helper files (no main function, included by other tests)
    return [os.path.basename(f) for f in files if "_helper" not in f]


@pytest.mark.parametrize("btrc_file", get_btrc_test_files())
def test_btrc_file(btrc_file):
    btrc_path = os.path.join(BTRC_TEST_DIR, btrc_file)
    with open(btrc_path, "r") as f:
        source = f.read()

    # Resolve includes
    source = resolve_includes(source, btrc_path)

    # Auto-include stdlib collection types
    stdlib_source = get_stdlib_source()
    if stdlib_source:
        source = stdlib_source + "\n" + source

    # Transpile
    tokens = Lexer(source, btrc_file).tokenize()
    program = Parser(tokens).parse()
    analyzed = Analyzer().analyze(program)
    assert not analyzed.errors, f"Analyzer errors: {analyzed.errors}"
    ir_module = IRGenerator(analyzed).generate()
    ir_module = optimize(ir_module)
    c_source = CEmitter().emit(ir_module)

    # Write C, compile, run
    with tempfile.NamedTemporaryFile(suffix=".c", delete=False, mode="w") as f:
        f.write(c_source)
        c_path = f.name
    bin_path = c_path.replace(".c", "")

    try:
        compile_result = subprocess.run(
            ["gcc", c_path, "-o", bin_path, "-lm"],
            capture_output=True, text=True, timeout=30
        )
        assert compile_result.returncode == 0, (
            f"gcc failed:\nstdout: {compile_result.stdout}\nstderr: {compile_result.stderr}"
        )

        run_result = subprocess.run(
            [bin_path], capture_output=True, text=True, timeout=10
        )
        assert run_result.returncode == 0, (
            f"Program exited with {run_result.returncode}:\n"
            f"stdout: {run_result.stdout}\nstderr: {run_result.stderr}"
        )
        assert "PASS" in run_result.stdout, (
            f"No PASS in output:\n{run_result.stdout}"
        )

        # Compare against golden expected output if available
        expected_path = os.path.join(BTRC_TEST_DIR, "expected",
                                      btrc_file.replace(".btrc", ".stdout"))
        if os.path.exists(expected_path):
            with open(expected_path) as ef:
                expected = ef.read()
            assert run_result.stdout == expected, (
                f"Output mismatch vs golden file:\n"
                f"Expected:\n{expected}\nGot:\n{run_result.stdout}"
            )
    finally:
        for p in [c_path, bin_path]:
            if os.path.exists(p):
                os.unlink(p)
