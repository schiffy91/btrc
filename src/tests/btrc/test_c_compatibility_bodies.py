"""Braceless bodies and empty statements change syntax only (C rows 2 and 6).

docs/design/c-compatibility.md (d) and (c): an unbraced body of ``if``/``else``/
``while``/C-``for``/``do`` is a synthesized ``Block`` positioned at the body's
first token, and a lone ``;`` is an empty ``Block`` at the ``;`` (or nothing at
all inside a statement list). The block keeps the scope a braced body has, so
the analyzer and lowering need no change. These tests prove it: each braceless
program lowers to the same raw IR (``--emit-ir``, before the optimizer) and the
same C, with and without ``--debug``, as its braced twin -- including bodies
that create and release managed temporaries -- through both compilers. btrcc
has no ``--emit-ir``, so its C output carries the comparison. The canonical
AST, positions included, matches between the two parsers.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

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
]


def _write(directory: Path, source: str) -> Path:
    """Write *source* as ``Program.btrc`` so file names never differ."""
    directory.mkdir(parents=True, exist_ok=True)
    program = directory / "Program.btrc"
    program.write_text(source)
    return program


def _reference(program: Path, *flags: str) -> str:
    """The reference compiler's ``--emit-ir`` dump, else its generated C."""
    output = program.with_suffix(".c")
    command = [sys.executable, "-m", "src.compiler.python.main", str(program), "--no-stdlib", "--no-cache", *flags]
    if "--emit-ir" not in flags:
        command.extend(["-o", str(output)])
    result = subprocess.run(
        command,
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(program.parent / "cache")},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout if "--emit-ir" in flags else output.read_text()


def _selfhost(compiler: Path, program: Path, *flags: str) -> str:
    result = subprocess.run(
        [str(compiler), "--no-stdlib", *flags, str(program)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _relative(text: str, program: Path) -> str:
    return text.replace(str(program.parent), "<dir>")


@pytest.mark.parametrize(("braced", "braceless"), PAIRS)
def test_braceless_body_lowers_exactly_like_its_braced_twin(
    semantic_btrcc: Path,
    tmp_path: Path,
    braced: str,
    braceless: str,
) -> None:
    left = _write(tmp_path / "braced", braced)
    right = _write(tmp_path / "braceless", braceless)

    for flags in (("--emit-ir",), (), ("--debug",)):
        assert _relative(_reference(left, *flags), left) == _relative(_reference(right, *flags), right), flags
    for flags in ((), ("--debug",)):
        assert _relative(_selfhost(semantic_btrcc, left, *flags), left) == _relative(
            _selfhost(semantic_btrcc, right, *flags), right
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
    program = _write(
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
    for generated in (_reference(program, "--debug"), _selfhost(semantic_btrcc, program, "--debug")):
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
