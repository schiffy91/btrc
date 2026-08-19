import ast
from pathlib import Path

import pytest

from src.compiler.python.frontend.imports import ImportResolver
from src.compiler.python.frontend.packages import IncludeResolutionError, PackageUniverse
import src.compiler.python.frontend.sources as frontend_sources
from src.compiler.python.frontend.sources import (
    SourceDirectoryScanner,
    SourceResolutionPolicy,
    SourceResolver,
    StdlibRepository,
)
from src.compiler.python.frontend.stage import FrontendStage

RESOLVER = FrontendStage().resolver


def test_source_resolver_owns_one_shared_import_repository(tmp_path):
    stdlib = StdlibRepository(directory=str(tmp_path / "stdlib"))
    imports = ImportResolver(stdlib)
    packages = PackageUniverse()
    resolver = SourceResolver(
        stdlib,
        imports=imports,
        package_universe=packages,
    )

    assert resolver.imports is imports
    assert resolver.stdlib is stdlib
    assert resolver.imports.stdlib is resolver.stdlib
    assert resolver.resolution_policy is imports.resolution_policy
    assert resolver.resolution_policy is stdlib.resolution_policy
    assert resolver.package_universe is packages


def test_source_resolver_rejects_inconsistent_import_ownership(tmp_path):
    first = StdlibRepository(directory=str(tmp_path / "first"))
    second = StdlibRepository(directory=str(tmp_path / "second"))

    with pytest.raises(ValueError, match="share one repository"):
        SourceResolver(first, imports=ImportResolver(second))


def test_source_resolution_limits_have_one_owned_policy() -> None:
    module = ast.parse(Path(frontend_sources.__file__).read_text())
    loose_behavior = [node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    policy = SourceResolutionPolicy(max_source_bytes=1024)
    resolver = FrontendStage(resolution_policy=policy).resolver

    assert loose_behavior == []
    assert resolver.resolution_policy is policy
    assert resolver.imports.resolution_policy is policy
    assert resolver.stdlib.resolution_policy is policy


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


def test_resolved_import_source_has_an_aggregate_byte_limit(tmp_path):
    root = tmp_path / "main.btrc"
    child = tmp_path / "child.btrc"
    root.write_text('#include "child.btrc"\nint main() { return 0; }\n')
    child.write_text("class Child { int payload; }\n")
    total = len(root.read_bytes()) + len(child.read_bytes())
    resolver = FrontendStage(
        resolution_policy=SourceResolutionPolicy(max_source_bytes=total - 1),
    ).resolver

    with pytest.raises(IncludeResolutionError, match="resolved source exceeds"):
        resolver.resolve_includes(root.read_text(), str(root), exit_on_error=False)


def test_import_graph_depth_is_bounded_before_python_recursion(tmp_path):
    root = tmp_path / "main.btrc"
    first = tmp_path / "first.btrc"
    second = tmp_path / "second.btrc"
    root.write_text('#include "first.btrc"\n')
    first.write_text('#include "second.btrc"\n')
    second.write_text("class End {}\n")
    resolver = FrontendStage(resolution_policy=SourceResolutionPolicy(max_depth=1)).resolver

    with pytest.raises(IncludeResolutionError, match="maximum depth"):
        resolver.resolve_includes(root.read_text(), str(root), exit_on_error=False)


def test_import_graph_unique_file_count_is_bounded(tmp_path):
    root = tmp_path / "main.btrc"
    root.write_text('#include "one.btrc"\n#include "two.btrc"\n')
    (tmp_path / "one.btrc").write_text("class One {}\n")
    (tmp_path / "two.btrc").write_text("class Two {}\n")
    resolver = FrontendStage(resolution_policy=SourceResolutionPolicy(max_files=2)).resolver

    with pytest.raises(IncludeResolutionError, match="file limit"):
        resolver.resolve_includes(root.read_text(), str(root), exit_on_error=False)


def test_directory_import_is_bounded_while_scanning(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for index in range(3):
        (modules / f"module_{index}.btrc").write_text(f"class Module{index} {{}}\n")
    imports = ImportResolver(
        directory_scanner=SourceDirectoryScanner(max_files=2),
    )
    resolver = SourceResolver(imports=imports)

    with pytest.raises(IncludeResolutionError, match="import directory exceeds"):
        resolver.resolve_includes(
            "import ./modules/*\n",
            str(tmp_path / "main.btrc"),
            exit_on_error=False,
        )


def test_directory_import_scan_counts_non_source_entries(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for index in range(3):
        (modules / f"ignored_{index}.txt").write_text("not source\n")
    imports = ImportResolver(
        directory_scanner=SourceDirectoryScanner(max_entries=2),
    )
    resolver = SourceResolver(imports=imports)

    with pytest.raises(IncludeResolutionError, match="entry scan limit"):
        resolver.resolve_includes(
            "import ./modules/*\n",
            str(tmp_path / "main.btrc"),
            exit_on_error=False,
        )
