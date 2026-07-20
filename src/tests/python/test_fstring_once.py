"""Regression tests: f-string interpolations must evaluate each expression
exactly once.

The lowering sizes the buffer with a measure pass (snprintf NULL/0) and then
fills it with a write pass. It declares typed temporaries ahead of the enclosing
statement, then assigns them in a comma expression at the semantic evaluation
site. Both snprintf passes reuse those values, so side-effecting expressions
run once without breaking short-circuit, ternary, or loop-condition semantics.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _snprintf_calls(c: str) -> list[str]:
    return re.findall(r"snprintf\(", c)


def test_side_effecting_call_evaluated_once():
    """A call is evaluated before either formatting pass and only once."""
    c = emit_c('int next() { return 1; }\nint main() { string s = f"{next()}"; return 0; }\n')
    assert c.count("next()") == 1, c
    calls = _snprintf_calls(c)
    assert len(calls) == 2, calls  # measure + write
    assert c.index("next()") < c.index("snprintf(NULL, 0"), c


def test_multiple_interpolations_each_evaluated_once():
    """Every interpolation is evaluated once before formatting begins."""
    c = emit_c('int next() { return 1; }\nint main() { string s = f"{next()} {next()} {next()}"; return 0; }\n')
    evaluations = [match.start() for match in re.finditer(r"next\(\)", c)]
    assert len(evaluations) == 3, c
    assert max(evaluations) < c.index("snprintf(NULL, 0"), c
    assert "snprintf(NULL, 0" in c


def test_interpolations_use_matching_variadic_formats():
    """Each source value crosses both formatting passes with its C format."""
    c = emit_c(
        "int main() {\n"
        "  int i = 1; double d = 2.0; bool b = true; char ch = 'x';\n"
        '  string s = "hi";\n'
        '  string r = f"{i} {d} {b} {ch} {s}";\n'
        "  return 0;\n"
        "}\n"
    )
    assert c.count('"%d %f %s %c %s"') == 2, c
    assert '? "true" : "false"' in c, c
    assert c.count("__btrc_string_or_empty(") >= 3, c


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_control_sensitive_evaluation_stays_inside_expression(tmp_path, c_compiler):
    c = emit_c(
        "int calls = 0;\n"
        "int tick() { calls++; return 1; }\n"
        "int main() {\n"
        '  bool skipped = false && f"{tick()}".len() > 0;\n'
        '  string chosen = true ? "yes" : f"{tick()}";\n'
        '  int n = 0; while (n < 2 && f"{tick()}".len() > 0) { n++; }\n'
        "  return !skipped && chosen[0] == 'y' && n == 2 && calls == 2 ? 0 : 1;\n"
        "}\n"
    )
    source = tmp_path / "fstring_control.c"
    executable = tmp_path / "fstring_control"
    source.write_text(c)
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    subprocess.run([str(executable)], check=True, timeout=15)


def test_no_args_fstring_is_plain_literal():
    """An f-string with no interpolations still lowers to a bare literal --
    no snprintf, no temps."""
    c = emit_c('int main() { string s = f"hello"; return 0; }')
    assert "snprintf" not in c
    assert '"hello"' in c
