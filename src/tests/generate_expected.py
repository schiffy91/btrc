"""Generate expected output golden files for btrc tests.

For each test_*.btrc file in subdirectories, compile and run via the
Python compiler, then save the stdout to expected/<test_name>.stdout
alongside the test file.
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.generator import generate_ir
from src.compiler.python.ir.optimizer import optimize
from src.compiler.python.lexer import Lexer
from src.compiler.python.main import get_stdlib_source, resolve_includes
from src.compiler.python.parser.parser import Parser
from src.tests.corpus_files import language_test_files

BTRC_TEST_DIR = os.path.dirname(os.path.abspath(__file__))


def generate_expected():
    passed = 0
    failed = 0

    for relative_path in language_test_files(BTRC_TEST_DIR):
        btrc_path = os.path.join(BTRC_TEST_DIR, relative_path)
        root = os.path.dirname(btrc_path)
        expected_dir = os.path.join(root, "expected")
        btrc_file = os.path.basename(btrc_path)
        name = btrc_file.removesuffix(".btrc")

        try:
            with open(btrc_path) as f:
                source = f.read()
            source = resolve_includes(source, btrc_path)
            stdlib_source = get_stdlib_source(source)
            if stdlib_source:
                source = stdlib_source + "\n" + source

            tokens = Lexer(source, btrc_file).tokenize()
            program = Parser(tokens).parse()
            analyzed = Analyzer().analyze(program)
            if analyzed.errors:
                print(f"  SKIP {relative_path}: analyzer errors")
                continue
            ir_module = generate_ir(analyzed)
            ir_module = optimize(ir_module)
            c_source = CEmitter().emit(ir_module)

            with tempfile.NamedTemporaryFile(suffix=".c", delete=False, mode="w") as f:
                f.write(c_source)
                c_path = f.name
            bin_path = c_path.removesuffix(".c")

            try:
                gcc_flags = ["gcc", c_path, "-o", bin_path, "-lm"]
                if "pthread.h" in c_source:
                    gcc_flags.append("-lpthread")
                result = subprocess.run(
                    gcc_flags,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    print(f"  SKIP {relative_path}: gcc failed")
                    continue

                result = subprocess.run(
                    [bin_path],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                stdout = result.stdout

                os.makedirs(expected_dir, exist_ok=True)
                out_path = os.path.join(expected_dir, f"{name}.stdout")
                with open(out_path, "w") as f:
                    f.write(stdout)
                print(f"  OK   {relative_path}")
                passed += 1
            finally:
                for path in [c_path, bin_path]:
                    if os.path.exists(path):
                        os.unlink(path)

        except Exception as error:
            print(f"  FAIL {relative_path}: {error}")
            failed += 1

    print(f"\nGenerated {passed} golden files ({failed} failed)")


if __name__ == "__main__":
    generate_expected()
