"""Source-order contracts for raw printf calls."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _compile_and_run(tmp_path: Path, compiler: str, generated: str):
    source = tmp_path / "printf_ordering.c"
    binary = tmp_path / "printf_ordering"
    source.write_text(generated)
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(binary),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    return subprocess.run(
        [str(binary)],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_printf_arguments_are_stabilized_in_source_order(tmp_path, c_compiler):
    generated = emit_c(
        """
        int main() {
            int value = 0;
            printf("%d %d\\n", (value = 1), value);
            return value == 1 ? 0 : 2;
        }
        """
    )

    first = re.search(r"__btrc_call_operand_\d+ = \(value = 1\)", generated)
    second = re.search(r"__btrc_call_operand_\d+ = value", generated)
    assert first and second
    assert first.start() < second.start()
    assert not re.search(r'printf\("%d %d\\n", \(value = 1\), value\)', generated)
    result = _compile_and_run(tmp_path, c_compiler, generated)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "1 1\n"


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_generic_printf_uses_the_same_ordering_boundary(tmp_path, c_compiler):
    generated = emit_c(
        """
        class Probe<T> {
            public Probe() {}
            public int run(T ignored) {
                (void)ignored;
                int value = 0;
                printf("%d %d\\n", (value = 1), value);
                return value;
            }
        }
        int main() {
            Probe<int> probe = new Probe<int>();
            return probe.run(0) == 1 ? 0 : 2;
        }
        """
    )

    method = generated[generated.index("btrc_Probe_int_run") :]
    first = re.search(r"__btrc_call_operand_\d+ = \(value = 1\)", method)
    second = re.search(r"__btrc_call_operand_\d+ = value", method)
    assert first and second
    assert first.start() < second.start()
    result = _compile_and_run(tmp_path, c_compiler, generated)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "1 1\n"


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_variadic_tail_preserves_named_default_order_and_c_promotions(tmp_path, c_compiler):
    generated = emit_c(
        """
        int trace = 0;

        int mark(int digit) {
            trace = trace * 10 + digit;
            return digit;
        }

        int pack(int a, int b = mark(4), int c = mark(5)) {
            return a * 100 + b * 10 + c;
        }

        int main() {
            char buffer[64];
            int written = snprintf(
                buffer,
                sizeof(buffer),
                "%d %.1f %d %d",
                pack(c = mark(3), a = mark(1)),
                (float)2.5,
                mark(6),
                trace
            );
            if (written != 14) { return 1; }
            if (strcmp(buffer, "143 2.5 6 3146") != 0) { return 2; }
            return trace == 3146 ? 0 : 3;
        }
        """
    )

    call = next(line for line in generated.splitlines() if "snprintf(" in line)
    assert call.count("__btrc_call_operand_") >= 7
    assert "((double)__btrc_call_operand_" in call
    result = _compile_and_run(tmp_path, c_compiler, generated)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_user_printf_remains_a_normal_declared_call(tmp_path, c_compiler):
    generated = emit_c(
        """
        int printf(int first, int second) { return first * 10 + second; }
        int main() {
            int value = 0;
            return printf((value = 2), value) == 22 ? 0 : 2;
        }
        """
    )

    assert "int __btrc_source_printf(int first, int second)" in generated
    assert "int printf(int first, int second)" not in generated
    result = _compile_and_run(tmp_path, c_compiler, generated)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_hosted_constant_macro_operand_is_never_given_an_invented_type(tmp_path, c_compiler):
    """A macro's expansion is unknown, so nothing may spell a C type for it.

    Both frontends sequence the typed operand of such a call; what neither may
    do is materialize the macro itself into a temporary whose type the compiler
    guessed. It is passed straight through to the hosted call.
    """

    generated = emit_c(
        """
        #include <signal.h>

        int main() {
            int signalNumber = (int)SIGPIPE;
            signal(signalNumber, SIG_IGN);
            signal(signalNumber, SIG_DFL);
            return 0;
        }
        """
    )

    assert not re.search(r"__btrc_call_operand_\d+\s*=\s*SIG_(?:IGN|DFL)\b", generated)
    assert re.search(r"signal\([^;]*,\s*SIG_IGN\)", generated)
    assert re.search(r"signal\([^;]*,\s*SIG_DFL\)", generated)
    result = _compile_and_run(tmp_path, c_compiler, generated)
    assert result.returncode == 0, result.stderr
