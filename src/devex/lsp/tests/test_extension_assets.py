"""VS Code extension asset coverage.

These tests keep the packaged editor entry points aligned with production LSP
features: language activation, syntax grammar, icon/config assets, and the
launcher path that starts the Python server.
"""

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

EXT_DIR = Path(__file__).resolve().parents[2] / "ext"
REPO_ROOT = EXT_DIR.parents[2]


def test_extension_manifest_activates_btrc_language_and_assets_exist():
    package = json.loads((EXT_DIR / "package.json").read_text())

    assert "onLanguage:btrc" in package["activationEvents"]
    assert package["contributes"]["configurationDefaults"]["[btrc]"]["editor.semanticHighlighting.enabled"] is True

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
    assert not (bundle_root / "src" / "compiler" / "btrc").exists()
    assert (bundle_root / "src" / "language" / "grammar.ebnf").exists()
    assert (bundle_root / "src" / "stdlib" / "process.btrc").exists()
    staged_debug = ext_dir / "debug"
    expected_debug_modules = {path.name for path in (REPO_ROOT / "src" / "devex" / "debug").glob("*.py")}
    assert {path.name for path in staged_debug.glob("*.py")} == expected_debug_modules
    assert (bundle_root / "flake.lock").read_text() == (REPO_ROOT / "flake.lock").read_text()
    bundled_flake = (bundle_root / "flake.nix").read_text()
    assert "Bundled btrc language server" in bundled_flake
    assert "pkgs.git" in bundled_flake
    assert "ps.pygls ps.lsprotocol" in bundled_flake
    assert not (bundle_root / "src" / "devex" / "lsp" / "tests").exists()
    assert not any(bundle_root.rglob(".DS_Store"))
    assert not any(bundle_root.rglob("*.o"))
    assert not any(bundle_root.rglob("*.a"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory modes model the Nix store")
def test_extension_packaging_regenerates_inside_read_only_source_copy(tmp_path, monkeypatch):
    script_path = EXT_DIR / "scripts" / "prepare_lsp_package.py"
    spec = importlib.util.spec_from_file_location("prepare_lsp_package_read_only", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    repo = tmp_path / "repo"
    generator = repo / "src" / "compiler" / "python" / "ast" / "gen_builtins.py"
    generator.parent.mkdir(parents=True)
    generator.write_text(
        "from pathlib import Path\n"
        "root = Path(__file__).resolve().parents[4]\n"
        "target = root / 'src/devex/lsp/builtins.py'\n"
        "temporary = target.with_name('.builtins.tmp')\n"
        "temporary.write_text('generated\\n')\n"
        "temporary.replace(target)\n"
    )
    (repo / "src" / "stdlib").mkdir(parents=True)
    (repo / "src" / "stdlib" / "core.btrc").write_text("class Core {}\n")
    (repo / "src" / "language").mkdir(parents=True)
    (repo / "src" / "language" / "grammar.ebnf").write_text("@keywords\n")
    lsp_source = repo / "src" / "devex" / "lsp"
    lsp_source.mkdir(parents=True)
    source_builtins = lsp_source / "builtins.py"
    source_builtins.write_text("stale\n")
    source_mode = stat.S_IMODE(lsp_source.stat().st_mode)
    lsp_source.chmod(0o555)
    source_builtins.chmod(0o444)
    monkeypatch.setenv("BTRC_PACKAGING_PYTHON", sys.executable)

    try:
        bundle = module.prepare(ext_dir=tmp_path / "ext", repo_root=repo)
        assert stat.S_IMODE(lsp_source.stat().st_mode) == 0o555
    finally:
        lsp_source.chmod(source_mode)

    staged_lsp = bundle / "src" / "devex" / "lsp"
    assert (staged_lsp / "builtins.py").read_text() == "generated\n"
    assert stat.S_IMODE(staged_lsp.stat().st_mode) & stat.S_IWUSR
    assert source_builtins.read_text() == "stale\n"
    assert stat.S_IMODE(source_builtins.stat().st_mode) == 0o444


def test_extension_packaging_uses_the_explicit_supported_python(tmp_path, monkeypatch):
    script_path = EXT_DIR / "scripts" / "prepare_lsp_package.py"
    spec = importlib.util.spec_from_file_location("prepare_lsp_package_runtime", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    bundle_root = tmp_path / "server"
    generator = bundle_root / "src" / "compiler" / "python" / "ast" / "gen_builtins.py"
    generator.parent.mkdir(parents=True)
    generator.write_text("raise AssertionError('test must not execute the generator')\n")
    calls = []

    def record_run(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setenv("BTRC_PACKAGING_PYTHON", "/nix/store/supported-python/bin/python3")
    monkeypatch.setattr(module.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(module.subprocess, "run", record_run)

    module._regenerate_builtins(bundle_root)

    assert calls[0][0][0] == "/nix/store/supported-python/bin/python3"
    assert calls[0][0][0] != module.sys.executable
    assert calls[0][1]["cwd"] == bundle_root


def test_make_extension_exports_the_nix_python_to_packaging():
    makefile = (REPO_ROOT / "Makefile").read_text()
    recipe = makefile.split("\nextension:", 1)[1].split("\nextension-install:", 1)[0]

    assert "$(NIX) bash -c" in recipe
    assert 'BTRC_PACKAGING_PYTHON="$$(command -v python3)"' in recipe


def test_extension_packaging_rejects_an_unsupported_implicit_python(monkeypatch):
    script_path = EXT_DIR / "scripts" / "prepare_lsp_package.py"
    spec = importlib.util.spec_from_file_location("prepare_lsp_package_unsupported", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delenv("BTRC_PACKAGING_PYTHON", raising=False)
    monkeypatch.setattr(module.sys, "version_info", (3, 9, 6))

    with pytest.raises(RuntimeError, match=r"requires Python 3\.13\+"):
        module._generator_python()


def test_extension_package_keeps_bundled_server_payload():
    ignored = (EXT_DIR / ".vscodeignore").read_text().splitlines()

    assert "server/**" not in ignored
    assert "server/src/devex/lsp/tests/**" in ignored
    assert "scripts/**" in ignored
    assert "test/**" in ignored
    assert "package-lock.json" in ignored
    assert "**/__pycache__/**" in ignored
    assert "**/*.pyc" in ignored


def test_nix_extension_package_installs_staged_debug_adapter():
    flake = (REPO_ROOT / "flake.nix").read_text()

    assert '"src/devex/debug/"' in flake
    assert '"src/devex/ext/debug/"' in flake
    assert 'cp -R debug icons out server syntaxes "$extension"/' in flake
