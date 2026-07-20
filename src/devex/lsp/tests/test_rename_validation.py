"""Rename requests must produce identifiers accepted by the language grammar."""

import pytest

from src.devex.lsp.references import get_rename_edits
from src.devex.lsp.tests.lsphelp import SAMPLE, analyze, pos_of


@pytest.mark.parametrize(
    "new_name",
    [
        "",
        "2fast",
        "two words",
        "has-dash",
        "class",
        "return",
        "café",
        "name\nnext",
    ],
)
def test_rename_rejects_invalid_identifiers_and_keywords(new_name):
    result = analyze(SAMPLE)
    position = pos_of(SAMPLE, "p = Point", offset=0)

    assert get_rename_edits(result, position, new_name) is None


@pytest.mark.parametrize("new_name", ["_next", "next2", "CamelCase"])
def test_rename_accepts_legal_identifiers(new_name):
    result = analyze(SAMPLE)
    position = pos_of(SAMPLE, "p = Point", offset=0)

    edit = get_rename_edits(result, position, new_name)

    assert edit is not None
    assert edit.changes
    assert {item.new_text for edits in edit.changes.values() for item in edits} == {new_name}
