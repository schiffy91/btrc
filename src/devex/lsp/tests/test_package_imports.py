"""LSP package-import integration and package-context isolation."""

from __future__ import annotations

import json

from src.compiler.python import pkg
from src.devex.lsp.workspace import Workspace


def _path_dependency_project(root, marker: str):
    dependency = root / f"shared-{marker}"
    (dependency / "src").mkdir(parents=True)
    module = dependency / "src" / "shared.btrc"
    module.write_text(f"int shared_{marker}() {{ return 1; }}\n")

    app = root / f"app-{marker}"
    app.mkdir()
    (app / "btrc.toml").write_text(f'[dependencies]\nshared = {{ path = "../shared-{marker}" }}\n')
    source = f"import shared;\nint main() {{ return shared_{marker}(); }}\n"
    active = app / "main.btrc"
    active.write_text(source)
    return active, source, module


def test_package_imports_are_scoped_to_each_document_root(tmp_path):
    first_path, first_source, first_module = _path_dependency_project(tmp_path, "first")
    second_path, second_source, second_module = _path_dependency_project(tmp_path, "second")
    workspace = Workspace()
    sentinel = {"outer": {"path": "/embedding-host"}}

    with pkg.package_context(sentinel):
        first = workspace.compose(workspace.parse_active(str(first_path), first_source))
        assert first.import_errors == []
        assert [unit.path for unit in first.imported] == [str(first_module)]
        assert pkg.configured_packages()["outer"]["path"] == "/embedding-host"

        second = workspace.compose(workspace.parse_active(str(second_path), second_source))
        assert second.import_errors == []
        assert [unit.path for unit in second.imported] == [str(second_module)]
        assert pkg.configured_packages()["outer"]["path"] == "/embedding-host"

    for active in (first_path, second_path):
        lock = json.loads((active.parent / "btrc.lock").read_text())
        assert lock["schema"] == pkg.LOCK_SCHEMA


def test_broken_manifest_reports_error_without_leaking_package_state(tmp_path):
    app = tmp_path / "broken"
    app.mkdir()
    (app / "btrc.toml").write_text('[dependencies]\nbad = { version = "unsupported" }\n')
    source = "import bad;\nint main() { return 0; }\n"
    active = app / "main.btrc"
    sentinel = {"outer": {"path": "/embedding-host"}}

    with pkg.package_context(sentinel):
        workspace = Workspace()
        composition = workspace.compose(workspace.parse_active(str(active), source))
        assert any("package resolution failed" in message for _, message in composition.import_errors)
        assert pkg.configured_packages()["outer"]["path"] == "/embedding-host"


def test_unchanged_manifest_reuses_workspace_package_resolution(tmp_path, monkeypatch):
    active, source, module = _path_dependency_project(tmp_path, "cached")
    workspace = Workspace()
    first = workspace.compose(workspace.parse_active(str(active), source))
    assert [unit.path for unit in first.imported] == [str(module)]

    def unexpected_resolution(_input_path):
        raise AssertionError("warm keystroke re-resolved unchanged packages")

    monkeypatch.setattr(pkg, "packages_for", unexpected_resolution)
    second = workspace.compose(workspace.parse_active(str(active), source + "\n"))
    assert second.import_errors == []
    assert [unit.path for unit in second.imported] == [str(module)]
