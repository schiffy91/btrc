"""Tests for .length projections, O(n) stdlib collection iteration, Array value equality,
main(Vector<string> args) entrypoints, and Platform.programName()."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.c_toolchains import HOST_C_COMPILERS
from src.tests.python.strict_c_fixtures import compile_and_run


def _analyze_raw(source: str):
    program = Parser(Lexer(source, "<elegance-check>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def _compile_stdlib_program(tmp_path: Path, name: str, source: str) -> str:
    source_path = tmp_path / f"{name}.btrc"
    source_path.write_text(source)
    result = Compiler().compile(
        source,
        str(source_path),
        CompilerOptions(use_cache=False),
    )
    assert result.successful, result.failure or result.diagnostics
    assert result.c_source is not None
    return result.c_source


@pytest.mark.parametrize(
    "source",
    [
        'int main() { string s = "abc"; s.length = 1; return 0; }',
        "import Library.Vector;\nint main() { Vector<int> v = [1, 2]; v.length = 0; return 0; }",
        "import Library.Bytes;\nint main() { Bytes b = Bytes(); b.length = 0; return 0; }",
        "int main(Vector<int> args) { return 0; }",
        "int main(string args) { return 0; }",
    ],
)
def test_readonly_length_and_invalid_main_are_rejected(tmp_path: Path, source: str) -> None:
    source_path = tmp_path / "invalid.btrc"
    source_path.write_text(source)
    result = Compiler().compile(
        source,
        str(source_path),
        CompilerOptions(use_cache=False),
    )
    assert not result.successful


def test_string_and_span_length_analyze_without_stdlib() -> None:
    analyzed = _analyze_raw(
        """
        int checkSpan(Span<int> items) {
            return (int)items.length;
        }
        int main() {
            string s = "hello";
            string? none = null;
            int a = s.length;
            int b = none?.length ?? 9;
            int backing[3] = {10, 20, 30};
            return (a == 5 && b == 9 && checkSpan(Span(backing)) == 3) ? 0 : 1;
        }
        """
    )
    assert analyzed.errors == []


@pytest.mark.skipif(not HOST_C_COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", HOST_C_COMPILERS, ids=lambda path: Path(path).name)
def test_direct_map_set_list_iteration_avoids_quadratic_iter_get(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    source = """
        import Library.List;
        import Library.Map;
        import Library.Set;

        int alive = 0;

        class Item {
            public int id;
            public Item(int id) { self.id = id; alive = alive + 1; }
            public void __del__() { alive = alive - 1; }
        }

        int sumEarlyReturn(Map<string, Item> table) {
            for key, item in table {
                if (key == "stop") {
                    return item.id;
                }
            }
            return -1;
        }

        int main() {
            {
                Map<string, Item> table = {};
                for (int i = 0; i < 40; i = i + 1) {
                    table.put(f"k{i}", new Item(i));
                }
                table.put("stop", new Item(99));

                int count = 0;
                for key, val in table {
                    if (val.id == 0) { continue; }
                    count = count + 1;
                    if (count == 10) { break; }
                }
                if (count != 10) { return 1; }
                if (sumEarlyReturn(table) != 99) { return 2; }
                if (table.length != 41) { return 3; }

                Set<string> tags = Set();
                for (int j = 0; j < 35; j = j + 1) {
                    tags.add(f"tag-{j}");
                }
                int tagSeen = 0;
                for tag in tags {
                    if (tag.length > 0) { tagSeen = tagSeen + 1; }
                }
                if (tagSeen != 35 || tags.length != 35) { return 4; }

                List<Item> chain = List();
                chain.push(new Item(10));
                chain.push(new Item(20));
                chain.push(new Item(30));
                int listSum = 0;
                for elem in chain {
                    listSum = listSum + elem.id;
                }
                if (listSum != 60 || chain.length != 3) { return 5; }
            }
            return alive == 0 ? 0 : 6;
        }
    """
    c_source = _compile_stdlib_program(tmp_path, "direct_iter", source)
    assert "_iterGet(" not in c_source
    assert "_iterValueAt(" not in c_source
    compile_and_run(c_source, tmp_path, c_compiler)


@pytest.mark.skipif(not HOST_C_COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", HOST_C_COMPILERS, ids=lambda path: Path(path).name)
def test_main_vector_string_args_and_program_name(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    source = """
        import Library.Platform;
        import Library.Vector;

        int main(Vector<string> args) {
            string prog = Platform.programName();
            if (prog.length == 0) { return 10; }
            if (args.length != 2) { return 11; }
            if (args[0] != "alpha" || args[1] != "beta") { return 12; }
            return 0;
        }
    """
    c_source = _compile_stdlib_program(tmp_path, "main_vector_args", source)
    c_file = tmp_path / "main_vector_args.c"
    exe = tmp_path / "main_vector_args_bin"
    c_file.write_text(c_source)
    build = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(c_file),
            "-o",
            str(exe),
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(exe), "alpha", "beta"], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr

    void_source = """
        import Library.Vector;

        void main(Vector<string> args) {
            assert(args.length == 1);
            assert(args[0] == "only");
        }
    """
    void_c = _compile_stdlib_program(tmp_path, "void_main_vector_args", void_source)
    void_c_file = tmp_path / "void_main_vector_args.c"
    void_exe = tmp_path / "void_main_vector_args_bin"
    void_c_file.write_text(void_c)
    build_void = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(void_c_file),
            "-o",
            str(void_exe),
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build_void.returncode == 0, build_void.stderr
    run_void = subprocess.run([str(void_exe), "only"], capture_output=True, text=True, check=False)
    assert run_void.returncode == 0, run_void.stderr
