"""Braceless bodies and empty statements change syntax only (C rows 2 and 6).

docs/design/c-compatibility.md (d) and (c): an unbraced body of ``if``/``else``/
``while``/C-``for``/``do`` is a synthesized ``Block`` positioned at the body's
first token, and a lone ``;`` is an empty ``Block`` at the ``;`` (or nothing at
all inside a statement list). The block keeps the scope a braced body has, so
the analyzer and lowering need no change. These tests prove it: each braceless
program lowers to the same raw IR (``--emit-ir``, before the optimizer) and the
same C, with and without ``--debug``, as its braced twin -- including bodies
that create and release managed temporaries, ``else if`` chains, nesting, a
dangling ``else`` and ``break``/``continue``/``return`` -- through both
compilers; each compiler's own ``--emit-ir`` dump is the raw-IR comparison
(the two compilers' IR models differ, so their dumps are never compared with
each other). The canonical AST, positions included, matches between the two
parsers.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.c_compatibility_harness import reference_output, relative_to_program, selfhost_output, write_program

REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "src/tests/c_compat"
PARSE_TOOL = REPO / "src/compiler/btrc/tools/ParseMain.btrc"

# Each pair is (braced, braceless); a body stays on its line, so positions
# outside the synthesized blocks, and every #line marker, are identical.
PAIRS = [
    pytest.param(
        """
        int main() {
            int x = 4;
            string s = "";
            bool c = x > 2;
            if (c) { s = f"{x}"; }
            if (!c) { s = f"no {x}"; } else { s = f"yes {x}"; }
            print(s);
            return 0;
        }
        """,
        """
        int main() {
            int x = 4;
            string s = "";
            bool c = x > 2;
            if (c)   s = f"{x}";
            if (!c)   s = f"no {x}";   else   s = f"yes {x}";
            print(s);
            return 0;
        }
        """,
        id="if-else-managed-temporaries",
    ),
    pytest.param(
        """
        import Library.Vector;
        int main() {
            Vector<int> v = [];
            int i = 0;
            int n = 3;
            while (i < n) { v.push(i++); }
            for (int k = 0; k < n; k++) { v.push(k * 2); }
            do { v.push(i--); } while (i > 0);
            print(f"{v.len}");
            return 0;
        }
        """,
        """
        import Library.Vector;
        int main() {
            Vector<int> v = [];
            int i = 0;
            int n = 3;
            while (i < n)   v.push(i++);
            for (int k = 0; k < n; k++)   v.push(k * 2);
            do   v.push(i--);   while (i > 0);
            print(f"{v.len}");
            return 0;
        }
        """,
        id="loops-managed-receivers",
    ),
    pytest.param(
        """
        int classify(int a, int b) {
            int result = 0;
            if (a) { if (b) { result = 1; } else { result = 2; } }
            for (int i = 0; i < 4; i++) { if (i == 2) { continue; } else if (i == 3) { break; } }
            if (a) { return result; }
            return -result;
        }
        int main() { return classify(1, 0) - 2; }
        """,
        """
        int classify(int a, int b) {
            int result = 0;
            if (a)   if (b)   result = 1;   else   result = 2;
            for (int i = 0; i < 4; i++)   if (i == 2)   continue;   else if (i == 3)   break;
            if (a)   return result;
            return -result;
        }
        int main() { return classify(1, 0) - 2; }
        """,
        id="dangling-else-and-jumps",
    ),
    pytest.param(
        """
        int main() {
            int i;
            int values[3] = {2, 1, 0};
            int* p = values;
            for (i = 0; i < 5; i++) {}

            while (*p++) {}
            if (i == 5) {} else { i = 0; }
            do {} while (i-- > 3);
            return i == 2 ? 0 : 1;
        }
        """,
        """
        int main() {
            int i;
            int values[3] = {2, 1, 0};
            int* p = values;
            for (i = 0; i < 5; i++);
            ;;
            while (*p++);
            if (i == 5) ; else   i = 0;
            do ; while (i-- > 3);
            return i == 2 ? 0 : 1;;
        }
        """,
        id="empty-statements",
    ),
    pytest.param(
        """
        string grade(int score) {
            string label = f"score {score}";
            if (score > 90) { return f"A {label}"; } else if (score > 80) { label = f"B {label}"; } else if (score > 70) { label = f"C {label}"; } else { return label; }
            return label;
        }
        int main() { print(grade(85)); print(grade(10)); return 0; }
        """,
        """
        string grade(int score) {
            string label = f"score {score}";
            if (score > 90)   return f"A {label}";   else if (score > 80)   label = f"B {label}";   else if (score > 70)   label = f"C {label}";   else   return label;
            return label;
        }
        int main() { print(grade(85)); print(grade(10)); return 0; }
        """,
        id="else-if-chain-managed-returns",
    ),
    pytest.param(
        """
        import Library.Vector;
        int main() {
            Vector<string> names = [];
            for (int i = 0; i < 4; i++) { for (int j = 0; j < 4; j++) { if (j > i) { break; } else if (j == 1) { continue; } else { names.push(f"{i}:{j}"); } } }
            int k = 0;
            while (k < 6) { if (k++ % 2 == 0) { continue; } else { names.push(f"odd {k}"); } }
            do { if (names.len > 100) { return 1; } } while (names.len > 1000);
            print(f"{names.len}");
            return 0;
        }
        """,
        """
        import Library.Vector;
        int main() {
            Vector<string> names = [];
            for (int i = 0; i < 4; i++)   for (int j = 0; j < 4; j++)   if (j > i)   break;   else if (j == 1)   continue;   else   names.push(f"{i}:{j}");
            int k = 0;
            while (k < 6)   if (k++ % 2 == 0)   continue;   else   names.push(f"odd {k}");
            do   if (names.len > 100)   return 1;   while (names.len > 1000);
            print(f"{names.len}");
            return 0;
        }
        """,
        id="nested-loops-managed-jumps",
    ),
    pytest.param(
        """
        class Counter { public int value; public Counter(int value) { self.value = value; } }
        Counter pick(int a, int b) {
            Counter chosen = new Counter(0);
            if (a) { if (b) { chosen = new Counter(1); } else { chosen = new Counter(2); } }
            while (chosen.value < 5) { if (chosen.value == 3) { break; } chosen = new Counter(chosen.value + 1); }
            for (int i = 0; i < 2; i++) { if (i) { return chosen; } }
            return new Counter(-1);
        }
        int main() { return pick(1, 0).value == 3 ? 0 : 1; }
        """,
        """
        class Counter { public int value; public Counter(int value) { self.value = value; } }
        Counter pick(int a, int b) {
            Counter chosen = new Counter(0);
            if (a)   if (b)   chosen = new Counter(1);   else   chosen = new Counter(2);
            while (chosen.value < 5) { if (chosen.value == 3)   break;   chosen = new Counter(chosen.value + 1); }
            for (int i = 0; i < 2; i++)   if (i)   return chosen;
            return new Counter(-1);
        }
        int main() { return pick(1, 0).value == 3 ? 0 : 1; }
        """,
        id="dangling-else-managed-objects",
    ),
]


@pytest.mark.parametrize(("braced", "braceless"), PAIRS)
def test_braceless_body_lowers_exactly_like_its_braced_twin(
    semantic_btrcc: Path,
    tmp_path: Path,
    braced: str,
    braceless: str,
) -> None:
    left = write_program(tmp_path / "braced", braced)
    right = write_program(tmp_path / "braceless", braceless)

    for flags in (("--emit-ir",), (), ("--debug",)):
        assert relative_to_program(reference_output(left, *flags), left) == relative_to_program(
            reference_output(right, *flags), right
        ), flags
    for flags in (("--emit-ir",), (), ("--debug",)):
        assert relative_to_program(selfhost_output(semantic_btrcc, left, *flags), left) == relative_to_program(
            selfhost_output(semantic_btrcc, right, *flags), right
        ), flags


def _source_lines(generated: str, statement: str) -> list[int]:
    """The source lines ``#line`` assigns to each C line containing *statement*."""
    found = []
    current = None
    for text in generated.splitlines():
        marker = re.match(r'#line (\d+)(?: "[^"]*")?$', text)
        if marker is not None:
            current = int(marker.group(1))
            continue
        if current is not None:
            if statement in text:
                found.append(current)
            current += 1
    return found


def test_debug_line_markers_map_braceless_bodies_to_their_own_lines(semantic_btrcc: Path, tmp_path: Path) -> None:
    program = write_program(
        tmp_path,
        "int main() {\n"
        "\tint x = 0;\n"
        "\tif (x == 0) x = 11;\n"
        "\tif (x == 11)\n"
        "\t\tx = 12;\n"
        "\telse x = 13;\n"
        "\twhile (x < 0) x = 14;\n"
        "\tfor (int i = 0; i < 2; i++)\n"
        "\t\tx = 15;\n"
        "\treturn x;\n"
        "}\n",
    )
    for generated in (reference_output(program, "--debug"), selfhost_output(semantic_btrcc, program, "--debug")):
        lines = {value: _source_lines(generated, f"(x = {value})") for value in range(11, 16)}
        assert lines == {11: [3], 12: [5], 13: [6], 14: [7], 15: [9]}, generated


@pytest.fixture(scope="module")
def parse_tool(selfhost_driver) -> Path:
    return selfhost_driver(PARSE_TOOL, compile_flags=("-pedantic-errors",))


@pytest.mark.parametrize(
    "corpus",
    ["BracelessBodies.btrc", "EmptyStatement.btrc"],
)
def test_canonical_ast_and_positions_match_the_reference(parse_tool: Path, corpus: str) -> None:
    program = CORPUS / corpus
    parsed = subprocess.run([str(parse_tool), str(program)], capture_output=True, text=True, timeout=30)
    reference = subprocess.run(
        [sys.executable, "-m", "tools.compiler_codegen.main", "dump-ast", str(program)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert parsed.returncode == 0, parsed.stderr
    assert reference.returncode == 0, reference.stderr
    assert parsed.stdout == reference.stdout


def test_selfhost_ir_dumps_precede_and_follow_the_optimizer(semantic_btrcc: Path, tmp_path: Path) -> None:
    """btrcc's ``--emit-ir`` is the raw module, ``--emit-optimized-ir`` the optimized one."""
    program = write_program(tmp_path, "int unused(int a) { return a; }\nint main() { return 0; }\n")
    raw = selfhost_output(semantic_btrcc, program, "--emit-ir")
    optimized = selfhost_output(semantic_btrcc, program, "--emit-optimized-ir")
    assert raw.startswith('$format btrcc-ir-v1\nmodule language="c"\n')
    assert 'function name="main" returnType="int"' in raw and 'function name="main" returnType="int"' in optimized
    # The optimizer removes the unreachable function the raw dump still holds.
    assert 'function name="unused"' in raw and 'function name="unused"' not in optimized
    for flags in (("--emit-ir", "--emit-optimized-ir"), ("--emit-ir", "--emit-units", str(tmp_path / "units"))):
        result = subprocess.run(
            [str(semantic_btrcc), "--no-stdlib", *flags, str(program)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode != 0 and "--emit-ir" in result.stderr, flags
