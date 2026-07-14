"""LSP package-import integration and package-context isolation."""

from __future__ import annotations

import json
import os

import pytest

from src.compiler.python import frontend_limits, pkg
from src.devex.lsp import package_resolution
from src.devex.lsp.diagnostics import compute_diagnostics
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


def test_package_resolution_retries_when_manifest_changes_during_save(tmp_path, monkeypatch):
    manifest = tmp_path / "btrc.toml"
    manifest.write_text("[dependencies]\nold = '../old'\n")
    active = tmp_path / "main.btrc"
    calls = []

    monkeypatch.setattr(pkg, "find_manifest", lambda _start: str(manifest))

    def resolve(_input_path):
        calls.append(manifest.read_text())
        if len(calls) == 1:
            manifest.write_text("[dependencies]\nfresh = '../fresh'\n")
            return {"old": {"path": "../old"}}
        return {"fresh": {"path": "../fresh"}}

    monkeypatch.setattr(pkg, "packages_for", resolve)
    resolver = package_resolution.PackageResolver()

    expected = {"fresh": {"path": "../fresh"}}
    assert resolver.packages_for(str(active)) == expected
    assert len(calls) == 2
    assert resolver.packages_for(str(active)) == expected
    assert len(calls) == 2


def test_package_resolution_never_caches_repeatedly_changing_inputs(tmp_path, monkeypatch):
    manifest = tmp_path / "btrc.toml"
    manifest.write_text("[dependencies]\n")
    active = tmp_path / "main.btrc"
    calls = []

    monkeypatch.setattr(pkg, "find_manifest", lambda _start: str(manifest))

    def unstable(_input_path):
        calls.append(len(calls) + 1)
        manifest.write_text(f"[dependencies]\ndep = '../version-{len(calls)}'\n")
        return {"dep": {"path": f"../version-{len(calls)}"}}

    monkeypatch.setattr(pkg, "packages_for", unstable)
    resolver = package_resolution.PackageResolver()

    with pytest.raises(pkg.IncludeResolutionError, match="changed repeatedly"):
        resolver.packages_for(str(active))

    assert len(calls) == resolver._STABLE_RESOLUTION_ATTEMPTS
    assert resolver._entries == {}


def test_package_fingerprints_bound_manifest_and_lock_reads(tmp_path):
    package_input = tmp_path / "package-input"
    package_input.write_bytes(b"12345")

    assert package_resolution._file_digest(str(package_input), 4) == ("too-large",)
    assert package_resolution._file_digest(str(package_input), 5)[0] == "sha256"
    assert package_resolution._file_digest(str(tmp_path / "missing"), 5) == ("missing",)


def test_workspace_package_resolution_cache_is_lru_bounded(tmp_path, monkeypatch):
    resolver = package_resolution.PackageResolver()
    monkeypatch.setattr(pkg, "find_manifest", lambda start: f"{start}/btrc.toml")
    monkeypatch.setattr(pkg, "packages_for", lambda _input: {})

    for index in range(resolver._ENTRY_CACHE_MAX + 5):
        resolver.packages_for(str(tmp_path / str(index) / "main.btrc"))

    assert len(resolver._entries) == resolver._ENTRY_CACHE_MAX
    evicted = os.path.normcase(os.path.realpath(tmp_path / "0" / "btrc.toml"))
    assert evicted not in resolver._entries


def test_workspace_import_composition_enforces_the_shared_byte_budget(tmp_path, monkeypatch):
    active, source, module = _path_dependency_project(tmp_path, "bounded")
    monkeypatch.setattr(
        frontend_limits,
        "MAX_RESOLVED_SOURCE_BYTES",
        len(source.encode()) + len(module.read_bytes()) - 1,
    )
    workspace = Workspace()

    composition = workspace.compose(workspace.parse_active(str(active), source))

    assert composition.imported == []
    assert any("resolved source exceeds" in message for _, message in composition.import_errors)


def test_diagnostic_snapshot_invalidates_when_import_error_changes(tmp_path):
    app = tmp_path / "app"
    dependency = tmp_path / "dep"
    app.mkdir()
    dependency.mkdir()
    manifest = app / "btrc.toml"
    manifest.write_text("[dependencies]\n")
    active = app / "main.btrc"
    source = "import dep;\nint main() { return 0; }\n"

    first = compute_diagnostics(active.as_uri(), source)
    first_messages = [diagnostic.message for diagnostic in first.diagnostics]
    assert any("dep" in message for message in first_messages)

    manifest.write_text('[dependencies]\ndep = { path = "../dep" }\n')
    second = compute_diagnostics(active.as_uri(), source)
    second_messages = [diagnostic.message for diagnostic in second.diagnostics]

    assert second is not first
    assert second_messages != first_messages
    assert any("dependency 'dep'" in message for message in second_messages)
