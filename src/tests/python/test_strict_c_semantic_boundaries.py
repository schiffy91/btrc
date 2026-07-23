"""SemanticAnalyzer and IR boundaries required for valid strict-C output."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.lowerer import IRLowerer
from src.compiler.python.ir.optimizer import IROptimizer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _analyze(source: str):
    program = Parser(Lexer(source, "<strict-c-boundary>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def _errors(source: str) -> list[str]:
    return _analyze(source).errors


def _has(errors: list[str], text: str) -> bool:
    return any(text.lower() in error.lower() for error in errors)


def _emit(source: str):
    analyzed = _analyze(source)
    assert analyzed.errors == []
    module = IRLowerer(analyzed).lower()
    return module, CEmitter().emit(IROptimizer(module).optimize())


def _compile_and_run(c_source: str, tmp_path: Path, compiler: str):
    source_path = tmp_path / "program.c"
    binary_path = tmp_path / "program"
    source_path.write_text(c_source)
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source_path),
            "-o",
            str(binary_path),
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    ran = subprocess.run([str(binary_path)], capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stderr
    return ran


def test_known_struct_rejects_unknown_field_but_preserves_c_opaque_structs():
    errors = _errors("""
        struct Point { int x; };
        void run(struct Point* point) { int value = point->y; }
    """)
    opaque = _analyze("""
        void run(struct NativeHandle* handle) { int value = handle->status; }
    """)

    assert _has(errors, "Struct 'Point' has no field 'y'")
    assert opaque.errors == []


def test_known_struct_field_remains_valid():
    result = _analyze("""
        struct Point { int x; };
        int read(struct Point* point) { return point->x; }
    """)
    assert result.errors == []


@pytest.mark.parametrize(
    ("source", "message"),
    (
        (
            "void action() {} void run() { int value = (int)action(); }",
            "Cannot cast void expression to 'int'",
        ),
        (
            "struct Point { int x; }; void run() { Point value = (Point)1; }",
            "Cannot cast scalar 'int' to aggregate struct 'Point'",
        ),
        (
            "void run() { Vector<int> value = (Vector<int>)1; }",
            "Cannot cast scalar 'int' to runtime generic value 'Vector<int>'",
        ),
    ),
)
def test_nonrepresentable_c_casts_are_rejected(source: str, message: str):
    assert _has(_errors(source), message)


def test_numeric_pointer_typedef_enum_and_void_discard_casts_remain_valid():
    result = _analyze("""
        typedef unsigned int UnsignedAlias;
        enum Color { RED, GREEN };
        void action() {}
        void run() {
            double source = 3.5;
            int number = (int)source;
            UnsignedAlias wide = (UnsignedAlias)number;
            void* opaque = (void*)&number;
            int* pointer = (int*)opaque;
            Color color = (Color)number;
            (void)wide;
            (void)pointer;
            (void)color;
            (void)action();
        }
    """)
    assert result.errors == []


def test_builtin_byte_and_uint_cast_targets_remain_valid():
    result = _analyze("""
        void run() {
            int source = 513;
            byte octet = (byte)source;
            uint wide = (uint)source;
            (void)octet;
            (void)wide;
        }
    """)
    assert result.errors == []


@pytest.mark.parametrize("literal", ("{1, 2}", "[1, 2]"))
def test_overfull_fixed_array_initializer_is_rejected(literal: str):
    errors = _errors(f"void run() {{ int values[1] = {literal}; }}")
    assert _has(errors, "2 elements but fixed array bound is 1")


def test_exact_and_underfull_fixed_array_initializers_remain_valid():
    result = _analyze("""
        void run() { int exact[2] = {1, 2}; int partial[2] = {1}; }
    """)
    assert result.errors == []


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_empty_fixed_array_initializer_is_normalized_to_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    _, generated = _emit("""
        int main() {
            int values[2] = {};
            return values[0] == 0 && values[1] == 0 ? 0 : 1;
        }
    """)
    assert "int values[2] = {0};" in generated
    _compile_and_run(generated, tmp_path, c_compiler)


def test_fixed_array_assignment_is_rejected():
    errors = _errors("""
        void run() { int source[2]; int target[2]; target = source; }
    """)
    assert _has(errors, "Fixed array 'int[]' is not assignable")


def test_fixed_array_accepts_gpu_dispatch_output_assignment():
    result = _analyze("""
        @gpu int[] dbl(int[] values) {
            int index = gpu_id();
            return values[index] * 2;
        }
        int main() {
            int[] values = {1, 2};
            int output[1];
            output = dbl(values);
            return 0;
        }
    """)
    assert result.errors == []


@pytest.mark.parametrize(
    ("source", "message"),
    (
        (
            "int[] values() { int result[2]; return result; }",
            "Function 'values' cannot return an array outside @gpu",
        ),
        (
            "class Values { public int[] get() { int result[2]; return result; } }",
            "Method 'Values.get' cannot return an array outside @gpu",
        ),
        (
            "interface Values { int[] get(); }",
            "Method 'Values.get' cannot return an array outside @gpu",
        ),
    ),
)
def test_host_array_return_declarations_are_rejected(source: str, message: str):
    assert _has(_errors(source), message)


def test_gpu_array_return_declaration_remains_valid():
    result = _analyze("""
        @gpu float[] identity(float[] values) { return values; }
    """)
    assert result.errors == []


def test_anonymous_enum_has_structured_unnamed_ir():
    module, c_source = _emit("""
        enum { A, B, C };
        int main() { return B - 1; }
    """)

    assert len(module.enum_defs) == 1
    assert module.enum_defs[0].name is None
    assert [value.name for value in module.enum_defs[0].values] == ["A", "B", "C"]
    assert not any(function.name.endswith("_toString") for function in module.function_defs)
    assert "enum {" in c_source
    assert "typedef enum {" not in c_source


def test_simple_enum_initializer_rejects_rich_enum_tags():
    errors = _errors("""
        enum class Payload { Empty }
        enum Values { Invalid = Payload.Empty };
    """)

    assert _has(errors, "using only earlier members")


def test_rich_enum_tags_remain_integer_constants_outside_enum_initializers():
    result = _analyze("""
        enum class Payload { First, Second }
        int selected = Payload.Second;
        int main() {
            switch (selected) {
                case Payload.Second: return 0;
                default: return 1;
            }
        }
    """)

    assert result.errors == []


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_preserved_valid_boundaries_compile_as_strict_c11(tmp_path: Path, c_compiler: str):
    _, c_source = _emit("""
        typedef unsigned int UnsignedAlias;
        enum Color { RED, GREEN };
        struct Point { int x; };
        int main() {
            double source = 3.5;
            int number = (int)source;
            UnsignedAlias wide = (UnsignedAlias)number;
            void* opaque = (void*)&number;
            int* pointer = (int*)opaque;
            Color color = (Color)number;
            struct Point point = {3};
            int values[2] = {1, 2};
            (void)wide;
            (void)color;
            (void)values;
            return *pointer + point.x - 6;
        }
    """)

    _compile_and_run(c_source, tmp_path, c_compiler)


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_anonymous_enum_compiles_as_strict_c11(tmp_path: Path, c_compiler: str):
    _, c_source = _emit("""
        enum { A, B, C };
        int main() { return B - 1; }
    """)

    _compile_and_run(c_source, tmp_path, c_compiler)
