import ast
from pathlib import Path

import pytest

import src.compiler.python.frontend.packages as frontend_packages
import src.compiler.python.frontend.sources as frontend_sources
from src.compiler.python.frontend.imports import ImportResolver
from src.compiler.python.frontend.packages import PackageUniverse
from src.compiler.python.frontend.sources import (
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
    assert resolver.package_universe is packages


def test_source_resolver_rejects_inconsistent_import_ownership(tmp_path):
    first = StdlibRepository(directory=str(tmp_path / "first"))
    second = StdlibRepository(directory=str(tmp_path / "second"))

    with pytest.raises(ValueError, match="share one repository"):
        SourceResolver(first, imports=ImportResolver(second))


def test_source_resolution_has_no_compiler_defined_resource_quotas() -> None:
    source_text = Path(frontend_sources.__file__).read_text()
    module = ast.parse(source_text)
    loose_behavior = [node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    declared = {node.name for node in module.body if isinstance(node, ast.ClassDef)}

    assert loose_behavior == []
    assert "SourceResolutionPolicy" not in declared
    assert "ResolutionBudget" not in declared
    for quota in ("max_source_bytes", "max_files", "max_scan_entries", "max_depth", "DEFAULT_MAX_BYTES"):
        assert quota not in source_text


def test_package_resolution_has_no_compiler_defined_resource_quotas() -> None:
    """Import resolution reads packages too, so the same rule binds that layer.

    The ceilings removed from source resolution had counterparts here -- a
    64 MiB JSON cap, a 16 MiB lock cap, a 1 MiB manifest cap, and a 16 KiB ref
    record cap -- and this file was not covered by the check above, which reads
    only the source resolver.
    """

    source_text = Path(frontend_packages.__file__).read_text()

    for quota in (
        "max_bytes",
        "MAX_LOCK_BYTES",
        "MAX_REF_RECORD_BYTES",
        "DEFAULT_MAX_BYTES",
        "64 * 1024 * 1024",
    ):
        assert quota not in source_text


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


def test_resolved_import_source_has_no_aggregate_byte_ceiling(tmp_path):
    root = tmp_path / "main.btrc"
    child = tmp_path / "child.btrc"
    child.write_text("".join(f"int filler_{index} = {index};\n" for index in range(20000)))
    root.write_text('#include "child.btrc"\nint main() { return 0; }\n')
    resolver = FrontendStage().resolver

    resolved = resolver.resolve_includes(root.read_text(), str(root), exit_on_error=False)

    assert "int filler_19999 = 19999;" in resolved
    assert "int main()" in resolved


def test_deeply_nested_includes_resolve_without_a_depth_ceiling(tmp_path):
    depth = 2048
    for index in range(depth):
        path = tmp_path / f"level_{index}.btrc"
        if index + 1 < depth:
            path.write_text(f'#include "level_{index + 1}.btrc"\nint value_{index};\n')
        else:
            path.write_text(f"int value_{index};\n")
    resolver = FrontendStage().resolver

    root = tmp_path / "level_0.btrc"
    resolved = resolver.resolve_includes(root.read_text(), str(root), exit_on_error=False)

    assert f"int value_{depth - 1};" in resolved
    assert resolved.index(f"int value_{depth - 1};") < resolved.index("int value_0;")


def test_import_graph_has_no_unique_file_ceiling(tmp_path):
    count = 512
    root = tmp_path / "main.btrc"
    root.write_text("".join(f'#include "unit_{index}.btrc"\n' for index in range(count)))
    for index in range(count):
        (tmp_path / f"unit_{index}.btrc").write_text(f"int unit_{index};\n")
    resolver = FrontendStage().resolver

    resolved = resolver.resolve_includes(root.read_text(), str(root), exit_on_error=False)

    assert all(f"int unit_{index};" in resolved for index in range(count))


def test_directory_import_has_no_entry_or_file_ceiling(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    count = 400
    for index in range(count):
        (modules / f"module_{index:04d}.btrc").write_text(f"class Module{index} {{}}\n")
        (modules / f"ignored_{index:04d}.txt").write_text("not source\n")
    resolver = SourceResolver(imports=ImportResolver())

    resolved = resolver.resolve_includes(
        "import ./modules/*\n",
        str(tmp_path / "main.btrc"),
        exit_on_error=False,
    )

    assert all(f"class Module{index} " in resolved for index in range(count))
    assert "not source" not in resolved
