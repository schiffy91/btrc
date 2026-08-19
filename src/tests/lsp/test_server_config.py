"""Language-server environment configuration contracts."""

import pytest

from src.devex.lsp.protocol.server import BtrcLanguageServer

DEFAULT_DEBOUNCE_SECONDS = BtrcLanguageServer.DEFAULT_DEBOUNCE_SECONDS
MAX_DEBOUNCE_SECONDS = BtrcLanguageServer.MAX_DEBOUNCE_SECONDS
parse_debounce_seconds = BtrcLanguageServer.parse_debounce_seconds


@pytest.mark.parametrize(
    "value",
    [None, "", "invalid", "nan", "inf", "-0.1", "5.0001", "1e300"],
)
def test_invalid_debounce_values_fall_back_to_the_safe_default(value):
    assert parse_debounce_seconds(value) == DEFAULT_DEBOUNCE_SECONDS


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0", 0.0), ("0.25", 0.25), ("2", 2.0), ("5", MAX_DEBOUNCE_SECONDS)],
)
def test_valid_debounce_values_are_preserved(value, expected):
    assert parse_debounce_seconds(value) == expected
