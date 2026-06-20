"""Regression tests: f-string interpolations must evaluate each expression
exactly once.

The lowering sizes the buffer with a measure pass (snprintf NULL/0) and then
fills it with a write pass. It must hoist every interpolated expression into a
temporary first and reuse that temp in BOTH passes, so side-effecting
expressions (counters, RNG, pop(), I/O) do not run twice.
"""

import re

from src.tests.python.test_codegen import emit_c


def _snprintf_calls(c: str) -> list[str]:
    return [ln for ln in c.splitlines() if "snprintf(" in ln]


def test_side_effecting_call_evaluated_once():
    """A call inside an interpolation appears once (in a temp decl), and the
    two snprintf passes reference the temp -- not the call -- so it runs once.
    """
    c = emit_c(
        "int next() { return 1; }\n"
        "int main() { string s = f\"{next()}\"; return 0; }\n"
    )
    # The call itself is emitted exactly once across the whole function.
    assert c.count("next()") == 1, c
    # That single occurrence is a hoisted temp initialiser, not an snprintf arg.
    calls = _snprintf_calls(c)
    assert len(calls) == 2, calls  # measure + write
    for call in calls:
        assert "next()" not in call, call
    # Both passes reference the same hoisted temp.
    m = re.search(r"=\s*next\(\);", c)
    assert m, c


def test_multiple_interpolations_each_hoisted_once():
    """Three side-effecting interpolations -> three temps, three single calls,
    and neither snprintf pass contains a raw call."""
    c = emit_c(
        "int next() { return 1; }\n"
        "int main() { string s = f\"{next()} {next()} {next()}\"; return 0; }\n"
    )
    assert c.count("next()") == 3, c
    assert len(re.findall(r"_arg\d+\s*=\s*next\(\);", c)) == 3, c
    for call in _snprintf_calls(c):
        assert "next()" not in call, call


def test_typed_temps_match_value_type():
    """Hoist temps carry the value's C type so the stored value is exact."""
    c = emit_c(
        "int main() {\n"
        "  int i = 1; double d = 2.0; bool b = true; char ch = 'x';\n"
        "  string s = \"hi\";\n"
        "  string r = f\"{i} {d} {b} {ch} {s}\";\n"
        "  return 0;\n"
        "}\n"
    )
    assert re.search(r"int\s+\S+_arg0\s*=", c), c
    assert re.search(r"double\s+\S+_arg1\s*=", c), c
    # bool is hoisted as a bool, then formatted via a (pure) ternary.
    assert re.search(r"bool\s+\S+_arg2\s*=", c), c
    assert "? \"true\" : \"false\"" in c, c
    assert re.search(r"char\s+\S+_arg3\s*=", c), c
    assert re.search(r"char\*\s+\S+_arg4\s*=", c), c


def test_no_args_fstring_is_plain_literal():
    """An f-string with no interpolations still lowers to a bare literal --
    no snprintf, no temps."""
    c = emit_c("int main() { string s = f\"hello\"; return 0; }")
    assert "snprintf" not in c
    assert '"hello"' in c
