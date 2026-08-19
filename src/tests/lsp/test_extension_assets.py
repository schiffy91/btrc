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

REPO_ROOT = Path(__file__).resolve().parents[3]
EXT_DIR = REPO_ROOT / "src" / "devex" / "vscode"


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
    assert project["project"]["scripts"]["btrc-lsp"] == "src.devex.lsp.__main__:main"
    assert "pygls>=2.0.0" in project["project"]["dependencies"]
    assert "lsprotocol>=2023.0.0" in project["project"]["dependencies"]


def test_textmate_grammar_covers_compiler_keywords():
    grammar_text = (EXT_DIR / "config" / "grammar.json").read_text()

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
    grammar = json.loads((EXT_DIR / "config" / "grammar.json").read_text())
    variables = grammar["repository"]["variables"]
    expression_includes = [
        entry["include"] for entry in grammar["repository"]["expression"]["patterns"] if "include" in entry
    ]

    assert variables["captures"]["1"]["name"] == "variable.other.readwrite.btrc"
    assert "#variables" in expression_includes


def test_extension_launcher_starts_real_lsp_server():
    extension = (EXT_DIR / "src" / "application" / "controller.ts").read_text()
    launch = (EXT_DIR / "src" / "language_server" / "launcher.ts").read_text()

    assert "LanguageClient" in extension
    assert "LanguageServerLaunchResolver" in extension
    assert "serverCommand" in extension
    assert "btrc-lsp" in (EXT_DIR / "package.json").read_text()
    for component in ("'src'", "'devex'", "'lsp'", "'__main__.py'"):
        assert component in launch
    assert "src.devex.lsp" in launch
    assert "context.extensionPath, 'server'" in launch
    assert "nix" in launch and "develop" in launch
    assert "nix-shell" in launch and "workspaceShellNix" in launch
    assert "workspaceFlake" in launch
    assert "serverPath" in launch
    assert (REPO_ROOT / "src" / "tests" / "vscode" / "language_server_launcher.test.js").exists()


def test_extension_packaging_stages_lsp_payload(tmp_path):
    script_path = EXT_DIR / "packaging" / "bundle.py"
    spec = importlib.util.spec_from_file_location("vscode_bundle", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    extension_root = module.ExtensionBundler(
        REPO_ROOT,
        output_root=tmp_path / "build" / "devex" / "vscode",
    ).bundle()
    bundle_root = extension_root / "server"

    assert (bundle_root / "src" / "devex" / "lsp" / "__main__.py").exists()
    compiler_root = bundle_root / "src" / "compiler" / "python"
    assert (compiler_root / "application" / "compiler.py").exists()
    assert (compiler_root / "application" / "pipeline.py").exists()
    assert (compiler_root / "frontend" / "sources.py").exists()
    assert not (bundle_root / "src" / "compiler" / "btrc").exists()
    assert (bundle_root / "src" / "language" / "grammar.ebnf").exists()
    assert (bundle_root / "src" / "stdlib" / "process.btrc").exists()
    for dependency in ("pygls", "lsprotocol", "attrs", "cattrs"):
        assert (bundle_root / "vendor" / dependency).is_dir()
    assert (bundle_root / "vendor" / "typing_extensions.py").is_file()
    staged_debug = bundle_root / "src" / "devex" / "debug"
    expected_debug_modules = {
        path.relative_to(REPO_ROOT / "src" / "devex" / "debug")
        for path in (REPO_ROOT / "src" / "devex" / "debug").rglob("*.py")
    }
    assert {path.relative_to(staged_debug) for path in staged_debug.rglob("*.py")} == expected_debug_modules
    assert (bundle_root / "flake.lock").read_text() == (REPO_ROOT / "flake.lock").read_text()
    bundled_flake = (bundle_root / "flake.nix").read_text()
    assert "Bundled btrc language server" in bundled_flake
    assert "pkgs.git" in bundled_flake
    assert "ps.pygls ps.lsprotocol" in bundled_flake
    assert not (bundle_root / "src" / "devex" / "lsp" / "tests").exists()
    assert not any(bundle_root.rglob(".DS_Store"))
    assert not any(bundle_root.rglob("*.o"))
    assert not any(bundle_root.rglob("*.a"))

    isolated_import = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            "import runpy, sys; "
            "sys.path[:0] = ['.', 'vendor']; "
            "runpy.run_module('src.devex.lsp', run_name='packaged_probe')",
        ],
        cwd=bundle_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert isolated_import.returncode == 0, isolated_import.stderr


def test_extension_packaging_replaces_read_only_previous_staging(tmp_path):
    script_path = EXT_DIR / "packaging" / "bundle.py"
    spec = importlib.util.spec_from_file_location("vscode_bundle_replacement", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    bundler = module.ExtensionBundler(
        REPO_ROOT,
        output_root=tmp_path / "build" / "devex" / "vscode",
    )
    first = bundler.bundle() / "server"
    vendored_package = first / "vendor" / "pygls"
    vendored_file = next(path for path in vendored_package.rglob("*") if path.is_file())
    vendored_file.chmod(stat.S_IMODE(vendored_file.stat().st_mode) & ~stat.S_IWUSR)
    if os.name != "nt":
        for directory in [vendored_package, *vendored_package.rglob("*")]:
            if directory.is_dir():
                directory.chmod(stat.S_IMODE(directory.stat().st_mode) & ~stat.S_IWUSR)

    second = bundler.bundle() / "server"

    assert second == first
    assert (second / "vendor" / "pygls").is_dir()
    assert all(
        stat.S_IMODE(path.stat().st_mode) & stat.S_IWUSR
        for path in (second / "vendor").rglob("*")
        if not path.is_symlink()
    )


@pytest.mark.parametrize("metadata_root", ["", "."])
def test_extension_packaging_rejects_distribution_root_metadata(tmp_path, monkeypatch, metadata_root):
    script_path = EXT_DIR / "packaging" / "bundle.py"
    spec = importlib.util.spec_from_file_location("vscode_bundle_metadata", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    class MalformedDistribution:
        files = (metadata_root,)

        @staticmethod
        def locate_file(_root):
            raise AssertionError("unsafe metadata must be rejected before locating its payload")

    monkeypatch.setattr(module, "_VENDORED_DISTRIBUTIONS", ("malformed",))
    monkeypatch.setattr(module.importlib.metadata, "distribution", lambda _name: MalformedDistribution())

    with pytest.raises(RuntimeError, match="unsafe path"):
        module.ExtensionBundler(tmp_path)._vendor_runtime_dependencies(tmp_path / "vendor")


@pytest.mark.skipif(os.name == "nt", reason="creating directory symlinks may require elevated Windows privileges")
def test_extension_packaging_removes_staging_symlink_without_touching_target(tmp_path):
    script_path = EXT_DIR / "packaging" / "bundle.py"
    spec = importlib.util.spec_from_file_location("vscode_bundle_symlink", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "sentinel.txt"
    sentinel.write_text("untouched\n")
    external.chmod(0o555)
    sentinel.chmod(0o444)
    external_mode = stat.S_IMODE(external.stat().st_mode)
    sentinel_mode = stat.S_IMODE(sentinel.stat().st_mode)
    staging = tmp_path / "ext" / "server"
    staging.parent.mkdir()
    staging.symlink_to(external, target_is_directory=True)

    try:
        bundler = module.ExtensionBundler(tmp_path)
        bundler._remove_tree(staging)

        assert not staging.exists()
        assert not staging.is_symlink()
        assert external.is_dir()
        assert sentinel.read_text() == "untouched\n"
        assert stat.S_IMODE(external.stat().st_mode) == external_mode
        assert stat.S_IMODE(sentinel.stat().st_mode) == sentinel_mode

        broken = staging.parent / "broken"
        broken.symlink_to(tmp_path / "missing", target_is_directory=True)
        bundler._remove_tree(broken)
        assert not broken.is_symlink()
    finally:
        external.chmod(0o755)
        sentinel.chmod(0o644)


def test_make_extension_exports_the_nix_python_to_packaging():
    makefile = (REPO_ROOT / "Makefile").read_text()
    recipe = makefile.split("\nextension:", 1)[1].split("\nextension-install:", 1)[0]

    assert "$(NIX) bash -c" in recipe
    assert 'BTRC_PACKAGING_PYTHON="$$(command -v python3)"' in recipe


def test_extension_package_keeps_bundled_server_payload():
    ignored = (EXT_DIR / ".vscodeignore").read_text().splitlines()

    assert "server/**" not in ignored
    assert "server/src/tests/**" in ignored
    assert "packaging/**" in ignored
    assert "package-lock.json" in ignored
    assert "**/__pycache__/**" in ignored
    assert "**/*.pyc" in ignored


def test_nix_extension_package_installs_staged_debug_adapter():
    flake = (REPO_ROOT / "flake.nix").read_text()

    assert '"src/devex/debug/"' in flake
    assert '"src/devex/vscode/"' in flake
    assert 'cp -R assets config out server "$extension"/' in flake
    assert "nativeBuildInputs = [ pkgs.esbuild lspPython ];" in flake
