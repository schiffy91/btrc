"""Strict-C contracts for values crossing printf's variadic boundary."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(compiler for compiler in (shutil.which("gcc"), shutil.which("clang")) if compiler is not None)
pytestmark = pytest.mark.skipif(not COMPILERS, reason="needs GCC or Clang")


@pytest.fixture(params=COMPILERS)
def c_compiler(request):
    return request.param


def _compile_and_run(tmp_path: Path, source: str, compiler: str):
    c_source = tmp_path / "printf_portability.c"
    executable = tmp_path / "printf_portability"
    c_source.write_text(source)
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(c_source),
            "-o",
            str(executable),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    return subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_print_and_fstring_adapt_nullable_pointer_and_callback_values(
    tmp_path,
    c_compiler,
):
    generated = emit_c(
        """
        int identity(int value) { return value; }
        int main() {
            string? missing = null;
            byte octet = (byte)255;
            int value = 7;
            int* pointer = &value;
            __fn_ptr<int, int> callback = identity;
            print(missing, octet, pointer, callback);
            string rendered = f"[{missing}|{octet}|{pointer}|{callback}]";
            print(rendered);
            return callback(3) == 3 ? 0 : 1;
        }
        """
    )

    # %s never receives a nullable source value directly, %p receives exactly
    # void*, and the byte argument is made exact after integer promotion.
    assert "__btrc_string_or_empty(missing)" in generated
    assert re.search(r'printf\("%s %u %p %s\\n",', generated)
    assert "((unsigned int)octet)" in generated
    assert "((void*)pointer)" in generated
    assert '(((void)callback), "<function>")' in generated

    result = _compile_and_run(tmp_path, generated, c_compiler)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("<function>") == 2
    assert "255" in result.stdout


def test_null_string_interpolation_has_defined_empty_string_semantics(
    tmp_path,
    c_compiler,
):
    generated = emit_c(
        'int main() { string? value = null; string text = f"<{value}>"; print(value); print(text); return 0; }'
    )

    assert generated.count("__btrc_string_or_empty(") >= 3
    result = _compile_and_run(tmp_path, generated, c_compiler)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n<>\n"


def test_generic_fstring_uses_the_same_null_safe_variadic_boundary(
    tmp_path,
    c_compiler,
):
    generated = emit_c(
        """
        class Box<T> {
            public T? value;
            public Box() { self.value = null; }
            public string render() { return f"<{self.value}>"; }
        }
        int main() {
            Box<string> box = new Box<string>();
            string result = box.render();
            print(result);
            return 0;
        }
        """
    )

    assert "<%s>" in generated
    render_start = generated.index("static char* btrc_Box_string_render(btrc_Box_string* self) {")
    render_end = generated.index("\n}", render_start)
    render = generated[render_start:render_end]
    assert render.count("__btrc_string_or_empty(") == 2
    result = _compile_and_run(tmp_path, generated, c_compiler)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "<>\n"


def test_whole_aggregates_never_cross_printf_varargs(tmp_path, c_compiler):
    generated = emit_c(
        """
        struct Point { int x; int y; };
        enum Color { RED, GREEN };
        enum class Shape { Circle(int radius), Point }

        int main() {
            (int, int) pair = (1, 2);
            struct Point point = {3, 4};
            Color color = GREEN;
            Shape shape = Shape.Circle(5);
            print(pair, point, shape, color);
            string rendered = f"{pair}|{point}|{shape}|{color}";
            print(rendered);
            return 0;
        }
        """
    )

    assert 'printf("%s %s %s %d\\n"' in generated
    assert '"<tuple>"' in generated
    assert '"<struct>"' in generated
    assert "Shape_toString(shape)" in generated
    assert "((int)color)" in generated
    assert not re.search(r'snprintf\([^\n]*"%d"[^\n]*_arg[01]\b', generated)

    result = _compile_and_run(tmp_path, generated, c_compiler)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ("<tuple> <struct> Circle 1\n<tuple>|<struct>|Circle|1\n")


def test_typedefs_use_their_canonical_variadic_types(tmp_path, c_compiler):
    generated = emit_c(
        """
        typedef char* Text;
        typedef bool Flag;
        typedef byte Octet;
        typedef int* IntPointer;

        int main() {
            Text missing = null;
            Flag enabled = true;
            Octet octet = (Octet)255;
            int value = 9;
            IntPointer pointer = &value;
            print(missing, enabled, octet, pointer);
            string rendered = f"{missing}|{enabled}|{octet}|{pointer}";
            print(rendered);
            return 0;
        }
        """
    )

    assert 'printf("%s %s %u %p\\n"' in generated
    assert "__btrc_string_or_empty(missing)" in generated
    assert '? "true" : "false"' in generated
    assert "((unsigned int)octet)" in generated
    assert "((void*)pointer)" in generated

    result = _compile_and_run(tmp_path, generated, c_compiler)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith(" true 255 ")
    assert lines[1].startswith("|true|255|")


def test_generic_print_and_len_share_typed_builtin_lowering(tmp_path, c_compiler):
    generated = emit_c(
        """
        typedef string Text;

        class Printer<T> {
            public Printer() {}
            public void show(T value) { print(value); }
            public string render(T value) { return f"{value}"; }
        }

        class Bucket {
            public int len;
            public Bucket(int length) { self.len = length; }
        }

        class Sizer<T> {
            public Sizer() {}
            public int size(T value) { return len(value); }
        }

        int main() {
            Printer<int> integers = new Printer<int>();
            integers.show(7);

            Printer<Text> strings = new Printer<Text>();
            strings.show(null);
            string empty = strings.render(null);
            print(empty);

            int value = 9;
            Printer<int*> pointers = new Printer<int*>();
            pointers.show(&value);

            (int, int) pair = (1, 2);
            Printer<(int, int)> tuples = new Printer<(int, int)>();
            tuples.show(pair);
            string tupleText = tuples.render(pair);
            print(tupleText);

            Sizer<Text> textSizer = new Sizer<Text>();
            if (textSizer.size(null) != 0) { return 2; }
            Sizer<Bucket> bucketSizer = new Sizer<Bucket>();
            Bucket bucket = new Bucket(4);
            if (bucketSizer.size(bucket) != 4) { return 3; }
            return 0;
        }
        """
    )

    assert "print(" not in generated
    assert not re.search(r"(?<![A-Za-z0-9_])len\(", generated)
    assert "__btrc_string_length(value)" in generated
    assert re.search(r"return value->len;", generated)
    assert 'printf("%s\\n",' in generated
    assert '"<tuple>"' in generated
    pointer_start = generated.index("static void btrc_Printer_int_p1_show(btrc_Printer_int_p1* self, int* value) {")
    pointer_end = generated.index("\n}", pointer_start)
    pointer_show = generated[pointer_start:pointer_end]
    assert 'printf("%p\\n"' in pointer_show
    assert "((void*)value)" in pointer_show

    result = _compile_and_run(tmp_path, generated, c_compiler)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[:3] == ["7", "", ""]
    assert lines[3]
    assert lines[4:] == ["<tuple>", "<tuple>"]


def test_generic_builtin_names_remain_shadowable(tmp_path, c_compiler):
    generated = emit_c(
        """
        int len(string value) { return value == null ? 77 : 78; }
        void print(int value) { printf("custom:%d\\n", value); }

        class Reporter<T> {
            public Reporter() {}
            public void report(T value) {
                (void)value;
                print(len("present"));
            }
        }

        int main() {
            Reporter<string> reporter = new Reporter<string>();
            reporter.report(null);
            return 0;
        }
        """
    )

    assert re.search(r'print\(len\("present"\)\)', generated)
    result = _compile_and_run(tmp_path, generated, c_compiler)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "custom:78\n"
