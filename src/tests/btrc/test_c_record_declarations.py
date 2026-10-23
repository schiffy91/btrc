"""C2 record declarations retain their identity and layout in both frontends."""

import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.diagnostic_harness import diagnostic_identity
from src.tests.btrc.production_readiness_harness import compile_diagnostic_pair
from src.tests.btrc.selfhost_snippet_harness import compile_reference_source, compile_source, strict_build_and_run

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("declarations", "body"),
    [
        pytest.param(
            "typedef struct { int x; int y; } Point;",
            "Point p = {2, 3}; assert(p.x + p.y == 5);",
            id="anonymous-typedef",
        ),
        pytest.param(
            "typedef struct Point { int x; int y; } Point;",
            "Point p = {2, 3}; struct Point q = p; assert(q.y == 3);",
            id="tagged-typedef",
        ),
        pytest.param(
            "typedef struct Point { int x; } Pair, *PairPtr;",
            "Pair p = {7}; PairPtr q = &p; assert(q->x == 7);",
            id="distinct-aliases",
        ),
        pytest.param(
            "typedef struct Point Point; struct Point { int x; };",
            "Point p = {7}; assert(p.x == 7);",
            id="identity-before-definition",
        ),
        pytest.param(
            "struct Point { int x; }; typedef struct Point Point;",
            "Point p = {7}; assert(p.x == 7);",
            id="identity-after-definition",
        ),
        pytest.param(
            "typedef union Value Value; union Value { int x; float y; };",
            "Value p = {7}; assert(p.x == 7);",
            id="union-identity",
        ),
        pytest.param(
            "struct Point { int x; } first = {4}, *pointer = &first;",
            "assert(first.x == 4 && pointer->x == 4);",
            id="record-objects",
        ),
        pytest.param(
            "typedef enum { RED, GREEN, BLUE } Color;", "Color c = GREEN; assert((int)c == 1);", id="enum-typedef"
        ),
        pytest.param(
            "typedef enum Color Color; enum Color { RED, GREEN };",
            "Color c = GREEN; assert((int)c == 1);",
            id="enum-identity",
        ),
        pytest.param(
            "typedef enum Color { RED, GREEN } Shade, *ShadePtr;",
            "Shade c = GREEN; ShadePtr p = &c; assert((int)*p == 1);",
            id="enum-distinct-aliases",
        ),
        pytest.param(
            "typedef enum { RED, GREEN } Color;",
            "enum Color c = GREEN; assert((int)c == 1);",
            id="enum-tag-local",
        ),
        pytest.param(
            "typedef enum { READY } T; "
            "class Box<T> { public enum T state; public T value; "
            "public Box(T value) { self.state = READY; self.value = value; } }",
            "Box<int> box = Box(7); assert((int)box.state == 0 && box.value == 7);",
            id="enum-tag-generic-shadow",
        ),
        pytest.param(
            "typedef enum { RED, GREEN } Color; enum Color global = GREEN; "
            "enum Color echo(enum Color color) { return color; }",
            "assert(echo(global) == GREEN);",
            id="enum-tag-global-and-return",
        ),
        pytest.param(
            "enum Color { RED, GREEN }; struct Palette { int count; enum Color colors[]; };",
            "assert(sizeof(struct Palette) >= sizeof(int));",
            id="enum-tag-flexible-member",
        ),
        pytest.param("typedef struct Foreign Foreign;", "Foreign* p = null; assert(p == null);", id="foreign-typedef"),
    ],
)
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_record_declarations_compile_and_run(
    semantic_btrcc: Path, tmp_path: Path, frontend: str, declarations: str, body: str
) -> None:
    source = "#include <assert.h>\n" + declarations + "\nint main() { " + body + " return 0; }\n"
    result, generated = (
        compile_reference_source(tmp_path, source)
        if frontend == "reference"
        else compile_source(semantic_btrcc, tmp_path, source)
    )
    assert result.returncode == 0, result.stderr
    strict_build_and_run(generated, tmp_path / "record-declarations")


@pytest.mark.parametrize(
    ("declarations", "message"),
    [
        (
            "struct Point { int x; }; typedef const struct Point Point;",
            "Top-level name 'Point' is declared as both struct and typedef",
        ),
        (
            "struct Point { int x; }; typedef struct Point* Point;",
            "Top-level name 'Point' is declared as both struct and typedef",
        ),
        (
            "struct Point { int x; }; typedef union Point Point;",
            "Top-level name 'Point' is declared as both struct and typedef",
        ),
        (
            "typedef struct { int x; } *Pointer;",
            "An untagged struct in a typedef needs a plain declarator to name it; add a tag (typedef struct Name { ... } *Alias;)",
        ),
        (
            "typedef enum { READY } *Pointer;",
            "An untagged enum in a typedef needs a plain declarator to name it; add a tag (typedef enum Name { ... } *Alias;)",
        ),
        (
            "struct { int x; } value;",
            "An untagged struct definition needs a tag to declare 'value'; write 'struct Name { ... } value;'",
        ),
    ],
)
def test_record_declaration_refusals_match(
    semantic_btrcc: Path, tmp_path: Path, declarations: str, message: str
) -> None:
    selfhost, reference = compile_diagnostic_pair(
        semantic_btrcc, tmp_path, declarations + "\nint main() { return 0; }\n"
    )
    assert selfhost.returncode != 0 and reference.returncode != 0
    reference_diagnostic = diagnostic_identity(reference.stderr)
    assert reference_diagnostic[0] == message
    assert diagnostic_identity(selfhost.stderr) == reference_diagnostic


def test_record_declaration_ast_positions_match(selfhost_driver, tmp_path: Path) -> None:
    source = tmp_path / "Records.btrc"
    source.write_text(
        "typedef struct {\n    int x, y;\n} Point, *PointPtr;\n"
        "typedef union Value {\n    int integer;\n    float real;\n} Value, *ValuePtr;\n"
        "typedef enum { RED, GREEN = 4 } Color, *ColorPtr;\n"
        "typedef enum Shade { DARK, LIGHT } Tint;\n"
        "typedef struct Later Later;\n"
        "struct Later { int value; } first = {7}, *next = &first;\n"
    )
    parser = selfhost_driver(REPO / "src/compiler/btrc/tools/ParseMain.btrc", compile_flags=("-pedantic-errors",))
    parsed = subprocess.run([str(parser), str(source)], capture_output=True, text=True, timeout=30)
    reference = subprocess.run(
        [sys.executable, "-m", "tools.compiler_codegen.main", "dump-ast", str(source)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert parsed.returncode == 0, parsed.stderr
    assert reference.returncode == 0, reference.stderr
    assert parsed.stdout == reference.stdout
