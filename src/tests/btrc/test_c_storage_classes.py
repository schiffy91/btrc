"""C storage classes retain declaration semantics in both compilers."""

import subprocess

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.tests.btrc.selfhost_snippet_harness import strict_build_and_run


def _compile(tmp_path, request, frontend, source):
    path = tmp_path / "Storage.btrc"
    path.write_text(source)
    if frontend == "python":
        result = Compiler().compile(source, str(path), CompilerOptions(include_stdlib=False, use_cache=False))
        diagnostics = "\n".join(diagnostic.message for diagnostic in result.diagnostics)
        if result.failure is not None:
            diagnostics += str(result.failure.message)
        return result.successful, result.c_source, diagnostics
    compiler = request.getfixturevalue("semantic_btrcc")
    result = subprocess.run([str(compiler), "--no-cache", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode == 0, result.stdout, result.stderr


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize(
    "source",
    [
        "int main() { auto int value = 7; value += 2; return value - 9; }",
        "int main() { int total = 0; for (auto int index = 0; index < 4; index++) { total += index; } return total - 6; }",
        "int main() { auto int values[2] = {3, 7}; return values[1] - 7; }",
        "int main() { auto int value = 7; auto int* pointer = &value; return *pointer - 7; }",
        "int main() { auto const int value = 7; var copy = value; return copy - 7; }",
        "int answer() { return 7; } int main() { auto int (*callback)() = answer; return callback() - 7; }",
        "class Item { public int value = 7; } int main() { auto Item item = new Item(); return item.value - 7; }",
        "int main() { auto int first = 3, second = 7; return first + second - 10; }",
        "typedef int Number; int main() { auto Number value = 7; return value - 7; }",
    ],
    ids=["update", "for-initializer", "array", "pointer", "inferred-copy", "callback", "managed", "multiple", "alias"],
)
def test_auto_local_storage(tmp_path, request, frontend, source):
    success, text, diagnostics = _compile(tmp_path, request, frontend, source)
    assert success and not diagnostics, diagnostics
    generated = tmp_path / "storage.c"
    generated.write_text(text)
    strict_build_and_run(generated, tmp_path / "storage", optimization="-O0")


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_auto_gpu_buffers_emit_the_same_dispatch(tmp_path, request, frontend):
    source = (
        "@gpu int[] doubled(int[] values) { int index = gpu_id(); return values[index] * 2; } "
        "int main() { auto int[] values = {1, 2}; auto int[] result = doubled(values); return result[0]; }"
    )
    success, actual, diagnostics = _compile(tmp_path, request, frontend, source)
    assert success and not diagnostics, diagnostics
    success, expected, diagnostics = _compile(tmp_path, request, frontend, source.replace("auto ", ""))
    assert success and not diagnostics, diagnostics
    assert actual == expected


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize(
    "source, message",
    [
        ("auto int value; int main() { return 0; }", "'auto' is not allowed at file scope"),
        ("int f(auto int value) { return value; } int main() { return f(0); }", "'auto' is not allowed on parameter"),
        ("auto int f() { return 0; } int main() { return f(); }", "'auto' is not allowed on return type"),
        ("typedef auto int Number; int main() { return 0; }", "'auto' is not allowed in a typedef"),
        ("struct Record { auto int value; }; int main() { return 0; }", "'auto' is not allowed on struct field"),
        ("class Item { public auto int value; } int main() { return 0; }", "'auto' is not allowed on field"),
        ("int main() { return (auto int)0; }", "'auto' is a storage class; it cannot appear in a type name"),
        ("int main() { return (int)sizeof(auto int); }", "'auto' is a storage class; it cannot appear in a type name"),
        (
            "class Item {} int main() { var item = new auto Item(); return 0; }",
            "'auto' is a storage class; it cannot appear in a type name",
        ),
        ("int main() { auto value = 1; return value; }", "'auto' is C11's storage class, not type inference"),
        ("int main() { auto auto int value = 1; return value; }", "Duplicate storage class 'auto'"),
        ("int main() { static auto int value = 1; return value; }", "has more than one storage class"),
        ("int main() { auto extern int value; return value; }", "has more than one storage class"),
        (
            "int main() { var callback = (auto int value) => value; return callback(0); }",
            "'auto' is not allowed on lambda parameter",
        ),
        (
            "class Item { public auto int value { get; set; } } int main() { return 0; }",
            "'auto' is not allowed on property",
        ),
        (
            "int main() { (auto int, int) pair = (1, 2); return 0; }",
            "'auto' is a storage class; it cannot appear in a type name",
        ),
        (
            "int main() { int (*callback)(auto int); return 0; }",
            "'auto' is not allowed on generic argument 2",
        ),
        ("auto int (*callback)(); int main() { return 0; }", "'auto' is not allowed at file scope"),
    ],
    ids=[
        "global",
        "parameter",
        "return",
        "typedef",
        "record-field",
        "class-field",
        "cast",
        "sizeof",
        "new",
        "inference",
        "duplicate",
        "static",
        "extern",
        "lambda-parameter",
        "property",
        "tuple-element",
        "callback-parameter",
        "global-callback",
    ],
)
def test_auto_refuses_nonlocal_declarations_and_type_names(tmp_path, request, frontend, source, message):
    success, _, diagnostics = _compile(tmp_path, request, frontend, source)
    assert not success
    assert message in diagnostics
