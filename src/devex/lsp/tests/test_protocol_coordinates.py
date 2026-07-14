"""UTF-16 protocol coordinates and exact rename safety regressions."""

from lsprotocol import types as lsp

from src.devex.lsp.code_actions import get_code_actions
from src.devex.lsp.completion import get_completions
from src.devex.lsp.definition import get_definition
from src.devex.lsp.references import get_rename_edits
from src.devex.lsp.semantic_tokens import get_semantic_tokens
from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.tests.lsphelp import analyze
from src.devex.lsp.text_coordinates import utf16_length


def _position(source: str, needle: str, offset: int = 0, *, last: bool = False):
    index = source.rindex(needle) if last else source.index(needle)
    index += offset
    prefix = source[:index]
    line = prefix.count("\n")
    return lsp.Position(
        line=line,
        character=utf16_length(prefix.rsplit("\n", 1)[-1]),
    )


def test_definition_and_rename_use_utf16_after_astral_character():
    source = 'int main() { string face = "😀"; int value = 1; return value; }\n'
    result = analyze(source)
    use = _position(source, "value", last=True)

    location = get_definition(result, use)
    edit = get_rename_edits(result, use, "answer")

    expected = _position(source, "value")
    assert location is not None and location.range.start == expected
    assert edit is not None
    starts = [item.range.start for items in edit.changes.values() for item in items]
    assert expected in starts and use in starts


def test_completion_and_signature_accept_utf16_carets():
    source = (
        "class Dog { public int bones; public void bark() {} public Dog() {} }\n"
        'int main() { string face = "😀"; Dog dog = Dog(); dog.bark(); print(face); return 0; }\n'
    )
    result = analyze(source)

    members = get_completions(result, _position(source, "dog.bark", offset=4))
    signature = get_signature_help(result, _position(source, "print(face", offset=6))

    assert {item.label for item in members} >= {"bones", "bark"}
    assert signature is not None and signature.signatures[0].label.startswith("print(")


def test_semantic_token_start_is_utf16_not_codepoint_offset():
    source = 'int main() { string face = "😀"; int value = 1; return value; }\n'
    tokens = get_semantic_tokens(analyze(source))
    assert tokens is not None
    expected = _position(source, "value")

    line = column = 0
    positions = []
    for index in range(0, len(tokens.data), 5):
        delta_line, delta_column = tokens.data[index : index + 2]
        line += delta_line
        column = column + delta_column if delta_line == 0 else delta_column
        positions.append((line, column))
    assert (expected.line, expected.character) in positions


def test_code_action_range_does_not_capture_other_typo_on_same_line():
    source = "class Point {}\nint main() { Piont left; Piont right; return 0; }\n"
    result = analyze(source)
    second = _position(source, "Piont", last=True)
    request_range = lsp.Range(
        start=second,
        end=lsp.Position(line=second.line, character=second.character + len("Piont")),
    )
    params = lsp.CodeActionParams(
        text_document=lsp.TextDocumentIdentifier(uri=result.uri),
        range=request_range,
        context=lsp.CodeActionContext(diagnostics=[]),
    )

    actions = get_code_actions(result, params)
    spelling = [action for action in actions if action.title.startswith("Change")]

    assert len(spelling) == 1
    edit = next(iter(spelling[0].edit.changes.values()))[0]
    assert edit.range.start == second


def test_class_rename_does_not_touch_same_spelling_local_variable():
    source = (
        "class Widget { public Widget() {} }\n"
        "int main() { Widget item = Widget(); int Widget = 1; Widget = Widget + 1; return Widget; }\n"
    )
    result = analyze(source)
    edit = get_rename_edits(result, _position(source, "Widget"), "Gadget")

    assert edit is not None
    starts = {(item.range.start.line, item.range.start.character) for items in edit.changes.values() for item in items}
    expected_class_sites = {
        (_position(source, "Widget").line, _position(source, "Widget").character),
        (_position(source, "Widget item").line, _position(source, "Widget item").character),
        (_position(source, "Widget();").line, _position(source, "Widget();").character),
    }
    local = _position(source, "int Widget", offset=4)

    assert expected_class_sites <= starts
    assert (local.line, local.character) not in starts
