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


@pytest.mark.parametrize(
    "declaration, suffix, prefix",
    [
        ("int value = 3;", "", ""),
        ("bool value = true;", "", ""),
        ("int values[2];", "", ""),
        ("int* pointer = null;", "", ""),
        ("struct Item item;", "", "struct Item { int number; double weight; };"),
        ("struct Link* link = null;", "", "struct Link { struct Link* next; };"),
        ("Number value = 3;", "", "typedef int Number;"),
        ("static int value = 3;", "value++;", ""),
        ("extern int value;", "value++;", ""),
        ('{ string text = "temporary"; }', "", ""),
        ('try {} finally { string text = "temporary"; }', "", ""),
    ],
)
def test_forward_jump_can_skip_unused_plain_or_nested_storage(declaration, suffix, prefix):
    source = (
        prefix + 'void f(bool flag) { if (flag) { jump("done"); } ' + declaration + ' label("done"); ' + suffix + " }"
    )
    assert _messages(source) == []


@pytest.mark.parametrize(
    "declaration, prefix",
    [
        ('string value = "owned";', ""),
        ('char* value = "owned";', ""),
        ('const char* value = "owned";', ""),
        ("Box value = new Box();", "class Box {}"),
        ("void* value = new Box();", "class Box {}"),
        ('var value = "owned";', ""),
        ("var value = () => 1;", ""),
        ("int (*value)() = answer;", "int answer() { return 1; }"),
    ],
)
def test_forward_jump_refuses_managed_or_callable_declarations(declaration, prefix):
    source = prefix + 'void f(bool flag) { if (flag) { jump("done"); } ' + declaration + ' label("done"); }'
    messages = _messages(source)
    assert len(messages) == 1, messages
    assert "skips the declaration of 'value'" in messages[0] and "not a plain C value" in messages[0]


@pytest.mark.parametrize("suffix", ["value++;", "{ int value = 7; value++; }", "var callback = () => value;"])
def test_forward_jump_refuses_reads_after_label_even_with_shadowing_or_capture(suffix):
    source = 'void f(bool flag) { if (flag) { jump("done"); } int value = 3; label("done"); ' + suffix + " }"
    messages = _messages(source)
    assert len(messages) == 1, messages
    assert "skips the declaration of 'value'" in messages[0] and "used after the label" in messages[0]


def test_forward_jump_refuses_reads_reachable_through_backward_goto():
    source = 'void f(bool flag) { if (flag) { jump("done"); } int value = 3; label("again"); value++; label("done"); jump("again"); }'
    messages = _messages(source)
    assert len(messages) == 1, messages
    assert "skips the declaration of 'value'" in messages[0] and "used after the label" in messages[0]


@pytest.mark.parametrize(
    "declaration",
    [
        "int values[count];",
        "try {} finally { int values[count]; }",
        "try {} finally { try {} finally { int values[count]; } }",
    ],
)
def test_forward_jump_refuses_vla_scope_including_spliced_finally(declaration):
    source = 'void f(bool flag, int count) { if (flag) { jump("done"); } ' + declaration + ' label("done"); }'
    messages = _messages(source)
    assert len(messages) == 1, messages
    assert "jumps into the scope of variable-length array 'values'" in messages[0]


def test_initializer_type_keeps_the_binding_at_the_declaration_point():
    source = 'string original() { return "owned"; } void f(bool flag) { if (flag) { jump("done"); } char* value = original(); int original = 3; label("done"); }'
    messages = _messages(source)
    assert len(messages) == 1, messages
    assert "skips the declaration of 'value'" in messages[0] and "not a plain C value" in messages[0]


@pytest.mark.parametrize(
    "base, pointer_depth, nullable, expected",
    [
        ("bool", 0, False, True),
        ("int", 0, False, True),
        ("double", 0, False, True),
        ("size_t", 0, False, True),
        ("FILE", 0, False, True),
        ("enum Foreign", 0, False, True),
        ("struct Foreign", 0, False, True),
        ("union Foreign", 0, False, True),
        ("mystery_t", 0, False, False),
        ("mystery_t", 1, False, True),
        ("void", 0, False, False),
        ("void", 1, False, True),
        ("int", 1, True, False),
        ("string", 0, False, False),
        ("string", 2, False, False),
        ("Box", 1, False, False),
        ("Box", 2, False, False),
        ("Contract", 1, False, False),
        ("Tuple", 0, False, False),
        ("Thread", 0, False, False),
        ("Mutex", 0, False, False),
        ("Atomic", 0, False, False),
        ("Span", 0, False, False),
        ("__fn_ptr", 0, False, False),
        ("__realtime_fn_ptr", 0, False, False),
    ],
)
def test_plain_c_object_type_policy(base, pointer_depth, nullable, expected):
    from src.compiler.python.syntax.ast.generated import TypeExpr

    analyzer = SemanticAnalyzer()
    result = analyzer.analyze(_program("class Box {} interface Contract { void call(); }"))
    assert result.errors == []
    assert (
        analyzer.types.is_plain_c_object(TypeExpr(base=base, pointer_depth=pointer_depth, is_nullable=nullable))
        is expected
    )


def test_plain_c_records_follow_aliases_anonymous_members_and_constant_extents():
    from src.compiler.python.syntax.ast.generated import AnonymousMember, FieldDef, IntLiteral, StructDecl, TypeExpr

    analyzer = SemanticAnalyzer()
    analyzer.index.typedef_table["Number"] = TypeExpr(base="int")
    bound = IntLiteral(value=2)
    values = TypeExpr(base="Number", is_array=True, array_size=bound)
    record = StructDecl(
        name="Record", fields=[AnonymousMember(is_union=True, fields=[FieldDef(name="values", type=values)])]
    )
    analyzer.index.struct_table["Record"] = record
    assert not analyzer.types.is_plain_c_object(TypeExpr(base="struct Record"))
    assert analyzer.types.is_variably_modified(values)
    analyzer.session.constant_array_bound_ids.add(id(bound))
    assert analyzer.types.is_plain_c_object(TypeExpr(base="struct Record"))
    assert not analyzer.types.is_variably_modified(values)
    record.fields.append(FieldDef(name="text", type=TypeExpr(base="string")))
    assert not analyzer.types.is_plain_c_object(TypeExpr(base="Record"))
    record.fields[-1].type = TypeExpr(base="Record")
    assert not analyzer.types.is_plain_c_object(TypeExpr(base="Record"))
    record.fields[-1].type = TypeExpr(base="Record", pointer_depth=1)
    assert analyzer.types.is_plain_c_object(TypeExpr(base="Record"))


def test_plain_c_policy_refuses_unresolved_type_parameters():
    from src.compiler.python.syntax.ast.generated import MethodDecl, TypeExpr

    analyzer = SemanticAnalyzer()
    analyzer.session.current_method = MethodDecl(
        name="generic", return_type=TypeExpr(base="void"), generic_params=["T"]
    )
    assert not analyzer.types.is_plain_c_object(TypeExpr(base="T"))
    assert not analyzer.types.is_plain_c_object(TypeExpr(base="T", pointer_depth=1))
    assert not analyzer.types.declaration_is_plain(
        TypeExpr(base="void", pointer_depth=1), TypeExpr(base="T"), initializer_managed=False
    )


def test_forward_jump_accepts_record_with_fixed_array_member():
    assert (
        _messages(
            'struct Packet { int values[2]; }; void f(bool flag) { if (flag) { jump("done"); } struct Packet packet; label("done"); }'
        )
        == []
    )


def test_generic_template_cannot_skip_unresolved_storage():
    source = 'class Holder<T> { public void f(bool flag, T input) { if (flag) { jump("done"); } T value = input; label("done"); } }'
    messages = _messages(source)
    assert any(
        "skips the declaration of 'value'" in message and "not a plain C value" in message for message in messages
    ), messages


def test_backward_jump_does_not_enter_variable_length_storage():
    assert _messages('void f(int count) { label("again"); int values[count]; jump("again"); }') == []
