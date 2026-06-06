"""VS Code extension asset coverage.

These tests keep the packaged editor entry points aligned with production LSP
features: language activation, syntax grammar, icon/config assets, and the
launcher path that starts the Python server.
"""

import importlib.util
import json
import tomllib
from pathlib import Path

EXT_DIR = Path(__file__).resolve().parents[2] / "ext"
REPO_ROOT = EXT_DIR.parents[2]


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

    config = package["contributes"]["configuration"]["properties"]
    assert config["btrc.serverCommand"]["default"] == "btrc-lsp"
    assert "btrc-lsp" in config["btrc.serverCommand"]["description"]

    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert project["project"]["scripts"]["btrc-lsp"] == "src.devex.lsp.server:main"
    assert "pygls>=1.3.0" in project["project"]["dependencies"]
    assert "lsprotocol>=2023.0.0" in project["project"]["dependencies"]


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


def test_textmate_grammar_colors_variables_inside_expressions():
    grammar = json.loads((EXT_DIR / "syntaxes" / "btrc.tmLanguage.json").read_text())
    variables = grammar["repository"]["variables"]
    expression_includes = [
        entry["include"] for entry in grammar["repository"]["expression"]["patterns"] if "include" in entry
    ]

    assert variables["captures"]["1"]["name"] == "variable.other.readwrite.btrc"
    assert "#variables" in expression_includes


def test_extension_launcher_starts_real_lsp_server():
    extension = (EXT_DIR / "src" / "extension.ts").read_text()
    launch = (EXT_DIR / "src" / "launch.ts").read_text()

    assert "LanguageClient" in extension
    assert "resolveServerLaunch" in extension
    assert "serverCommand" in extension
    assert "btrc-lsp" in (EXT_DIR / "package.json").read_text()
    assert "src', 'devex', 'lsp', 'server.py" in launch
    assert "context.extensionPath, 'server'" in launch
    assert "nix" in launch and "develop" in launch
    assert "nix-shell" in launch and "workspaceShellNix" in launch
    assert "workspaceFlake" in launch
    assert "serverPath" in launch
    assert (EXT_DIR / "test" / "launch.test.js").exists()


def test_extension_packaging_stages_lsp_payload(tmp_path):
    script_path = EXT_DIR / "scripts" / "prepare_lsp_package.py"
    spec = importlib.util.spec_from_file_location("prepare_lsp_package", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    ext_dir = tmp_path / "ext"
    ext_dir.mkdir()
    bundle_root = module.prepare(ext_dir=ext_dir, repo_root=REPO_ROOT)

    assert (bundle_root / "src" / "devex" / "lsp" / "server.py").exists()
    assert (bundle_root / "src" / "compiler" / "python" / "frontend.py").exists()
    assert (bundle_root / "src" / "stdlib" / "process.btrc").exists()
    bundled_flake = (bundle_root / "flake.nix").read_text()
    assert "Bundled btrc language server" in bundled_flake
    assert "ps.pygls ps.lsprotocol" in bundled_flake
    assert not (bundle_root / "src" / "devex" / "lsp" / "tests").exists()


def test_extension_package_keeps_bundled_server_payload():
    ignored = (EXT_DIR / ".vscodeignore").read_text().splitlines()

    assert "server/**" not in ignored
    assert "server/src/devex/lsp/tests/**" in ignored
    assert "**/__pycache__/**" in ignored
    assert "**/*.pyc" in ignored
