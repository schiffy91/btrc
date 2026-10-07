"""Both compilers decide lambda termination with one predicate (D-13).

btrcc used to check lambda bodies with a third termination predicate,
ExpressionTypeResolver's, which had no switch or loop rule, so it refused
typed lambdas that the reference compiler accepts. Its only lambda check is
now ControlFlowValidator's, which mirrors ControlFlowAnalyzer's rules.

The negative wording still differs between the compilers; r15b's D-7
unification owns that change, so each compiler's current text is pinned here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.tests.btrc.selfhost_snippet_harness import (
    CC,
    compile_reference_source,
    compile_source,
    strict_build_and_run,
)

pytestmark = pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)

REFERENCE_MESSAGE = "Non-void lambda does not return a value on every path"
SELFHOST_MESSAGE = "Non-void lambda does not return on every path"

TERMINATING_BODIES = {
    "infinite-while": "while (true) { return n; }",
    "switch-with-default": "switch (n) { case 1: return n; default: return n; }",
    "infinite-for": "for (;;) { return n; }",
    "do-while": "do { return n; } while (n > 0);",
    "nested-terminating-switch": "if (n > 100) { return 0; } else { switch (n) { default: { return n; } } }",
}

FALLING_BODIES = {
    "loop-with-break": "while (true) { if (n > 0) { break; } return n; }",
    "switch-without-default": "switch (n) { case 1: return n; case 2: return n; }",
    "conditional-loop": "while (n > 0) { return n; }",
}


def _program(body: str) -> str:
    return f"""
        int main() {{
            var pick = int function(int n) {{
                {body}
            }};
            if (pick(7) != 7) {{ return 1; }}
            return 0;
        }}
    """


def _array_bound_program(body: str) -> str:
    """A local array bound is prepared like any other expression, so its lambda gets the same check."""
    return f"""
        int main() {{
            int values[(int function(int n) {{ {body} }})(2)];
            values[0] = 0;
            values[1] = 0;
            return values[0] + values[1];
        }}
    """


def _parameter_bound_program(body: str) -> str:
    return f"""
        int main() {{
            var first = int function(int values[(int function(int n) {{ {body} }})(2)]) {{ return values[0]; }};
            int data[2] = {{0, 0}};
            return first(data);
        }}
    """


def _global_bound_program(body: str) -> str:
    """A global bound must be constant, so only the refusal order is shared: the lambda's comes first."""
    return f"""
        int values[(int function(int n) {{ {body} }})(2)];
        int main() {{ return 0; }}
    """


def _reference_position(output: str) -> str:
    return output.split(".btrc:", 1)[1].split()[0]


def _selfhost_position(output: str) -> str:
    # btrcc renders the position as the reference does.
    return _reference_position(output)


PROGRAMS = {
    "local": _program,
    "array-bound": _array_bound_program,
    "lambda-parameter-bound": _parameter_bound_program,
}
REFUSED_PROGRAMS = {**PROGRAMS, "global-bound": _global_bound_program}


@pytest.mark.parametrize("program", PROGRAMS.values(), ids=PROGRAMS.keys())
@pytest.mark.parametrize("body", TERMINATING_BODIES.values(), ids=TERMINATING_BODIES.keys())
def test_terminating_lambda_bodies_are_accepted_by_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    program,
    body: str,
) -> None:
    source = program(body)
    reference, reference_c = compile_reference_source(tmp_path, source)
    selfhost, selfhost_c = compile_source(semantic_btrcc, tmp_path, source)
    assert reference.returncode == 0, reference.stdout + reference.stderr
    assert selfhost.returncode == 0, selfhost.stdout + selfhost.stderr
    strict_build_and_run(reference_c, tmp_path / "reference-program")
    strict_build_and_run(selfhost_c, tmp_path / "selfhost-program")


@pytest.mark.parametrize("program", REFUSED_PROGRAMS.values(), ids=REFUSED_PROGRAMS.keys())
@pytest.mark.parametrize("body", FALLING_BODIES.values(), ids=FALLING_BODIES.keys())
def test_falling_lambda_bodies_are_refused_by_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    program,
    body: str,
) -> None:
    source = program(body)
    reference, _ = compile_reference_source(tmp_path, source)
    selfhost, _ = compile_source(semantic_btrcc, tmp_path, source)
    reference_output = reference.stdout + reference.stderr
    assert reference.returncode != 0
    assert REFERENCE_MESSAGE in reference_output
    assert selfhost.returncode == 1
    assert selfhost.stdout == ""
    assert SELFHOST_MESSAGE in selfhost.stderr
    assert _selfhost_position(selfhost.stderr) == _reference_position(reference_output)
