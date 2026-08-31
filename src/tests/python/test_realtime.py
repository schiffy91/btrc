"""Source and structured-IR contracts for ``@realtime``."""

from __future__ import annotations

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFor,
    IRFunctionDef,
    IRLiteral,
    IRModule,
    IRWhile,
)
from src.compiler.python.ir.verifier import IRVerifier
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import ParseError, Parser


def analyze(source: str):
    program = Parser(Lexer(source, "realtime-test.btrc").tokenize()).parse()
    return program, SemanticAnalyzer().analyze(program)


def realtime_errors(source: str) -> list[str]:
    return [error for error in analyze(source)[1].errors if "@realtime" in error]


def test_parser_retains_realtime_on_functions_and_methods() -> None:
    program, result = analyze(
        """
        @realtime int render(int value) { return value; }
        class Engine { public @realtime int tick(int value) { return value; } }
        """
    )
    assert result.errors == []
    assert program.declarations[0].is_realtime
    assert program.declarations[1].members[0].is_realtime


@pytest.mark.parametrize(
    "source",
    (
        "@realtime int value = 1;",
        "@gpu @realtime void render() {}",
        "class Engine { public @realtime int value; }",
    ),
)
def test_parser_rejects_invalid_realtime_placement(source: str) -> None:
    with pytest.raises(ParseError):
        Parser(Lexer(source).tokenize()).parse()


def test_realtime_is_part_of_a_function_declaration_contract() -> None:
    _, matching = analyze("@realtime int tick(int value); @realtime int tick(int value) { return value; }")
    _, mismatched = analyze("@realtime int tick(int value); int tick(int value) { return value; }")

    assert matching.errors == []
    assert any("Conflicting declarations" in error for error in mismatched.errors)


def test_safe_pointer_c_for_is_accepted() -> None:
    source = """
        @realtime void gain(float* samples, int count, float amount) {
            for (int index = 0; index < count; index++) {
                samples[index] = samples[index] * amount;
            }
        }
    """
    assert realtime_errors(source) == []


def test_reachable_recursive_scc_fails_with_the_closing_call_path() -> None:
    errors = realtime_errors(
        """
        int evenStep(int value);
        int oddStep(int value) { return evenStep(value - 1); }
        int evenStep(int value) { return oddStep(value - 1); }
        @realtime int audio(int value) { return evenStep(value); }
        """
    )

    assert len(errors) == 1
    assert "forbidden blocking operation 'recursive call cycle'" in errors[0]
    assert "via audio -> evenStep -> oddStep -> evenStep" in errors[0]


@pytest.mark.parametrize(
    ("loop", "operation"),
    (
        ("while (!ready) {}", "unproven while loop"),
        ("do {} while (!ready);", "unproven do-while loop"),
    ),
)
def test_unproven_wait_loops_fail_closed(loop: str, operation: str) -> None:
    errors = realtime_errors(f"@realtime void audio(bool ready) {{ {loop} }}")

    assert len(errors) == 1
    assert f"forbidden blocking operation '{operation}' via audio" in errors[0]


@pytest.mark.parametrize(
    "loop",
    (
        "for (;;) {}",
        "for (int index = 0; ready; index++) {}",
        "for (int index = 0; index <= count; index++) {}",
        "for (int index = 0; index < count; index--) {}",
        "for (int index = 0; index < count; index = 0) {}",
        "for (int index = 0; index < count; index++) { index = 0; }",
        "for (int index = 0; index < count; index++) { count--; }",
    ),
)
def test_only_canonical_bounded_c_for_is_admitted(loop: str) -> None:
    errors = realtime_errors(f"@realtime void audio(int count, bool ready) {{ {loop} }}")

    assert len(errors) == 1
    assert "forbidden blocking operation 'unproven C-style loop' via audio" in errors[0]


def test_c_for_rejects_address_escape_of_its_bound() -> None:
    errors = realtime_errors(
        """
        void touch(int* value) { *value = *value; }
        @realtime void audio(int count) {
            for (int index = 0; index < count; index++) { touch(&count); }
        }
        """
    )

    assert len(errors) == 1
    assert "forbidden blocking operation 'unproven C-style loop' via audio" in errors[0]


def test_pod_global_and_self_field_reads_are_accepted() -> None:
    assert (
        realtime_errors(
            """
            int globalLevel = 2;
            class Engine {
                public int level;
                public @realtime int render() { return globalLevel + self.level; }
            }
            """
        )
        == []
    )


@pytest.mark.parametrize(
    ("source", "category", "operation"),
    (
        (
            'string label = "ready"; @realtime void audio() { (void*)label; }',
            "strings",
            "string identifier 'label'",
        ),
        (
            "Vector<int> values; @realtime void audio() { (void*)values; }",
            "collections",
            "collection identifier 'values'",
        ),
        (
            "class Box {} Box box; @realtime void audio() { (void*)box; }",
            "ARC",
            "managed identifier 'box'",
        ),
        (
            "class Engine { public string label; public @realtime void audio() { (void*)self.label; } }",
            "strings",
            "string field 'label'",
        ),
        (
            "@realtime void audio(void* raw) { (string)raw; }",
            "strings",
            "string cast result",
        ),
    ),
)
def test_existing_managed_values_cannot_enter_realtime_expressions(
    source: str,
    category: str,
    operation: str,
) -> None:
    errors = realtime_errors(source)

    assert len(errors) == 1
    assert f"forbidden {category} operation '{operation}'" in errors[0]


def test_pod_rich_enum_payload_is_accepted() -> None:
    assert (
        realtime_errors(
            """
            enum class Sample { Value(int sample), Empty }
            @realtime int audio(Sample sample) { return sample.tag; }
            """
        )
        == []
    )


@pytest.mark.parametrize(
    "declarations",
    (
        "enum class Sample { Text(string value), Empty }",
        "class Box {} enum class Sample { Object(Box value), Empty }",
        "enum class Sample { Values(Vector<int> value), Empty }",
    ),
)
def test_managed_rich_enum_payload_closure_is_rejected(declarations: str) -> None:
    errors = realtime_errors(f"{declarations} @realtime void audio(Sample sample) {{}}")

    assert len(errors) == 1
    assert "forbidden ARC operation 'managed parameter 'sample''" in errors[0]


def test_explicitly_safe_hosted_manifest_call_is_accepted() -> None:
    assert realtime_errors("@realtime int magnitude(int value) { return abs(value); }") == []


def test_transitive_diagnostic_names_exact_operation_and_call_path() -> None:
    errors = realtime_errors(
        """
        void writeLog() { print(1); }
        void service() { writeLog(); }
        @realtime void audio() { service(); }
        """
    )
    assert len(errors) == 1
    assert "forbidden logging operation 'external call 'print()''" in errors[0]
    assert "via audio -> service -> writeLog" in errors[0]
    assert errors[0].endswith("at 2:27")


@pytest.mark.parametrize(
    ("source", "category", "operation"),
    (
        ("class Box {} @realtime void audio() { Box(); }", "allocation", "constructor call 'Box'"),
        ("@realtime void audio(string value) {}", "ARC", "managed parameter 'value'"),
        ("@realtime void audio() { throw 1; }", "exceptions", "ThrowStmt"),
        ('@realtime void audio() { "text"; }', "strings", "string value"),
        ("@realtime void audio() { [1, 2]; }", "collections", "ListLiteral"),
        ("@realtime void audio() { sleep(1); }", "blocking", "external call 'sleep()'"),
        ("@realtime void audio() { write(1, null, 0); }", "I/O", "external call 'write()'"),
        ("extern void foreign(); @realtime void audio() { foreign(); }", "unknown", "bodyless"),
    ),
)
def test_forbidden_effect_families_fail_closed(source: str, category: str, operation: str) -> None:
    errors = realtime_errors(source)
    assert len(errors) == 1
    assert f"forbidden {category} operation" in errors[0]
    assert operation in errors[0]


def test_omitted_default_expression_belongs_to_callers_realtime_path() -> None:
    errors = realtime_errors(
        """
        int helper(int value = sleep(1)) { return value; }
        @realtime int audio() { return helper(); }
        """
    )
    assert len(errors) == 1
    assert "external call 'sleep()'" in errors[0]
    assert "via audio" in errors[0]


def test_realtime_method_reaches_an_unsafe_method_body() -> None:
    errors = realtime_errors(
        """
        class Engine {
            private void trace() { print(1); }
            public @realtime void render() { self.trace(); }
        }
        """
    )
    assert len(errors) == 1
    assert "via Engine.render -> Engine.trace" in errors[0]


@pytest.mark.parametrize(
    ("expression", "path"),
    (
        ("self + 1", "via Engine.render -> Engine.__add__"),
        ("self[0]", "via Engine.render -> Engine.get"),
    ),
)
def test_implicit_protocol_calls_are_in_the_realtime_graph(expression: str, path: str) -> None:
    errors = realtime_errors(
        f"""
        class Engine {{
            public int __add__(int value) {{ print(value); return value; }}
            public int get(int index) {{ print(index); return index; }}
            public void set(int index, int value) {{}}
            public @realtime int render() {{ return {expression}; }}
        }}
        """
    )
    assert len(errors) == 1
    assert path in errors[0]


def test_ir_backstop_accepts_internal_closure_and_rejects_external_calls() -> None:
    helper = IRFunctionDef(
        name="helper",
        return_type=CType("void"),
        body=IRBlock(stmts=[]),
    )
    root = IRFunctionDef(
        name="audio",
        return_type=CType("void"),
        body=IRBlock(stmts=[IRExprStmt(expr=IRCall(callee="helper"))]),
        is_realtime=True,
    )
    IRVerifier(IRModule(function_defs=[root, helper])).validate_schema()

    root.body.stmts.append(IRExprStmt(expr=IRCall(callee="abs", args=[IRLiteral(text="-1")])))
    IRVerifier(IRModule(function_defs=[root, helper], realtime_safe_externals={"abs"})).validate_schema()

    root.body.stmts.append(IRExprStmt(expr=IRCall(callee="malloc", args=[IRLiteral(text="4")])))
    with pytest.raises(ValueError, match=r"external/runtime call 'malloc'.*audio"):
        IRVerifier(IRModule(function_defs=[root, helper], realtime_safe_externals={"abs"})).validate_schema()


def test_ir_backstop_rejects_recursion_and_uncertified_loops() -> None:
    recursive = IRFunctionDef(
        name="recursive",
        return_type=CType("void"),
        body=IRBlock(stmts=[IRExprStmt(expr=IRCall(callee="recursive"))]),
        is_realtime=True,
    )
    with pytest.raises(ValueError, match=r"recursive call cycle.*recursive -> recursive"):
        IRVerifier(IRModule(function_defs=[recursive])).validate_schema()

    unbounded = IRFunctionDef(
        name="unbounded",
        return_type=CType("void"),
        body=IRBlock(stmts=[IRWhile(condition=IRLiteral(text="1"), body=IRBlock())]),
        is_realtime=True,
    )
    with pytest.raises(ValueError, match=r"unbounded loop.*unbounded"):
        IRVerifier(IRModule(function_defs=[unbounded])).validate_schema()

    uncertified = IRFunctionDef(
        name="uncertified",
        return_type=CType("void"),
        body=IRBlock(
            stmts=[
                IRFor(
                    condition=IRLiteral(text="1"),
                    update=IRLiteral(text="1"),
                    body=IRBlock(),
                )
            ]
        ),
        is_realtime=True,
    )
    with pytest.raises(ValueError, match=r"uncertified for loop.*uncertified"):
        IRVerifier(IRModule(function_defs=[uncertified])).validate_schema()

    uncertified.body.stmts[0].realtime_bounded = True
    IRVerifier(IRModule(function_defs=[uncertified])).validate_schema()
