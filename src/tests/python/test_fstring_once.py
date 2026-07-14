"""Regression tests: f-string interpolations must evaluate each expression
exactly once.

The lowering sizes the buffer with a measure pass (snprintf NULL/0) and then
fills it with a write pass. It declares typed temporaries ahead of the enclosing
statement, then assigns them in a comma expression at the semantic evaluation
site. Both snprintf passes reuse those values, so side-effecting expressions
run once without breaking short-circuit, ternary, or loop-condition semantics.
"""

import re

from src.tests.python.test_codegen import emit_c


def _snprintf_calls(c: str) -> list[str]:
    return re.findall(r"snprintf\(", c)


def test_side_effecting_call_evaluated_once():
    """A call inside an interpolation appears once (in a temp decl), and the
    two snprintf passes reference the temp -- not the call -- so it runs once.
    """
    c = emit_c('int next() { return 1; }\nint main() { string s = f"{next()}"; return 0; }\n')
    # The call itself is emitted exactly once across the whole function.
    assert c.count("next()") == 1, c
    # That single occurrence assigns a typed temp, never an snprintf argument.
    calls = _snprintf_calls(c)
    assert len(calls) == 2, calls  # measure + write
    # Both passes reference the same hoisted temp.
    m = re.search(r"_arg0\s*=\s*next\(\)", c)
    assert m, c


def test_multiple_interpolations_each_hoisted_once():
    """Three side-effecting interpolations -> three temps, three single calls,
    and neither snprintf pass contains a raw call."""
    c = emit_c('int next() { return 1; }\nint main() { string s = f"{next()} {next()} {next()}"; return 0; }\n')
    assert c.count("next()") == 3, c
    assert len(re.findall(r"_arg\d+\s*=\s*next\(\)", c)) == 3, c
    assert "snprintf(NULL, 0" in c


def test_typed_temps_match_value_type():
    """Hoist temps carry the value's C type so the stored value is exact."""
    c = emit_c(
        "int main() {\n"
        "  int i = 1; double d = 2.0; bool b = true; char ch = 'x';\n"
        '  string s = "hi";\n'
        '  string r = f"{i} {d} {b} {ch} {s}";\n'
        "  return 0;\n"
        "}\n"
    )
    assert re.search(r"int\s+\S+_arg0\s*;", c), c
    assert re.search(r"double\s+\S+_arg1\s*;", c), c
    # bool is hoisted as a bool, then formatted via a (pure) ternary.
    assert re.search(r"bool\s+\S+_arg2\s*;", c), c
    assert '? "true" : "false"' in c, c
    assert re.search(r"char\s+\S+_arg3\s*;", c), c
    assert re.search(r"char\*\s+\S+_arg4\s*;", c), c


def test_control_sensitive_evaluation_stays_inside_expression():
    c = emit_c(
        "int tick() { return 1; }\n"
        "int main() {\n"
        '  bool skipped = false && f"{tick()}".len() > 0;\n'
        '  string chosen = true ? "yes" : f"{tick()}";\n'
        '  int n = 0; while (n < 2 && f"{tick()}".len() > 0) { n++; }\n'
        "  return skipped ? chosen.len() : n;\n"
        "}\n"
    )
    # Declarations are harmlessly hoisted; tick() remains in each enclosing
    # &&/?:/while expression rather than becoming an unconditional statement.
    assert not re.search(r"^\s*\S+_arg\d+\s*=\s*tick\(\);", c, re.MULTILINE), c
    assert c.count("tick()") == 3, c
    assert "while ((n < 2) &&" in c


def test_no_args_fstring_is_plain_literal():
    """An f-string with no interpolations still lowers to a bare literal --
    no snprintf, no temps."""
    c = emit_c('int main() { string s = f"hello"; return 0; }')
    assert "snprintf" not in c
    assert '"hello"' in c
