"""Strict-C contracts for built-in method dispatch through typedef chains."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
            typedef Mutex<int> GateBase;
            typedef GateBase Gate;

            int main() {
                Gate gate = new Mutex<int>(3);
                gate.set(gate.get() + 4);
                int result = gate.get();
                return result == 7 ? 0 : 1;
            }
            """,
            id="mutex",
        ),
        pytest.param(
            """
            typedef string TextBase;
            typedef TextBase Text;

            int main() {
                Text value = " hello ";
                Text trimmed = value.trim();
                return trimmed.len() == 5 ? 0 : 1;
            }
            """,
            id="string",
        ),
    ],
)
def test_typedef_aliased_builtin_methods_execute_under_strict_c11(
    tmp_path: Path,
    c_compiler: str,
    source: str,
) -> None:
    generated = emit_c(source)
    assert re.search(r"\.(?:get|set|trim|len)\(", generated) is None

    generated_path = tmp_path / "typedef_builtin.c"
    executable = tmp_path / "typedef_builtin"
    generated_path.write_text(generated)
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror=implicit-function-declaration",
            "-O1",
            str(generated_path),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    subprocess.run(
        [str(executable)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
