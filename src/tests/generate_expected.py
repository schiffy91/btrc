"""Generate expected output golden files for btrc tests.

For each test_*.btrc file, compile and run via the Python compiler,
then save the stdout to expected/<test_name>.stdout.
"""

import glob
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.compiler.python.lexer import Lexer
from src.compiler.python.parser import Parser
from src.compiler.python.analyzer import Analyzer
from src.compiler.python.codegen import CodeGen
from src.compiler.python.main import resolve_includes

BTRC_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
EXPECTED_DIR = os.path.join(BTRC_TEST_DIR, "expected")


def generate_expected():
    os.makedirs(EXPECTED_DIR, exist_ok=True)

    pattern = os.path.join(BTRC_TEST_DIR, "test_*.btrc")
    files = sorted(glob.glob(pattern))
    files = [f for f in files if "_helper" not in f]

    passed = 0
    failed = 0

    for btrc_path in files:
        name = os.path.basename(btrc_path).replace(".btrc", "")
        try:
            with open(btrc_path) as f:
                source = f.read()
            source = resolve_includes(source, btrc_path)

            tokens = Lexer(source, os.path.basename(btrc_path)).tokenize()
            program = Parser(tokens).parse()
            analyzed = Analyzer().analyze(program)
            if analyzed.errors:
                print(f"  SKIP {name}: analyzer errors")
                continue
            c_source = CodeGen(analyzed).generate()

            with tempfile.NamedTemporaryFile(suffix=".c", delete=False, mode="w") as f:
                f.write(c_source)
                c_path = f.name
            bin_path = c_path.replace(".c", "")

            try:
                result = subprocess.run(
                    ["gcc", c_path, "-o", bin_path, "-lm"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    print(f"  SKIP {name}: gcc failed")
                    continue

                result = subprocess.run(
                    [bin_path], capture_output=True, text=True, timeout=10,
                )
                stdout = result.stdout

                out_path = os.path.join(EXPECTED_DIR, f"{name}.stdout")
                with open(out_path, "w") as f:
                    f.write(stdout)
                print(f"  OK   {name}")
                passed += 1
            finally:
                for p in [c_path, bin_path]:
                    if os.path.exists(p):
                        os.unlink(p)

        except Exception as e:
            print(f"  FAIL {name}: {e}")
            failed += 1

    print(f"\nGenerated {passed} golden files ({failed} failed)")


if __name__ == "__main__":
    generate_expected()
