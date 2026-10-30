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


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize(
    "source",
    [
        "int main() { register int value = 7; value += 2; value++; return value - 10; }",
        "int main() { int sum = 0; for (register int index = 0; index < 4; index++) { sum += index; } return sum - 6; }",
        "int main() { int value = 7; register int* pointer = &value; *pointer += 2; int* copy = &*pointer; return *copy - 9; }",
        "int main() { int values[2] = {3, 7}; register int* pointer = values; int* copy = &pointer[1]; return *copy - 7; }",
        "int main() { register const int value = 7; var copy = value; return copy - 7; }",
        "int answer() { return 7; } int main() { register int (*callback)() = answer; return callback() - 7; }",
        "int main() { register int first = 3, second = 7; return first + second - 10; }",
        "typedef int Number; int main() { register Number value = 7; return value - 7; }",
        "enum Choice { First, Second }; int main() { register Choice choice = Choice.Second; return (int)choice - 1; }",
        "int add(register int value) { return value + 2; } int main() { return add(5) - 7; }",
        "int add(int); int add(register int value) { return value + 2; } int main() { return add(5) - 7; }",
        "class Item { public int add(register int value) { return value + 2; } } int main() { Item item = new Item(); return item.add(5) - 7; }",
        "int main() { var callback = (register int value) => value + 2; return callback(5) - 7; }",
        "int main() { register int value = 0; return (value = 7) ? value - 7 : 1; }",
        "int choose(register int value) { return (value = 7) ? value - 7 : 1; } int main() { return choose(0); }",
        'int main() { register int value = 1; try { value += 2; throw "stop"; } catch (string error) { value += 4; } return value - 7; }',
        "int main() { register int value = 7; { int value = 3; int* pointer = &value; *pointer = 4; } return value - 7; }",
        "int main() { int value = 3; { register int value = 7; value++; } int* pointer = &value; return *pointer - 3; }",
        "typedef int (*Fn)(register int); int add(int value) { return value + 2; } int main() { register Fn callback = add; return callback(5) - 7; }",
        "interface Add { int add(int value); } class Item implements Add { public int add(register int value) { return value + 2; } } int main() { Item item = new Item(); return item.add(5) - 7; }",
    ],
    ids=[
        "update",
        "for",
        "pointer",
        "pointer-index",
        "const",
        "callback",
        "multiple",
        "alias",
        "enum",
        "parameter",
        "prototype",
        "method",
        "lambda",
        "ternary",
        "parameter-ternary",
        "try",
        "shadow-register",
        "shadow-ordinary",
        "callback-parameter",
        "interface-parameter",
    ],
)
def test_register_scalar_storage(tmp_path, request, frontend, source):
    success, text, diagnostics = _compile(tmp_path, request, frontend, source)
    assert success and not diagnostics, diagnostics
    assert "register " in text
    generated = tmp_path / "register.c"
    generated.write_text(text)
    strict_build_and_run(generated, tmp_path / "register", optimization="-O0")


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("contract", ["interface", "override"])
@pytest.mark.parametrize("declaration_storage, definition_storage", [("register ", ""), ("", "register ")])
def test_register_parameter_storage_does_not_change_method_signature(
    tmp_path, request, frontend, contract, declaration_storage, definition_storage
):
    if contract == "interface":
        parent = f"interface Add {{ int add({declaration_storage}int value); }}"
        inheritance = "implements Add"
        modifier = ""
    else:
        parent = f"class Add {{ public int add({declaration_storage}int value) {{ return value; }} }}"
        inheritance = "extends Add"
        modifier = "override "
    source = (
        f"{parent} class Item {inheritance} {{ "
        f"public {modifier}int add({definition_storage}int value) {{ return value + 2; }} "
        "} int main() { Item item = new Item(); return item.add(5) - 7; }"
    )
    success, text, diagnostics = _compile(tmp_path, request, frontend, source)
    assert success and not diagnostics, diagnostics
    generated = tmp_path / "signature.c"
    generated.write_text(text)
    strict_build_and_run(generated, tmp_path / "signature", optimization="-O0")


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize(
    "source, message",
    [
        ("register int value; int main() { return 0; }", "allowed only on block-scope objects and parameters"),
        (
            "register int f() { return 0; } int main() { return f(); }",
            "allowed only on block-scope objects and parameters",
        ),
        ("typedef register int Number; int main() { return 0; }", "allowed only on block-scope objects and parameters"),
        (
            "struct Record { register int value; }; int main() { return 0; }",
            "allowed only on block-scope objects and parameters",
        ),
        ("int main() { return (register int)0; }", "allowed only on block-scope objects and parameters"),
        ("int main() { return (int)sizeof(register int); }", "allowed only on block-scope objects and parameters"),
        ("int main() { register int values[2] = {1, 2}; return 0; }", "requires a scalar plain C value or raw pointer"),
        (
            "struct Record { int value; }; int main() { register Record value = {1}; return 0; }",
            "requires a scalar plain C value or raw pointer",
        ),
        ('int main() { register string value = "text"; return 0; }', "requires a scalar plain C value or raw pointer"),
        (
            "class Item {} int main() { register Item item = new Item(); return 0; }",
            "requires a scalar plain C value or raw pointer",
        ),
        (
            "int main() { register int value = 1; int* pointer = &value; return *pointer; }",
            "Cannot take the address of register object 'value'",
        ),
        (
            "int f(register int value) { return *(&value); } int main() { return f(0); }",
            "Cannot take the address of register object 'value'",
        ),
        (
            "int main() { register int value = 1; var callback = () => value; return callback(); }",
            "Cannot capture register object 'value'",
        ),
        (
            "int main() { register int value = 1; Thread<int> task = spawn(() => value); return task.join(); }",
            "Cannot capture register object 'value'",
        ),
        ("int main() { register register int value = 1; return value; }", "Duplicate storage class 'register'"),
        ("int main() { register static int value = 1; return value; }", "has more than one storage class"),
        ("int main() { register auto int value = 1; return value; }", "has more than one storage class"),
    ],
    ids=[
        "global",
        "return",
        "typedef",
        "field",
        "cast",
        "sizeof",
        "array",
        "record",
        "string",
        "class",
        "address",
        "parameter-address",
        "capture",
        "spawn",
        "duplicate",
        "static",
        "auto",
    ],
)
def test_register_refuses_invalid_storage_and_escapes(tmp_path, request, frontend, source, message):
    success, _, diagnostics = _compile(tmp_path, request, frontend, source)
    assert not success
    assert message in diagnostics
