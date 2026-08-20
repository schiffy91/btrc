"""Terminal throw operands remain owned until exception cleanup consumes them."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _compile_and_run(generated: str, tmp_path: Path, compiler: str, stem: str) -> None:
    source = tmp_path / f"{stem}.c"
    executable = tmp_path / stem
    source.write_text(generated)
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert executed.returncode == 0, executed.stderr


CASES = (
    (
        "fstring",
        "tick",
        """
            int evaluations = 0;

            int tick() {
                evaluations++;
                return evaluations;
            }

            int main() {
                int baseline = (int)__btrc_string_live_count();
                try {
                    throw f"owned-{tick()}";
                } catch (string error) {
                    if (!error.equals("owned-1")) { return 2; }
                }
                return evaluations == 1 && (int)__btrc_string_live_count() == baseline ? 0 : 3;
            }
        """,
    ),
    (
        "owned_call",
        "build",
        """
            int evaluations = 0;

            string build() {
                evaluations++;
                return f"owned-{evaluations}";
            }

            int main() {
                int baseline = (int)__btrc_string_live_count();
                try {
                    throw build();
                } catch (string error) {
                    if (!error.equals("owned-1")) { return 2; }
                }
                return evaluations == 1 && (int)__btrc_string_live_count() == baseline ? 0 : 3;
            }
        """,
    ),
)


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("case_name,evaluated_symbol,source", CASES, ids=("fstring", "owned_call"))
def test_owned_throw_operand_is_released_once_on_caught_unwind(
    tmp_path: Path,
    c_compiler: str,
    case_name: str,
    evaluated_symbol: str,
    source: str,
) -> None:
    generated = emit_c(source)
    main = generated[generated.index("int main(void)") :]
    terminal = re.search(r"char\* volatile (__btrc_terminal_operand_\d+) =", main)
    assert terminal is not None
    slot = terminal.group(1)
    registration = main.index(f"((void*)(&{slot}))")
    throwing = main.index(f"__btrc_throw({slot})")
    assert registration < throwing
    assert f"{slot} = NULL" not in main[registration:throwing]
    assert main.count(f"{evaluated_symbol}()") == 1

    _compile_and_run(generated, tmp_path, c_compiler, f"throw_{case_name}_{Path(c_compiler).name}")
