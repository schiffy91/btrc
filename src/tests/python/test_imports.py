import pytest

from src.compiler.python import frontend_limits
from src.compiler.python.frontend.imports import ImportResolver
from src.compiler.python.frontend.resolver import SourceResolver
from src.compiler.python.frontend.stdlib import StdlibRepository
from src.compiler.python.pkg import IncludeResolutionError, PackageResolver

RESOLVER = SourceResolver()


def test_source_resolver_owns_one_shared_import_repository(tmp_path):
    stdlib = StdlibRepository(directory=str(tmp_path / "stdlib"))
    imports = ImportResolver(stdlib)
    packages = PackageResolver()
    resolver = SourceResolver(
        stdlib,
        imports=imports,
        package_resolver=packages,
    )

    assert resolver.imports is imports
    assert resolver.stdlib is stdlib
    assert resolver.imports.stdlib is resolver.stdlib
    assert resolver.package_resolver is packages


def test_source_resolver_rejects_inconsistent_import_ownership(tmp_path):
    first = StdlibRepository(directory=str(tmp_path / "first"))
    second = StdlibRepository(directory=str(tmp_path / "second"))

    with pytest.raises(ValueError, match="share one repository"):
        SourceResolver(first, imports=ImportResolver(second))


def test_std_brace_import_resolves_stdlib():
    source = "import std.{strings, json}\nint main() { return 0; }"
    resolved = RESOLVER.resolve_includes(source, "main.btrc")

    assert "class Strings" in resolved
    assert "class JsonObject" in resolved
    assert "import std" not in resolved


def test_relative_bulk_imports_are_sorted_and_recursive(tmp_path):
    root = tmp_path / "project"
    nested = root / "lib" / "nested"
    nested.mkdir(parents=True)
    (root / "main.btrc").write_text("import ./lib/**\nint main() { return 0; }")
    (root / "lib" / "b.btrc").write_text("class B {}\n")
    (root / "lib" / "a.btrc").write_text("class A {}\n")
    (nested / "c.btrc").write_text("class C {}\n")

    resolved = RESOLVER.resolve_includes((root / "main.btrc").read_text(), str(root / "main.btrc"))

    assert resolved.index("class A") < resolved.index("class B")
    assert "class C" in resolved
    assert "import ./lib/**" not in resolved


def test_resolved_import_source_has_an_aggregate_byte_limit(tmp_path, monkeypatch):
    root = tmp_path / "main.btrc"
    child = tmp_path / "child.btrc"
    root.write_text('#include "child.btrc"\nint main() { return 0; }\n')
    child.write_text("class Child { int payload; }\n")
    total = len(root.read_bytes()) + len(child.read_bytes())
    monkeypatch.setattr(frontend_limits, "MAX_RESOLVED_SOURCE_BYTES", total - 1)

    with pytest.raises(IncludeResolutionError, match="resolved source exceeds"):
        RESOLVER.resolve_includes(root.read_text(), str(root), exit_on_error=False)


def test_import_graph_depth_is_bounded_before_python_recursion(tmp_path, monkeypatch):
    root = tmp_path / "main.btrc"
    first = tmp_path / "first.btrc"
    second = tmp_path / "second.btrc"
    root.write_text('#include "first.btrc"\n')
    first.write_text('#include "second.btrc"\n')
    second.write_text("class End {}\n")
    monkeypatch.setattr(frontend_limits, "MAX_IMPORT_DEPTH", 1)

    with pytest.raises(IncludeResolutionError, match="maximum depth"):
        RESOLVER.resolve_includes(root.read_text(), str(root), exit_on_error=False)


def test_import_graph_unique_file_count_is_bounded(tmp_path, monkeypatch):
    root = tmp_path / "main.btrc"
    root.write_text('#include "one.btrc"\n#include "two.btrc"\n')
    (tmp_path / "one.btrc").write_text("class One {}\n")
    (tmp_path / "two.btrc").write_text("class Two {}\n")
    monkeypatch.setattr(frontend_limits, "MAX_RESOLVED_FILES", 2)

    with pytest.raises(IncludeResolutionError, match="file limit"):
        RESOLVER.resolve_includes(root.read_text(), str(root), exit_on_error=False)


def test_directory_import_is_bounded_while_scanning(tmp_path, monkeypatch):
    modules = tmp_path / "modules"
    modules.mkdir()
    for index in range(3):
        (modules / f"module_{index}.btrc").write_text(f"class Module{index} {{}}\n")
    monkeypatch.setattr(frontend_limits, "MAX_RESOLVED_FILES", 2)

    with pytest.raises(IncludeResolutionError, match="import directory exceeds"):
        RESOLVER.resolve_includes("import ./modules/*\n", str(tmp_path / "main.btrc"), exit_on_error=False)


def test_directory_import_scan_counts_non_source_entries(tmp_path, monkeypatch):
    modules = tmp_path / "modules"
    modules.mkdir()
    for index in range(3):
        (modules / f"ignored_{index}.txt").write_text("not source\n")
    monkeypatch.setattr(frontend_limits, "MAX_IMPORT_SCAN_ENTRIES", 2)

    with pytest.raises(IncludeResolutionError, match="entry scan limit"):
        RESOLVER.resolve_includes("import ./modules/*\n", str(tmp_path / "main.btrc"), exit_on_error=False)
