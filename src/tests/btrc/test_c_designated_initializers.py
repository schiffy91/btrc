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
        "assert(sizeof(values) == 6 * sizeof(int)); "
        "assert(values[0] == 0 && values[1] == 2 && values[4] == 7 && values[5] == 8);",
        id="unsized-sparse-array",
    ),
    pytest.param(
        "int values[] = {[4] = 7, 8, [1] = 2};",
        "assert(sizeof(values) == 6 * sizeof(int)); "
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
