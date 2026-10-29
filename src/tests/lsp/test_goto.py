"""Label navigation keeps function, lambda and variable namespaces separate."""

from src.tests.lsp.lsphelp import (
    analyze,
    get_definition,
    get_document_highlights,
    get_references,
    get_rename_edits,
    pos_of,
)

SOURCE = """void first() {
    int done = 0;
    var run = () => { goto done; done: ; };
    goto done;
    done:
    print(done);
}
void second() { goto done; done: ; }
"""


def test_goto_definition_and_label_definition_ignore_same_named_variable():
    result = analyze(SOURCE)
    loc = get_definition(result, pos_of(SOURCE, "goto done", occurrence=2, offset=5))
    assert loc is not None and (loc.range.start.line, loc.range.start.character) == (4, 4)
    assert get_definition(result, pos_of(SOURCE, "done:\n", offset=1)) is None
    loc = get_definition(result, pos_of(SOURCE, "print(done)", offset=7))
    assert loc is not None and loc.range.start.line == 1


def test_label_references_and_rename_stay_in_callable():
    result = analyze(SOURCE)
    position = pos_of(SOURCE, "goto done", occurrence=2, offset=5)
    assert {loc.range.start.line for loc in get_references(result, position)} == {3, 4}
    assert {loc.range.start.line for loc in get_references(result, position, False)} == {3}
    edit = get_rename_edits(result, position, "finished")
    assert edit is not None
    assert {entry.range.start.line for entries in edit.changes.values() for entry in entries} == {3, 4}
    inner = pos_of(SOURCE, "goto done", offset=5)
    assert len(get_references(result, inner)) == 2
    assert all(loc.range.start.line == 2 for loc in get_references(result, inner))


def test_label_highlights_do_not_include_same_named_variable():
    result = analyze(SOURCE)
    highlights = get_document_highlights(result, pos_of(SOURCE, "goto done", occurrence=2, offset=5))
    assert {highlight.range.start.line for highlight in highlights} == {3, 4}
