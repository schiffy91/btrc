"""C2 anonymous members keep C layout and one explicit positional brace slot."""

import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.diagnostic_harness import diagnostic_identity
from src.tests.btrc.production_readiness_harness import compile_diagnostic_pair
from src.tests.btrc.selfhost_snippet_harness import compile_reference_source, compile_source, strict_build_and_run


@pytest.mark.parametrize(
    ("declarations", "body"),
    [
        pytest.param(
            "int increment(int value) { return value + 1; } "
            "struct Callable { union { int (*callback)(int); void* pointer; }; };",
            "Callable value = {{increment}}; assert(value.callback(6) == 7);",
            id="c-function-pointer",
        ),
        pytest.param(
            "struct Pair { int x; int y; }; "
            "typedef struct { union { struct { Pair pair; int z; }; double real; }; } Frame;",
            "Frame value = {{{{2, 3}, 4}}}; assert(value.pair.x + value.pair.y + value.z == 9);",
            id="anonymous-typedef-with-named-record",
        ),
        pytest.param(
            "union Value { struct { int x; int y; }; double real; };",
            "Value value = {{2, 3}}; assert(value.x + value.y == 5);",
            id="anonymous-struct-in-union",
        ),
        pytest.param(
            "struct Value { int kind; union { int integer; float real; }; };",
            "Value value; value.kind = 1; value.integer = 7; "
            "Value* pointer = &value; assert(pointer->integer == 7 && value.kind == 1);",
            id="flattened-access",
        ),
        pytest.param(
            "struct Value { int kind; union { int integer; float real; }; };",
            "Value value = {1, {7}}; assert(value.kind == 1 && value.integer == 7);",
            id="union-slot",
        ),
        pytest.param(
            "struct Frame { struct { int x; int y; }; int z; };",
            "Frame frame = {{2, 3}, 4}; assert(frame.x + frame.y + frame.z == 9);",
            id="struct-slot",
        ),
        pytest.param(
            "struct Frame { union { struct { int x; int y; }; float real; }; int z; };",
            "Frame frame = {{{2, 3}}, 4}; assert(frame.x + frame.y + frame.z == 9);",
            id="nested-anonymous-slots",
        ),
        pytest.param(
            "struct Frame { int kind; union { int integer; float real; }; int tail; };",
            "Frame zero = {}; Frame partial = {1, {7}}; "
            "assert(zero.kind == 0 && zero.integer == 0 && zero.tail == 0); "
            "assert(partial.kind == 1 && partial.integer == 7 && partial.tail == 0);",
            id="zero-initialization",
        ),
        pytest.param(
            "struct Values { struct { int values[2]; }; };",
            "Values value = {{{3, 4}}}; assert(value.values[0] + value.values[1] == 7);",
            id="array-member",
        ),
        pytest.param(
            "struct Values { struct { int values[2]; }; int tail; }; int calls = 0; "
            "int nextValue() { calls += 1; return calls; } "
            "int sum(Values value) { return value.values[0] + value.values[1] + value.tail; }",
            "Values value = {{{nextValue(), nextValue()}}, nextValue()}; "
            "assert(value.values[0] == 1 && value.values[1] == 2 && value.tail == 3 && calls == 3); "
            "assert(sum({{{nextValue(), nextValue()}}, nextValue()}) == 15 && calls == 6);",
            id="array-member-evaluation-order",
        ),
        pytest.param(
            "struct Inner { int values[2]; }; struct Outer { Inner inner; int tail; }; int calls = 0; "
            "int nextValue() { calls += 1; return calls; }",
            "Outer value = {{{nextValue(), nextValue()}}, nextValue()}; "
            "assert(value.inner.values[0] == 1 && value.inner.values[1] == 2 && value.tail == 3 && calls == 3);",
            id="named-record-array-evaluation-order",
        ),
        pytest.param(
            "struct Value { int kind; union { int integer; float real; }; }; Value global = {1, {7}};",
            "static Value local = {2, {9}}; assert(global.integer == 7 && local.integer == 9);",
            id="static-initialization",
        ),
        pytest.param(
            "struct Frame { struct { int x; int y; }; int z; }; int calls = 0; "
            "int nextValue() { calls += 1; return calls; }",
            "Frame frame = {{nextValue(), nextValue()}, nextValue()}; "
            "assert(frame.x == 1 && frame.y == 2 && frame.z == 3 && calls == 3);",
            id="initializer-evaluation-order",
        ),
    ],
)
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_anonymous_members_compile_and_run(
    request: pytest.FixtureRequest, tmp_path: Path, frontend: str, declarations: str, body: str
) -> None:
    source = "#include <assert.h>\n" + declarations + "\nint main() { " + body + " return 0; }\n"
    result, generated = (
        compile_reference_source(tmp_path, source)
        if frontend == "reference"
        else compile_source(request.getfixturevalue("semantic_btrcc"), tmp_path, source)
    )
    assert result.returncode == 0, result.stderr
    strict_build_and_run(generated, tmp_path / "anonymous-members")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "struct Value { int integer; union { int integer; float real; }; };",
            "Duplicate field 'integer' in struct 'Value'",
        ),
        (
            "struct Value { union { int integer; float real; }; int integer; };",
            "Duplicate field 'integer' in struct 'Value'",
        ),
        (
            "struct Value { union { string text; int integer; }; };",
            "Member 'text' of an anonymous union in struct 'Value' cannot hold managed type 'string'; anonymous members must be plain C values",
        ),
        (
            "struct Value { struct { string text; }; };",
            "Member 'text' of an anonymous struct in struct 'Value' cannot hold managed type 'string'; anonymous members must be plain C values",
        ),
        (
            "struct Pair { string name; }; struct Value { struct { Pair pair; }; };",
            "Member 'pair' of an anonymous struct in struct 'Value' cannot hold 'Pair', which contains managed field 'name'; anonymous members must be plain C values",
        ),
        (
            "struct Value { struct { CFunction<string> callback; }; };",
            "Member 'callback' of an anonymous struct in struct 'Value' cannot hold managed type 'CFunction<string>'; anonymous members must be plain C values",
        ),
        (
            "struct S { union { int value; } u; };",
            "Member 'u' of struct 'S' has an untagged union type; declare 'union Name' at file scope or make the member anonymous",
        ),
        (
            "struct S { union U { int value; }; };",
            "A union defined inside struct 'S' must be declared at file scope",
        ),
        (
            "class Value { union { int integer; float real; }; }",
            "Anonymous struct and union members are only allowed in struct and union declarations",
        ),
        (
            "struct Value { int kind; union { int integer; float real; }; }; Value value = {1, 7};",
            "The anonymous union member of struct 'Value' requires its own braces in a positional initializer",
        ),
        (
            "struct S { int; };",
            "Struct 'S' declares an unnamed member that is neither a bit-field nor an anonymous struct or union",
        ),
    ],
)
def test_anonymous_member_refusals_match(semantic_btrcc: Path, tmp_path: Path, source: str, message: str) -> None:
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source + "\nint main() { return 0; }\n")
    assert selfhost.returncode != 0 and reference.returncode != 0
    reference_diagnostic = diagnostic_identity(reference.stderr)
    assert reference_diagnostic[0] == message
    assert diagnostic_identity(selfhost.stderr) == reference_diagnostic


@pytest.mark.parametrize("prefix, suffix", [("struct S", ";"), ("typedef struct", " S;")])
@pytest.mark.parametrize(
    "body",
    [
        "int;",
        "union { int value; } u;",
        "union U { int value; };",
        "union { int; };",
        "union { int values[]; };",
    ],
)
def test_anonymous_parser_diagnostics_match(
    selfhost_driver, tmp_path: Path, prefix: str, suffix: str, body: str
) -> None:
    from src.compiler.python.lexer.lexer import Lexer
    from src.compiler.python.parser.parser import ParseError, Parser

    repo = Path(__file__).resolve().parents[3]
    source = prefix + " { " + body + " }" + suffix
    with pytest.raises(ParseError) as error:
        Parser(Lexer(source).tokenize()).parse()
    path = tmp_path / "InvalidRecord.btrc"
    path.write_text(source)
    parser = selfhost_driver(repo / "src/compiler/btrc/tools/ParseMain.btrc", compile_flags=("-pedantic-errors",))
    result = subprocess.run([str(parser), str(path)], cwd=repo, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert result.stderr.strip() == "error: " + str(error.value)


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("argument", [False, True])
def test_anonymous_c_function_slot_preserves_capture_refusal(request, tmp_path, frontend, argument):
    body = (
        "return invoke({{(int n) => n + offset}});"
        if argument
        else "Callable value = {{(int n) => n + offset}}; return value.callback(1);"
    )
    source = (
        "struct Callable { union { CFunction<int, int> callback; void* pointer; }; }; "
        "int invoke(Callable value) { return value.callback(1); } "
        "int main() { int offset = 7; " + body + " }"
    )
    result, _ = (
        compile_reference_source(tmp_path, source)
        if frontend == "reference"
        else compile_source(request.getfixturevalue("semantic_btrcc"), tmp_path, source)
    )
    assert result.returncode != 0, "anonymous CFunction storage discarded the lambda's capture requirement"
    diagnostic = result.stdout + result.stderr
    assert "bare __fn_ptr" in diagnostic
    assert "environment" in diagnostic or "capturing" in diagnostic


def test_anonymous_record_argument_requires_member_braces(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = (
        "struct Value { int kind; union { int integer; float real; }; }; "
        "int read(Value value) { return value.integer; } "
        "int main() { return read({1, 7}); }"
    )
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source)
    assert selfhost.returncode != 0 and reference.returncode != 0
    expected = "The anonymous union member of struct 'Value' requires its own braces in a positional initializer"
    assert diagnostic_identity(reference.stderr)[0] == expected
    assert diagnostic_identity(selfhost.stderr) == diagnostic_identity(reference.stderr)
