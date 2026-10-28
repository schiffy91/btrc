"""C2 r10 designators retain storage paths and source evaluation order."""

from pathlib import Path

import pytest

from src.tests.btrc.selfhost_snippet_harness import compile_reference_source, compile_source, strict_build_and_run

CASES = [
    pytest.param(
        "struct Point { int x; int y; int z; };",
        "struct Point point = {.y = 2, 3, .x = 1}; assert(point.x == 1 && point.y == 2 && point.z == 3);",
        id="positional-continuation",
    ),
    pytest.param(
        "struct Point { int x; int y; }; struct Frame { struct Point point; int tail; };",
        "struct Frame frame = {.point.y = 2, .tail = 3, .point.x = 1}; "
        "assert(frame.point.x == 1 && frame.point.y == 2 && frame.tail == 3);",
        id="merge-nested-record-paths",
    ),
    pytest.param(
        "struct Frame { int values[4]; int tail; };",
        "struct Frame frame = {.values[2] = 7, .tail = 9, .values[0] = 3}; "
        "assert(frame.values[0] == 3 && frame.values[1] == 0 && frame.values[2] == 7 "
        "&& frame.values[3] == 0 && frame.tail == 9);",
        id="merge-array-member-paths",
    ),
    pytest.param(
        "struct Point { int x; int y; };",
        "struct Point points[3] = {[2].x = 7, [0].y = 9}; "
        "assert(points[2].x == 7 && points[2].y == 0 && points[0].x == 0 "
        "&& points[0].y == 9 && points[1].x == 0 && points[1].y == 0);",
        id="array-of-record-paths",
    ),
    pytest.param(
        "union Value { int integer; double real; };",
        "union Value value = {.real = 3.5}; assert(value.real == 3.5);",
        id="union-nonfirst-member",
    ),
    pytest.param(
        "struct Frame { union { struct { int x; int y; }; double real; }; int tail; };",
        "struct Frame frame = {.y = 2, .tail = 3, .x = 1}; assert(frame.x == 1 && frame.y == 2 && frame.tail == 3);",
        id="anonymous-union-compatible-siblings",
    ),
    pytest.param(
        "struct Point { int x; int y; }; struct Point globalPoint = {.y = 2};",
        "static struct Point localPoint = {.y = 4, .x = 3}; "
        "assert(globalPoint.x == 0 && globalPoint.y == 2 && localPoint.x == 3 && localPoint.y == 4);",
        id="global-and-static-zero-fill",
    ),
    pytest.param(
        "struct Label { char text[4]; int tag; };",
        'struct Label label = {.tag = 3, .text = "abc"}; '
        "assert(label.text[0] == 'a' && label.text[2] == 'c' && label.text[3] == 0 && label.tag == 3);",
        id="char-array-member",
    ),
    pytest.param(
        "",
        "int values[] = {[4] = 7, 8, [1] = 2}; "
        "assert((unsigned long long)sizeof(values) == 6ULL * (unsigned long long)sizeof(int)); "
        "assert(values[0] == 0 && values[1] == 2 && values[4] == 7 && values[5] == 8);",
        id="unsized-sparse-array",
    ),
    pytest.param(
        "int values[] = {[4] = 7, 8, [1] = 2};",
        "assert((unsigned long long)sizeof(values) == 6ULL * (unsigned long long)sizeof(int)); "
        "assert(values[0] == 0 && values[1] == 2 && values[4] == 7 && values[5] == 8);",
        id="global-unsized-sparse-array",
    ),
    pytest.param(
        "int increment(int value) { return value + 1; } struct Callable { int tag; int (*callback)(int); };",
        "struct Callable value = {.callback = increment, .tag = 5}; assert(value.tag == 5 && value.callback(6) == 7);",
        id="callable-slot-type",
    ),
]


@pytest.mark.parametrize(("declarations", "body"), CASES)
@pytest.mark.parametrize("frontend", ["host-c", "reference", "selfhost"])
def test_designated_initializers_compile_and_run(
    request: pytest.FixtureRequest, tmp_path: Path, frontend: str, declarations: str, body: str
) -> None:
    source = "#include <assert.h>\n" + declarations + "\nint main(void) { " + body + " return 0; }\n"
    if frontend == "host-c":
        generated = tmp_path / "oracle.c"
        generated.write_text(source)
    else:
        result, generated = (
            compile_reference_source(tmp_path, source)
            if frontend == "reference"
            else compile_source(request.getfixturevalue("semantic_btrcc"), tmp_path, source)
        )
        assert result.returncode == 0, result.stderr
    strict_build_and_run(generated, tmp_path / "designated-initializer")


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_designated_operands_keep_source_order_across_shared_parents(
    request: pytest.FixtureRequest, tmp_path: Path, frontend: str
) -> None:
    # C leaves operand order unspecified. This is btrc's stronger guarantee.
    source = """#include <assert.h>
struct Pair { int x; int y; };
struct Frame { struct Pair pair; int values[3]; };
int calls = 0;
int nextValue() { calls += 1; return calls; }
int main() {
    struct Frame frame = {.pair.y = nextValue(), .values[2] = nextValue(),
        .pair.x = nextValue(), .values[0] = nextValue()};
    assert(calls == 4 && frame.pair.y == 1 && frame.values[2] == 2
        && frame.pair.x == 3 && frame.values[0] == 4 && frame.values[1] == 0);
    return 0;
}
"""
    result, generated = (
        compile_reference_source(tmp_path, source)
        if frontend == "reference"
        else compile_source(request.getfixturevalue("semantic_btrcc"), tmp_path, source)
    )
    assert result.returncode == 0, result.stderr
    strict_build_and_run(generated, tmp_path / "designated-order")


@pytest.mark.parametrize(
    ("declarations", "initializer", "diagnostic"),
    [
        ("struct Point { int x; int y; };", "struct Point value = {.z = 1};", "Struct 'Point' has no field 'z'"),
        (
            "struct Point { int x; int y; };",
            "struct Point value = {.x = 1, .x = 2};",
            "Field 'x' of struct 'Point' is initialized more than once",
        ),
        (
            "struct Point { int x; int y; }; struct Frame { struct Point point; };",
            "struct Frame value = {.point = {1, 2}, .point.x = 3};",
            "Field 'point' of struct 'Frame' is initialized more than once",
        ),
        (
            "union Value { int integer; float real; };",
            "union Value value = {.integer = 1, .real = 2.0f};",
            "Union 'Value' initializer sets both 'integer' and 'real'",
        ),
        (
            "struct Frame { struct { int x; int y; }; int tail; };",
            "struct Frame value = {.x = 1, 2};",
            "A positional initializer cannot follow a designator into an anonymous member; designate the next member",
        ),
        ("", "int value[4] = {[4] = 1};", "Array designator index 4 is outside 'int[4]'"),
        ("", "int value[4] = {[-1] = 1};", "Array designator index -1 is outside 'int[4]'"),
        (
            "int index = 2;",
            "int value[4] = {[index] = 1};",
            "Array designator index must be an integer constant expression",
        ),
    ],
)
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_invalid_designated_initializers_are_diagnosed(
    request: pytest.FixtureRequest, tmp_path: Path, frontend: str, declarations: str, initializer: str, diagnostic: str
) -> None:
    source = declarations + "\nint main() { " + initializer + " return 0; }\n"
    result, _ = (
        compile_reference_source(tmp_path, source)
        if frontend == "reference"
        else compile_source(request.getfixturevalue("semantic_btrcc"), tmp_path, source)
    )
    assert result.returncode != 0
    assert diagnostic in result.stderr, result.stderr


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize(
    ("declarations", "body"),
    [
        (
            "struct Point { int x; int y; };",
            "struct Point values[] = {[2].y = 7, [0].x = 2}; int count = 0; int sum = 0; for point in values { count++; sum += point.x + point.y; } assert(count == 3 && sum == 9);",
        ),
        (
            "struct Point { int x; int y; }; struct Frame { struct Point point; int values[3]; }; struct Frame frame = {.point.y = 2, .values[2] = 3, .point.x = 1};",
            "assert(frame.point.x == 1 && frame.point.y == 2 && frame.values[0] == 0 && frame.values[2] == 3);",
        ),
        (
            "struct Point { int x; int y; }; class Factory { public T make<T>(T seed) { T value = {.x = 7}; return value; } }",
            "var factory = new Factory(); struct Point seed = {}; struct Point value = factory.make(seed); assert(value.x == 7 && value.y == 0);",
        ),
        (
            "struct Point { int x; int y; };",
            "struct Point values[2] = {[0].x = 1, [0].y = 2, [1].x = 3, [1].y = 4}; assert(values[0].x + values[0].y + values[1].x + values[1].y == 10);",
        ),
    ],
)
def test_designated_extent_and_concrete_targets(request, tmp_path, frontend, declarations, body):
    source = "#include <assert.h>\n" + declarations + "\nint main() { " + body + " return 0; }"
    result, generated = (
        compile_reference_source(tmp_path, source)
        if frontend == "reference"
        else compile_source(request.getfixturevalue("semantic_btrcc"), tmp_path, source)
    )
    assert result.returncode == 0, result.stderr
    strict_build_and_run(generated, tmp_path / "designated-concrete")


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize(
    ("source", "diagnostic"),
    [
        (
            "union Value { struct { int values[2]; }; int other; }; int main() { union Value value = {.values[0] = 1, .other = 2}; return 0; }",
            "Union 'Value' initializer sets both 'values' and 'other'",
        ),
        (
            "int main() { int values[4] = {[3] = 1, 2}; return 0; }",
            "Initializer element for index 4 is outside 'int[4]'",
        ),
        (
            "int main() { int values[4] = {[1 + 1] = 1, [2] = 2}; return 0; }",
            "Index 2 of 'int[4]' is initialized more than once",
        ),
        ("int main() { int values[2 + 2] = {[4] = 1}; return 0; }", "Array designator index 4 is outside 'int[4]'"),
        (
            "int main() { int values[4] = {.x = 1}; return 0; }",
            "Designator '.x' needs a struct or union, but the initialized type is 'int[4]'",
        ),
        (
            "int main() { var value = {.x = 1}; return 0; }",
            "A designated initializer needs a declared struct, union or array type",
        ),
        (
            "int main() { (int, int) value = {._0 = 1}; return 0; }",
            "Designated initializers apply to structs, unions and arrays",
        ),
        (
            "int main() { int values[4] = {[0 ... 2] = 1}; return 0; }",
            "Range designators ('[a ... b]') are a GNU extension, not C11; designate each index",
        ),
        (
            "struct Point { int y; }; class Factory { public T make<T>(T seed) { T value = {.x = 7}; return value; } } int main() { var factory = new Factory(); struct Point seed = {}; struct Point value = factory.make(seed); return value.y; }",
            "Struct 'Point' has no field 'x'",
        ),
    ],
)
def test_designator_target_and_continuation_refusals(request, tmp_path, frontend, source, diagnostic):
    result, _ = (
        compile_reference_source(tmp_path, source)
        if frontend == "reference"
        else compile_source(request.getfixturevalue("semantic_btrcc"), tmp_path, source)
    )
    assert result.returncode != 0
    assert diagnostic in result.stderr, result.stderr


@pytest.mark.parametrize("initializer", ["{[1, 2], [3, 4]}", "{[1, 2][0], [3, 4].len}"])
def test_reference_list_expressions_are_not_designations(initializer):
    from src.compiler.python.lexer.lexer import Lexer
    from src.compiler.python.parser.parser import Parser
    from src.compiler.python.syntax.ast.generated import BraceInitializer

    expression = Parser(Lexer(initializer).tokenize())._parse_expr()
    assert isinstance(expression, BraceInitializer)
    assert expression.entries == []
    assert len(expression.elements) == 2


@pytest.mark.parametrize(("initializer", "allowed"), [("{.x = 7}", True), ("{7}", False)])
def test_reference_native_public_designator_with_private_fields(initializer, allowed):
    from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
    from src.compiler.python.frontend.native_imports import NativeHeaderSource
    from src.compiler.python.lexer.lexer import Lexer
    from src.compiler.python.parser.parser import Parser

    program = Parser(
        Lexer(
            "struct Native { int x; }; int main() { struct Native value = " + initializer + "; return value.x; }"
        ).tokenize()
    ).parse()
    program.declarations[0].source_file = NativeHeaderSource("fixture", "Native.h", private_fields=True)
    result = SemanticAnalyzer().analyze(program)
    if allowed:
        assert result.errors == []
    else:
        assert any(
            "Native records with private fields cannot use positional initialization" in error
            for error in result.errors
        )
