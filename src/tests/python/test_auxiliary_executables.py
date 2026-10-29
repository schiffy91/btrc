"""Target and reachability selection of executable entries in native plans."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.frontend.sources import StdlibRepository
from src.compiler.python.frontend.stage import FrontendStage
from src.tests.process_limits import TRANSPILE_TIMEOUT

REPO = Path(__file__).resolve().parents[3]
HELPER = "__btrc_windows_supervisor_image_verify"


def compiler_environment(library: Path | None = None) -> dict[str, str]:
    home = REPO / "src"
    if library is not None:
        home = library.parent
        language = home / "language"
        language.mkdir(exist_ok=True)
        shutil.copy2(REPO / "src/language/grammar.ebnf", language / "grammar.ebnf")
        for module in (REPO / "src/stdlib").glob("*.btrc"):
            shutil.copy2(module, library / module.name)
    return {**os.environ, "BTRC_HOME": str(home)}


def package(root: Path, declaration: str = "") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Leaf.btrc").write_text("int main() { return 0; }\n")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "AuxiliaryTest"\n'
        '[[native.auxiliary-executables]]\npath = "Leaf.btrc"\n'
        'kind = "windows-daemon-supervisor"\nprotocol = 1\nos = ["windows"]\n'
        f'requires = ["{HELPER}"]\n{declaration}'
    )
    return root / "Main.btrc"


def frontend_command(frontend, request):
    if frontend == "reference":
        return [sys.executable, "-m", "src.compiler.python.main"]
    return [str(request.getfixturevalue("immutable_btrcc"))]


def compile_plan(source: Path, frontend: str, target: str, request, *, module_units: bool = False):
    prefix = str(source.parent / f"{frontend}-units") if module_units else None
    library = source.parent / "data/stdlib"
    environment = compiler_environment(library if library.is_dir() else None)
    compiler = (
        Compiler(CompilationPipeline(frontend=FrontendStage(StdlibRepository(directory=str(library)))))
        if library.is_dir()
        else Compiler()
    )
    if frontend == "reference":
        result = compiler.compile(
            source.read_text(),
            str(source),
            CompilerOptions(
                include_stdlib=False,
                use_cache=False,
                use_ast_cache=False,
                target=target,
                module_units=module_units,
                units_prefix=prefix,
            ),
        )
        assert result.successful, (result.failure, result.diagnostics)
        return result.native_plan.as_dict()
    plan = source.parent / "selfhost-plan.json"
    result = subprocess.run(
        [
            str(request.getfixturevalue("immutable_btrcc")),
            str(source),
            "--no-stdlib",
            "--no-cache",
            "--target",
            target,
            "--emit-link-plan",
            str(plan),
            "-o",
            str(source.with_suffix(".c")),
            *(["--module-units", "--emit-units", prefix] if module_units else []),
        ],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(plan.read_text())


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("target", ["windows-x86_64", "windows-aarch64", "linux-x86_64"])
@pytest.mark.parametrize("retained", [False, True])
@pytest.mark.parametrize("module_units", [False, True])
def test_auxiliary_follows_retained_runtime_capability(frontend, target, retained, module_units, request, tmp_path):
    source = package(tmp_path)
    library = tmp_path / "data/stdlib"
    library.mkdir(parents=True)
    (library / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "btrc_stdlib_runtime"\nexports = ["DaemonProbe"]\n'
    )
    (library / "DaemonProbe.btrc").write_text(
        f"class DaemonProbe {{ class int start() {{ return {HELPER}(NULL, NULL); }} }}\n"
    )
    source.write_text(
        "import Library.DaemonProbe;\n"
        + ("int main() { return DaemonProbe.start(); }\n" if retained else "int main() { return 0; }\n")
    )
    plan = compile_plan(source, frontend, target, request, module_units=module_units)
    if retained and target.startswith("windows-"):
        leaf = tmp_path / "Leaf.btrc"
        assert plan["auxiliary-executables"] == [
            {
                "abi": target,
                "kind": "windows-daemon-supervisor",
                "package": "AuxiliaryTest",
                "path": str(leaf),
                "protocol": 1,
                "sha256": hashlib.sha256(leaf.read_bytes()).hexdigest(),
            }
        ]
    else:
        assert "auxiliary-executables" not in plan


def test_entry_is_excluded_from_discovery_symbols_and_editor_index(tmp_path):
    from src.devex.lsp.workspace.workspace import Workspace
    from tools.compiler_codegen.builtins import BuiltinStdlibScanner
    from tools.compiler_codegen.hosted_abi import TargetManifest

    package(tmp_path)
    (tmp_path / "Public.btrc").write_text("class Public { class int value() { return 1; } }\n")
    (tmp_path / "Leaf.btrc").write_text(
        "class ExecutableOnly { class int hidden() { return 2; } }\nint main() { return 0; }\n"
    )
    library = StdlibRepository(directory=str(tmp_path))
    assert library.discover_files() == ["Public.btrc"]
    assert "ExecutableOnly" not in library.render_symbol_index()
    catalog = BuiltinStdlibScanner(tmp_path, TargetManifest.load_repository(REPO)).scan()
    assert "ExecutableOnly" not in {item.name for item in (*catalog.collections, *catalog.static_classes)}
    units = Workspace(stdlib=library).stdlib_units()
    assert {Path(unit.path).name for unit in units} == {"Public.btrc"}


def test_editor_catalog_excludes_nested_executable_without_a_root_manifest(tmp_path):
    from tools.compiler_codegen.builtins import BuiltinStdlibScanner
    from tools.compiler_codegen.hosted_abi import TargetManifest

    nested = tmp_path / "Nested"
    package(nested)
    (nested / "Leaf.btrc").write_text("class ExecutableOnly { class int hidden() { return 2; } }\n")
    (nested / "Public.btrc").write_text("class Public { class int value() { return 1; } }\n")
    catalog = BuiltinStdlibScanner(tmp_path, TargetManifest.load_repository(REPO)).scan()
    names = {item.name for item in (*catalog.collections, *catalog.static_classes)}
    assert "Public" in names and "ExecutableOnly" not in names


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_executable_source_is_not_parsed_during_stdlib_discovery(frontend, request, tmp_path):
    library = tmp_path / "data/stdlib"
    package(library)
    manifest = library / "btrc.toml"
    manifest.write_text(manifest.read_text().replace('name = "AuxiliaryTest"', 'name = "btrc_stdlib_runtime"'))
    (library / "Leaf.btrc").write_text("this executable source is deliberately invalid {\n")
    (library / "Public.btrc").write_text("class Public { class int value() { return 0; } }\n")
    source = tmp_path / "Main.btrc"
    source.write_text("import Library.Public;\nint main() { return Public.value(); }\n")
    plan = compile_plan(source, frontend, "windows-x86_64", request)
    assert "auxiliary-executables" not in plan


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("library_import", [False, True])
def test_executable_entry_is_not_importable(frontend, library_import, request, tmp_path):
    library = tmp_path / "data/stdlib"
    source = package(library if library_import else tmp_path)
    if library_import:
        source = tmp_path / "Main.btrc"
    source.write_text(
        ("import Library.Leaf;\n" if library_import else "import ./Leaf.btrc;\n") + "int main() { return 0; }\n"
    )
    if frontend == "reference":
        frontend_stage = FrontendStage(StdlibRepository(directory=str(library))) if library_import else FrontendStage()
        result = Compiler(CompilationPipeline(frontend=frontend_stage)).compile(
            source.read_text(), str(source), CompilerOptions(include_stdlib=False, use_cache=False)
        )
        assert not result.successful
        diagnostic = result.failure.message
    else:
        result = subprocess.run(
            [str(request.getfixturevalue("immutable_btrcc")), str(source), "--no-stdlib", "--no-cache"],
            cwd=REPO,
            env=compiler_environment(library if library_import else None),
            capture_output=True,
            text=True,
            timeout=TRANSPILE_TIMEOUT,
        )
        assert result.returncode != 0
        diagnostic = result.stderr
    assert "executable entry" in diagnostic and "cannot be imported" in diagnostic, diagnostic


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize(
    "old,new,message",
    [
        ("protocol = 1", "protocol = true", "protocol"),
        ("protocol = 1", "protocol = 2", "protocol"),
        ('os = ["windows"]', 'os = ["linux"]', "select"),
        ('kind = "windows-daemon-supervisor"', 'kind = "arbitrary-command"', "kind"),
        (f'requires = ["{HELPER}"]', 'requires = ["not_a_runtime_helper"]', "runtime helper"),
        (f'requires = ["{HELPER}"]', f'requires = ["{HELPER}", "{HELPER}"]', "requires"),
        ('path = "Leaf.btrc"', 'path = "Missing.btrc"', "file"),
        ('name = "AuxiliaryTest"', 'name = "AuxiliaryTest"\nexports = ["Leaf"]', "export an executable"),
    ],
)
def test_invalid_auxiliary_declarations_are_refused(tmp_path, old, new, message, frontend, request):
    from src.compiler.python.frontend.packages import PackageManifestReader, PackageManifestValidator

    source = package(tmp_path)
    source.write_text("int main() { return 0; }\n")
    path = tmp_path / "btrc.toml"
    path.write_text(path.read_text().replace(old, new))
    if frontend == "reference":
        validator = PackageManifestValidator()
        document = PackageManifestReader().read(str(path))
        with pytest.raises(ValueError, match=message):
            name = validator.validate_identity(document, str(path))
            validator.native(document, str(tmp_path), name, str(path))
    else:
        result = subprocess.run(
            [*frontend_command(frontend, request), str(source), "--no-stdlib", "--no-cache"],
            cwd=REPO,
            env=compiler_environment(),
            capture_output=True,
            text=True,
            timeout=TRANSPILE_TIMEOUT,
        )
        assert result.returncode != 0 and message in result.stderr, result.stderr


def test_cached_auxiliary_plan_revalidates_source_digest(tmp_path):
    from dataclasses import replace

    from src.compiler.python.frontend.packages import PackageUniverse

    source = package(tmp_path)
    source.write_text("int main() { return 0; }\n")
    resolved = PackageUniverse().resolve_for(str(source), target="windows-x86_64")
    plan = replace(resolved.native_plan, retained_runtime_helpers=(HELPER,))
    encoded = plan.canonical_json()
    assert resolved.native_plan.with_cached_artifacts(encoded, 0) == plan
    leaf = tmp_path / "Leaf.btrc"
    leaf.write_text("int main() { return 2; }\n")
    assert resolved.native_plan.with_cached_artifacts(encoded, 0) is None
    assert plan.canonical_json() != encoded


def test_auxiliary_entry_cannot_be_owned_by_a_nested_package(tmp_path):
    from src.compiler.python.frontend.packages import PackageManifestReader, PackageManifestValidator

    package(tmp_path)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "Nested"\n')
    (nested / "Leaf.btrc").write_text("int main() { return 0; }\n")
    path = tmp_path / "btrc.toml"
    path.write_text(path.read_text().replace('path = "Leaf.btrc"', 'path = "nested/Leaf.btrc"'))
    with pytest.raises(ValueError, match="declaring package"):
        PackageManifestValidator().native(
            PackageManifestReader().read(str(path)), str(tmp_path), "AuxiliaryTest", str(path)
        )


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("encoded", [b"int main() { return 0; }\r\n", b"\xef\xbb\xbfint main() { return 0; }\n"])
def test_auxiliary_source_digest_preserves_bytes(frontend, encoded, request, tmp_path):
    source = package(tmp_path)
    (tmp_path / "Leaf.btrc").write_bytes(encoded)
    source.write_text(f"int main() {{ return {HELPER}(NULL, NULL); }}\n")
    plan = compile_plan(source, frontend, "windows-x86_64", request)
    assert plan["auxiliary-executables"][0]["sha256"] == hashlib.sha256(encoded).hexdigest()


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("alias", [False, True])
def test_compiler_output_cannot_replace_auxiliary_source(frontend, alias, request, tmp_path):
    source = package(tmp_path)
    source.write_text(f"int main() {{ return {HELPER}(NULL, NULL); }}\n")
    leaf = tmp_path / "Leaf.btrc"
    before = leaf.read_bytes()
    output = leaf
    if alias:
        output = tmp_path / "alias.c"
        os.link(leaf, output)
    result = subprocess.run(
        [
            *frontend_command(frontend, request),
            str(source),
            "--no-stdlib",
            "--no-cache",
            "--target",
            "windows-x86_64",
            "-o",
            str(output),
        ],
        cwd=REPO,
        env=compiler_environment(),
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert result.returncode != 0 and "same file as a source" in result.stderr, result.stderr
    assert leaf.read_bytes() == before and output.read_bytes() == before


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_cached_compilation_rechecks_auxiliary_bytes(frontend, request, tmp_path):
    source = package(tmp_path)
    source.write_text(f"int main() {{ return {HELPER}(NULL, NULL); }}\n")
    leaf = tmp_path / "Leaf.btrc"
    output = tmp_path / "program.c"
    plan = tmp_path / "plan.json"
    environment = {
        **compiler_environment(),
        "BTRC_CACHE_DIR": str(tmp_path / "cache"),
        "BTRC_STATE_DIR": str(tmp_path / "state"),
        "BTRC_TIMING": "1",
    }
    for changed in (False, False, True, False):
        if changed:
            leaf.write_bytes(b"int main() { return 2; }\r\n")
        result = subprocess.run(
            [
                *frontend_command(frontend, request),
                str(source),
                "--no-stdlib",
                "--target",
                "windows-x86_64",
                "-o",
                str(output),
                "--emit-link-plan",
                str(plan),
            ],
            cwd=REPO,
            env=environment,
            capture_output=True,
            text=True,
            timeout=TRANSPILE_TIMEOUT,
        )
        assert result.returncode == 0, result.stderr
        assert (
            json.loads(plan.read_text())["auxiliary-executables"][0]["sha256"]
            == hashlib.sha256(leaf.read_bytes()).hexdigest()
        )
    assert "artifact-hit=" in result.stderr, result.stderr
