"""VS Code extension asset coverage.

These tests keep the packaged editor entry points aligned with production LSP
features: language activation, syntax grammar, icon/config assets, and the
launcher path that starts the Python server.
"""

import json
from pathlib import Path

EXT_DIR = Path(__file__).resolve().parents[2] / "ext"


def test_extension_manifest_activates_btrc_language_and_assets_exist():
    package = json.loads((EXT_DIR / "package.json").read_text())

    assert "onLanguage:btrc" in package["activationEvents"]

    language = package["contributes"]["languages"][0]
    assert language["id"] == "btrc"
    assert ".btrc" in language["extensions"]
    assert (EXT_DIR / language["icon"]["light"]).exists()
    assert (EXT_DIR / language["icon"]["dark"]).exists()
    assert (EXT_DIR / language["configuration"]).exists()

    grammar = package["contributes"]["grammars"][0]
    assert grammar["language"] == "btrc"
    assert grammar["scopeName"] == "source.btrc"
    assert (EXT_DIR / grammar["path"]).exists()


def test_textmate_grammar_covers_compiler_keywords():
    grammar_text = (EXT_DIR / "syntaxes" / "btrc.tmLanguage.json").read_text()

    for keyword in [
        "abstract",
        "catch",
        "class",
        "finally",
        "implements",
        "import",
        "interface",
        "keep",
        "override",
        "parallel",
        "spawn",
        "try",
    ]:
        assert keyword in grammar_text


def test_extension_launcher_starts_real_lsp_server():
    extension = (EXT_DIR / "src" / "extension.ts").read_text()

    assert "LanguageClient" in extension
    assert "src', 'devex', 'lsp', 'server.py" in extension
    assert "nix" in extension and "develop" in extension
    assert "btrc.serverPath" in extension
