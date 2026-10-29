"""Semantic scope refusals on jump ASTs before parser syntax is enabled."""

import dataclasses

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer, LiteralDecoder
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import CallExpr, ExprStmt, GotoStmt, Identifier, LabelStmt


def _program(source):
    program = Parser(Lexer(source).tokenize()).parse()

    def replace(node):
        if isinstance(node, ExprStmt) and isinstance(node.expr, CallExpr) and isinstance(node.expr.callee, Identifier):
            call = node.expr
            if call.callee.name in {"jump", "label"}:
                name = call.args[0]
                if call.callee.name == "jump":
                    return GotoStmt(
                        name=LiteralDecoder.decode_string(name.value).decode(),
                        line=node.line,
                        col=node.col,
                        name_line=name.line,
                        name_col=name.col,
                    )
                return LabelStmt(name=LiteralDecoder.decode_string(name.value).decode(), line=node.line, col=node.col)
        if dataclasses.is_dataclass(node):
            for field in dataclasses.fields(node):
                value = getattr(node, field.name)
                if isinstance(value, list):
                    setattr(node, field.name, [replace(child) for child in value])
                elif dataclasses.is_dataclass(value):
                    setattr(node, field.name, replace(value))
        return node

    return replace(program)


def _analyze(source):
    return SemanticAnalyzer().analyze(_program(source))


def _messages(source):
    return [diagnostic.message for diagnostic in _analyze(source).diags if diagnostic.severity == "error"]


def test_forward_backward_and_nested_outward_targets_share_one_body_marker():
    result = _analyze('void f() { jump("done"); label("again"); { jump("done"); } label("done"); jump("again"); }')
    assert result.errors == []
    assert result.jump_body_ids == {id(result.program.declarations[0].body)}


def test_undefined_label():
    assert _messages('void f() { jump("missing"); }') == ["Label 'missing' is not defined in this function"]


def test_duplicate_labels_share_function_scope_but_not_variable_namespace():
    result = _analyze('void f() { int done = 1; label("done"); jump("done"); }')
    assert result.errors == []
    messages = _messages('void f() { label("done"); { label("done"); } }')
    assert len(messages) == 1 and messages[0].startswith("Duplicate label 'done' in this function (first at 1:")


def test_lambda_cannot_leave_for_a_later_outer_label():
    messages = _messages('void f() { var callback = () => { jump("out"); }; label("out"); }')
    assert len(messages) == 1 and messages[0].startswith("goto 'out' cannot leave a lambda body (label at 1:")


def test_lambda_cannot_be_entered():
    messages = _messages('void f() { jump("inside"); var callback = () => { label("inside"); }; }')
    assert len(messages) == 1 and messages[0].startswith("goto 'inside' cannot enter a lambda body (label at 1:")


def test_sibling_lambda_labels_are_undefined():
    source = 'void f() { var first = () => { label("inside"); }; var second = () => { jump("inside"); }; }'
    assert _messages(source) == ["Label 'inside' is not defined in this function"]


@pytest.mark.parametrize("region", ["try", "catch", "finally"])
def test_cannot_leave_exception_region(region):
    bodies = {"try": "", "catch": "", "finally": ""}
    bodies[region] = 'jump("out");'
    source = f'void f() {{ try {{ {bodies["try"]} }} catch (string error) {{ {bodies["catch"]} }} finally {{ {bodies["finally"]} }} label("out"); }}'
    assert _messages(source) == [
        f"goto 'out' cannot leave a {region} block; set a flag and test it after the try statement"
    ]


@pytest.mark.parametrize("region", ["try", "catch", "finally"])
def test_cannot_enter_exception_region(region):
    bodies = {"try": "", "catch": "", "finally": ""}
    bodies[region] = 'label("inside");'
    source = f'void f() {{ jump("inside"); try {{ {bodies["try"]} }} catch (string error) {{ {bodies["catch"]} }} finally {{ {bodies["finally"]} }} }}'
    assert _messages(source) == [f"goto 'inside' cannot enter a {region} block"]


def test_catch_is_not_a_callable_root():
    result = _analyze('void f() { try { } catch (string error) { jump("inside"); label("inside"); } }')
    assert result.errors == []
    assert result.jump_body_ids == {id(result.program.declarations[0].body)}


@pytest.mark.parametrize(
    "nested",
    [
        '{ label("inside"); }',
        'if (true) { label("inside"); }',
        'while (false) { label("inside"); }',
        'switch (1) { case 1: label("inside"); break; }',
    ],
)
def test_cannot_enter_nested_statement_list(nested):
    assert _messages('void f() { jump("inside"); ' + nested + " }") == [
        "goto 'inside' cannot jump into a nested block; jump only to a label in the same block or an enclosing one"
    ]


def test_exception_region_refusal_precedes_general_nested_list_refusal():
    assert _messages('void f() { jump("inside"); { try { label("inside"); } finally {} } }') == [
        "goto 'inside' cannot enter a try block"
    ]


def test_cannot_leave_parallel_body():
    assert _messages('void f() { parallel for index in range(3) { jump("out"); } label("out"); }') == [
        "goto 'out' cannot leave a parallel for body"
    ]


@pytest.mark.parametrize("name", ["auto", "__reserved", "_Reserved", "__btrc_hidden"])
def test_label_uses_generated_c_name_validation(name):
    messages = _messages(f'void f() {{ label("{name}"); }}')
    assert len(messages) == 1 and messages[0].startswith(f"Label name '{name}'")
    assert "reserved" in messages[0]


def test_hosted_macro_can_be_renamed_but_source_macro_cannot():
    assert _messages('void f() { label("EOF"); jump("EOF"); }') == []
    assert _messages('#define done 1\nvoid f() { label("done"); }') == [
        "Label name 'done' collides with source macro 'done'"
    ]


def test_analyzer_reuse_clears_jump_body_facts_and_indexes():
    analyzer = SemanticAnalyzer()
    first = analyzer.analyze(_program('void f() { label("done"); }'))
    assert first.jump_body_ids
    second = analyzer.analyze(_program("void g() {}"))
    assert second.jump_body_ids == set()
    assert second.errors == []


def test_methods_constructor_properties_and_lambda_have_distinct_body_markers():
    source = """
        class Box {
            public Box() { label("done"); }
            public void method() {
                label("done");
                var callback = () => { label("done"); jump("done"); };
            }
            public int value {
                get { label("done"); return 1; }
                set { label("done"); }
            }
        }
    """
    result = _analyze(source)
    assert result.errors == []
    constructor, method, property_ = result.program.declarations[0].members
    callback = method.body.statements[1].initializer
    bodies = [constructor.body, method.body, property_.getter_body, property_.setter_body, callback.body.body]
    assert result.jump_body_ids == {id(body) for body in bodies}


def test_region_exit_diagnostic_names_the_innermost_forbidden_boundary():
    assert _messages('void f() { parallel for i in range(3) { try { jump("out"); } finally {} } label("out"); }') == [
        "goto 'out' cannot leave a try block; set a flag and test it after the try statement"
    ]
    assert _messages('void f() { try { parallel for i in range(3) { jump("out"); } } finally {} label("out"); }') == [
        "goto 'out' cannot leave a parallel for body"
    ]
