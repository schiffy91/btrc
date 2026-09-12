"""Explicit, immutable package ownership across compiler invocations."""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.frontend.packages import (
    IncludeResolutionError,
    PackageUniverse,
    ResolvedPackages,
)
from src.compiler.python.frontend.stage import FrontendStage


@pytest.fixture(params=["reference", "selfhost"])
def package_compile(request):
    binary = request.getfixturevalue("immutable_btrcc") if request.param == "selfhost" else None

    def compile_source(path, *, target="macos-arm64"):
        if binary is None:
            result = Compiler().compile(path.read_text(), str(path), CompilerOptions(use_cache=False, target=target))
            diagnostic = str(result.failure) + "\n" + "\n".join(item.message for item in result.diagnostics)
            return result.successful, diagnostic, result.c_source or ""
        result = subprocess.run(
            [str(binary), "--no-stdlib", "--target", target, str(path)],
            env={**os.environ, "BTRC_HOME": str(Path(__file__).resolve().parents[2])},
            capture_output=True,
            text=True,
            timeout=90,
        )
        return result.returncode == 0, result.stderr, result.stdout

    return compile_source


def _export_project(tmp_path, exports='["GUI"]'):
    provider = tmp_path / "widgets"
    application = tmp_path / "app"
    (provider / "src").mkdir(parents=True)
    (application / "src").mkdir(parents=True)
    (provider / "btrc.toml").write_text(f'manifest-version = 1\n[package]\nname = "widgets"\nexports = {exports}\n')
    (provider / "src/Internal.btrc").write_text("int hiddenValue() { return 42; }\n")
    (provider / "src/GUI.btrc").write_text("import ./Internal.btrc;\nint publicValue() { return hiddenValue(); }\n")
    (application / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "application"\n[dependencies]\nwidgets = { path = "../widgets" }\n'
    )
    return application / "src/Main.btrc", provider


def test_exported_module_can_use_private_implementation(tmp_path, package_compile):
    source, _ = _export_project(tmp_path)
    source.write_text("import widgets.GUI;\nint main() { return publicValue() == 42 ? 0 : 1; }\n")
    successful, diagnostic, emitted = package_compile(source)
    assert successful, diagnostic
    assert "hiddenValue" in emitted


@pytest.mark.parametrize(
    "target, expected", [("macos-arm64", 11), ("macos-x86_64", 44), ("linux-x86_64", 22), ("windows-arm64", 33)]
)
def test_source_provider_selection_uses_compilation_target(tmp_path, package_compile, target, expected):
    source, provider = _export_project(tmp_path)
    manifest = provider / "btrc.toml"
    declarations = []
    implementations = [
        ("MacOS", "macos", "aarch64", 11),
        ("MacOSIntel", "macos", "x86_64", 44),
        ("Linux", "linux", "", 22),
        ("Windows", "windows", "", 33),
    ]
    for name, operating_system, architecture, value in implementations:
        (provider / f"src/{name}.btrc").write_text(f"int providerValue() {{ return {value}; }}\n")
        declarations.append(
            f'[[package.providers]]\nmodule = "GUI"\nimplementation = "{name}"\nos = ["{operating_system}"]\n'
            + (f'arch = ["{architecture}"]\n' if architecture else "")
        )
    manifest.write_text(manifest.read_text() + "\n".join(declarations))
    (provider / "src/GUI.btrc").write_text("int publicValue() { return providerValue(); }\n")
    source.write_text(f"import widgets.GUI;\nint main() {{ return publicValue() == {expected} ? 0 : 1; }}\n")
    successful, diagnostic, emitted = package_compile(source, target=target)
    assert successful, diagnostic
    generated = tmp_path / "Provider.c"
    executable = tmp_path / "Provider"
    generated.write_text(emitted)
    built = subprocess.run(
        ["cc", "-std=c11", "-pedantic-errors", str(generated), "-o", str(executable), "-lm", "-lpthread"],
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    for name, _, _, value in implementations:
        if value != expected:
            (provider / f"src/{name}.btrc").write_text("This unfinished provider is not valid BTRC.\n")
    successful, diagnostic, _ = package_compile(source, target=target)
    assert successful, diagnostic
    source.write_text("import widgets.GUI;\nimport widgets.MacOS;\nint main() { return 0; }\n")
    successful, diagnostic, _ = package_compile(source, target=target)
    assert not successful and "private to package" in diagnostic


def test_source_provider_applies_to_compilation_entrypoint(tmp_path, package_compile):
    _, provider = _export_project(tmp_path)
    (provider / "src/MacOS.btrc").write_text("int providerValue() { return 42; }\n")
    source = provider / "src/GUI.btrc"
    source.write_text("int main() { return providerValue() == 42 ? 0 : 1; }\n")
    manifest = provider / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + '[[package.providers]]\nmodule = "GUI"\nimplementation = "MacOS"\nos = ["macos"]\n'
    )
    successful, diagnostic, _ = package_compile(source)
    assert successful, diagnostic


@pytest.mark.parametrize("mode", ["missing", "overlap", "unknown", "escape", "self", "inactive"])
def test_source_provider_validation_is_fail_closed(tmp_path, package_compile, mode):
    source, provider = _export_project(tmp_path)
    (provider / "src/GUI.btrc").write_text("int publicValue() { return providerValue(); }\n")
    (provider / "src/MacOS.btrc").write_text("int providerValue() { return 42; }\n")
    source.write_text("import widgets.GUI;\nint main() { return publicValue(); }\n")
    implementation = "Absent" if mode == "missing" else "GUI" if mode == "self" else "MacOS"
    declaration = f'[[package.providers]]\nmodule = "GUI"\nimplementation = "{implementation}"\n'
    if mode == "inactive":
        declaration += 'os = ["linux"]\n'
    elif mode == "overlap":
        declaration += 'os = ["macos"]\n' + declaration
    elif mode == "unknown":
        declaration += 'command = "ignored"\n'
    elif mode == "escape":
        (provider / "src/MacOS.btrc").unlink()
        (provider / "src/MacOS.btrc").symlink_to(source)
    manifest = provider / "btrc.toml"
    manifest.write_text(manifest.read_text() + declaration)
    successful, diagnostic, _ = package_compile(source)
    assert not successful
    expected = {
        "missing": "unknown module",
        "overlap": "overlaps",
        "unknown": "unexpected",
        "escape": "escapes package root",
        "self": "own module",
        "inactive": "no provider",
    }
    assert expected[mode] in diagnostic


@pytest.mark.parametrize(
    "route", ["package", "relative", "include", "glob", "symlink", "extensionless", "already-loaded", "loose", "nested"]
)
def test_private_module_cannot_be_imported_across_package_boundary(tmp_path, package_compile, route):
    source, provider = _export_project(tmp_path)
    imports = {
        "package": "import widgets.Internal;",
        "relative": "import ../../widgets/src/Internal.btrc;",
        "include": '#include "../../widgets/src/Internal.btrc"',
        "glob": "import ../../widgets/src/*;",
        "symlink": "import ./Alias.btrc;",
        "extensionless": 'import "./Alias";',
        "already-loaded": "import widgets.GUI;\nimport widgets.Internal;",
        "loose": "import ../widgets/src/Internal.btrc;",
        "nested": "import ../src/Internal.btrc;",
    }
    if route in {"symlink", "extensionless"}:
        (source.parent / ("Alias.btrc" if route == "symlink" else "Alias")).symlink_to(provider / "src/Internal.btrc")
    elif route == "loose":
        source = tmp_path / "loose/Main.btrc"
        source.parent.mkdir()
    elif route == "nested":
        source = provider / "nested/Main.btrc"
        source.parent.mkdir()
        (source.parent / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "nested"\n')
    source.write_text(imports[route] + "\nint main() { return 0; }\n")
    successful, diagnostic, emitted = package_compile(source)
    assert not successful
    assert "private to package 'widgets'" in diagnostic
    assert emitted == ""


@pytest.mark.parametrize(
    "exports,diagnostic",
    [
        ('"GUI"', "array of strings"),
        ("[1]", "array of strings"),
        ('["GUI", "GUI"]', "duplicate"),
        ('["../Internal"]', "invalid module"),
        ('["Missing"]', "unknown module"),
        ("[]", "private to package"),
    ],
)
def test_package_exports_fail_closed(tmp_path, package_compile, exports, diagnostic):
    source, _ = _export_project(tmp_path, exports)
    source.write_text("import widgets.GUI;\nint main() { return 0; }\n")
    successful, message, _ = package_compile(source)
    assert not successful
    assert diagnostic in message


def test_exported_module_cannot_escape_package_via_symlink(tmp_path, package_compile):
    source, provider = _export_project(tmp_path, '["Escaped"]')
    outside = tmp_path / "Outside.btrc"
    outside.write_text("int outsideValue() { return 3; }\n")
    (provider / "src/Escaped.btrc").symlink_to(outside)
    source.write_text("import widgets.Escaped;\nint main() { return 0; }\n")
    successful, diagnostic, _ = package_compile(source)
    assert not successful
    assert "escapes package root" in diagnostic


def test_private_module_alias_to_external_source_stays_private(tmp_path, package_compile):
    source, provider = _export_project(tmp_path)
    outside = tmp_path / "Outside.btrc"
    outside.write_text("int outsideValue() { return 3; }\n")
    (provider / "src/PrivateAlias.btrc").symlink_to(outside)
    source.write_text("import widgets.PrivateAlias;\nint main() { return 0; }\n")
    successful, diagnostic, _ = package_compile(source)
    assert not successful
    assert "private to package 'widgets'" in diagnostic


def test_public_import_through_package_directory_alias_keeps_internal_access(tmp_path, package_compile):
    source, provider = _export_project(tmp_path)
    (tmp_path / "LinkedWidgets").symlink_to(provider, target_is_directory=True)
    source.write_text("import ../../LinkedWidgets/src/GUI.btrc;\nint main() { return publicValue() == 42 ? 0 : 1; }\n")
    successful, diagnostic, _ = package_compile(source)
    assert successful, diagnostic


@pytest.mark.parametrize(
    "directive", ["import ./LinkedSub/../Internal.btrc;", '#include "./LinkedSub/../Internal.btrc"']
)
def test_private_import_checks_symlinks_before_parent_traversal(tmp_path, package_compile, directive):
    source, provider = _export_project(tmp_path)
    (provider / "src/Sub").mkdir()
    (source.parent / "LinkedSub").symlink_to(provider / "src/Sub", target_is_directory=True)
    source.write_text(directive + "\nint main() { return 0; }\n")
    successful, diagnostic, _ = package_compile(source)
    assert not successful
    assert "private to package 'widgets'" in diagnostic


def _project(root: Path, marker: str) -> tuple[Path, str]:
    dependency = root / f"dependency-{marker}"
    (dependency / "src").mkdir(parents=True)
    (dependency / "src" / "dep.btrc").write_text(f"class Dep{marker.title()} {{}}\n")

    application = root / f"application-{marker}"
    application.mkdir()
    (application / "btrc.toml").write_text(f'[dependencies]\ndep = {{ path = "../dependency-{marker}" }}\n')
    source_path = application / "Main.btrc"
    source = "import dep;\nint main() { return 0; }\n"
    source_path.write_text(source)
    return source_path, source


def test_resolved_packages_are_deeply_immutable(tmp_path):
    entries = {"dep": {"path": str(tmp_path / "dependency")}}
    packages = ResolvedPackages(str(tmp_path / "btrc.toml"), entries)
    entries["dep"]["path"] = "/mutated-after-construction"

    assert packages.entries["dep"]["path"] == str(tmp_path / "dependency")
    with pytest.raises(TypeError):
        packages.entries["other"] = {"path": "/other"}
    with pytest.raises(TypeError):
        packages.entries["dep"]["path"] = "/other"


def test_one_source_resolver_isolates_concurrent_projects(tmp_path):
    left_path, left_source = _project(tmp_path, "left")
    right_path, right_source = _project(tmp_path, "right")
    ready = Barrier(2)

    class CoordinatedPackageUniverse(PackageUniverse):
        def resolve_for(self, input_path: str, *, refresh: bool = False):
            packages = super().resolve_for(input_path, refresh=refresh)
            ready.wait(timeout=10)
            return packages

    resolver = FrontendStage(package_universe=CoordinatedPackageUniverse()).resolver

    def resolve(path: Path, source: str) -> str:
        return resolver.resolve_includes(
            source,
            str(path),
            exit_on_error=False,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        left = executor.submit(resolve, left_path, left_source)
        right = executor.submit(resolve, right_path, right_source)
        left_result = left.result(timeout=20)
        right_result = right.result(timeout=20)

    assert "class DepLeft" in left_result
    assert "DepRight" not in left_result
    assert "class DepRight" in right_result
    assert "DepLeft" not in right_result


def test_previous_project_cannot_leak_into_no_manifest_resolution(tmp_path):
    project_path, project_source = _project(tmp_path, "owned")
    resolver = FrontendStage().resolver

    resolved = resolver.resolve_includes(
        project_source,
        str(project_path),
        exit_on_error=False,
    )
    assert "class DepOwned" in resolved

    loose = tmp_path / "loose" / "Main.btrc"
    loose.parent.mkdir()
    with pytest.raises(IncludeResolutionError, match="not found"):
        resolver.resolve_includes(
            project_source,
            str(loose),
            exit_on_error=False,
        )


def test_failed_resolution_cannot_affect_concurrent_success(tmp_path):
    success_path, success_source = _project(tmp_path, "success")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "btrc.toml").write_text('[dependencies]\nbad = { version = "unsupported" }\n')
    broken_path = broken / "Main.btrc"
    broken_source = "import bad;\nint main() { return 0; }\n"
    entered = Barrier(2)

    class CoordinatedPackageUniverse(PackageUniverse):
        def resolve_for(self, input_path: str, *, refresh: bool = False):
            entered.wait(timeout=10)
            return super().resolve_for(input_path, refresh=refresh)

    resolver = FrontendStage(package_universe=CoordinatedPackageUniverse()).resolver

    def resolve(path: Path, source: str) -> str:
        return resolver.resolve_includes(
            source,
            str(path),
            exit_on_error=False,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        failed = executor.submit(resolve, broken_path, broken_source)
        successful = executor.submit(resolve, success_path, success_source)
        with pytest.raises(IncludeResolutionError, match="package resolution failed"):
            failed.result(timeout=20)
        success = successful.result(timeout=20)

    assert "class DepSuccess" in success
