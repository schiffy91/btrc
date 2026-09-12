"""Versioned recursive packages and native link-plan contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python import Compiler, CompilerOptions
from src.compiler.python.frontend.packages import (
    NATIVE_LINK_PLAN_SCHEMA,
    PACKAGE_GRAPH_LOCK_SCHEMA,
    IncludeResolutionError,
    LockfileError,
    NativeLinkPlan,
    PackageNode,
    PackageTarget,
    PackageUniverse,
)
from src.compiler.python.frontend.sources import SourceDependencyGraph
from src.compiler.python.main import main as compiler_main

REPO = Path(__file__).resolve().parents[3]
EXAMPLE = REPO / "examples" / "native-package"


def test_stdlib_manifest_selects_only_loaded_provider_units():
    library = REPO / "src/stdlib"
    plan = NativeLinkPlan.empty(PackageTarget.parse("macos-aarch64"))
    assert plan.with_stdlib(str(library), [str(library / "Strings.btrc")]) == plan
    selected = plan.with_stdlib(
        str(library),
        [str(library / "Audio/MacOS/CoreAudioDevice.btrc"), str(library / "MacOSEncodedImageDecoder.btrc")],
    )
    payload = selected.as_dict()
    assert payload["units"] == []
    assert [item["name"] for item in payload["frameworks"]] == [
        "AudioToolbox",
        "CoreAudio",
        "CoreFoundation",
        "CoreGraphics",
        "ImageIO",
    ]
    assert len(selected.packages) == 1 and len(selected.packages[0].manifest_hash) == 64
    assert [Path(binding.module).name for binding in selected.bindings] == [
        "CoreAudioDevice.btrc",
        "MacOSEncodedImageDecoder.btrc",
    ]
    assert selected.bindings[0].read_only_borrows == ("CFStringCreateWithCString.cStr",)
    assert selected.bindings[1].read_only_borrows == ()
    assert (
        selected.with_stdlib(
            str(library),
            [str(library / "Audio/MacOS/CoreAudioDevice.btrc"), str(library / "MacOSEncodedImageDecoder.btrc")],
        )
        == selected
    )


def test_stdlib_manifest_rejects_foreign_package_identity(tmp_path):
    library = REPO / "src/stdlib"
    foreign = PackageNode("btrc_stdlib_runtime", str(tmp_path), {}, {"path": str(tmp_path)}, "")
    plan = NativeLinkPlan(PackageTarget.parse("macos-aarch64"), (foreign,))
    with pytest.raises(IncludeResolutionError, match="reserved for compiler-owned"):
        plan.with_stdlib(str(library), [str(library / "Audio/MacOS/CoreAudioDevice.btrc")])


def _manifest(path: Path, name: str, dependencies: str = "", native: str = "") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "btrc.toml").write_text(
        f'manifest-version = 1\n\n[package]\nname = "{name}"\n{dependencies}{native}',
        encoding="utf-8",
    )


def _compile(source: Path):
    return Compiler().compile(
        source.read_text(encoding="utf-8"),
        str(source),
        CompilerOptions(include_stdlib=False, use_cache=False, target="linux-x86_64"),
    )


def _binding_package(root: Path, binding: str) -> Path:
    _manifest(root, "bindings", native=binding)
    (root / "src").mkdir(exist_ok=True)
    (root / "src/Api.btrc").write_text("// Native wrapper module.\n", encoding="utf-8")
    (root / "Native.h").write_text("long measure(const char *text);\n", encoding="utf-8")
    source = root / "src/Main.btrc"
    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    return source


_BINDING = (
    '\n[[native.bindings]]\nmodule = "Api"\nheader = "Native.h"\n'
    'language = "c"\nstandard = "c11"\nsymbols = ["measure"]\n'
)

_RESOURCE_BINDING = _BINDING.replace(
    '["measure"]', '["WidgetRef", "WidgetCreate", "WidgetRead", "WidgetRetain", "WidgetRelease"]'
) + (
    'owned-results = ["WidgetCreate"]\nborrowed-parameters = ["WidgetRead.widget"]\n'
    '[native.bindings.resources.WidgetRef]\nownership = "reference-counted"\n'
    'retain = "WidgetRetain"\nrelease = "WidgetRelease"\n'
)


@pytest.mark.parametrize("shared_hooks", [False, True])
def test_native_resource_binding_preserves_ownership_facts(tmp_path, shared_hooks):
    declaration = _RESOURCE_BINDING
    if shared_hooks:
        declaration = declaration.replace('["WidgetRef",', '["OtherRef", "WidgetRef",')
        declaration += (
            '[native.bindings.resources.OtherRef]\nownership = "reference-counted"\n'
            'retain = "WidgetRetain"\nrelease = "WidgetRelease"\n'
        )
    source = _binding_package(tmp_path, declaration)
    resolved = PackageUniverse().resolve_for(str(source), target="macos-aarch64")
    [binding] = resolved.native_plan.for_sources([str(tmp_path / "src/Api.btrc")]).bindings
    resource = binding.resources[-1]
    assert len(binding.resources) == (2 if shared_hooks else 1)
    assert all(item.retain == "WidgetRetain" and item.release == "WidgetRelease" for item in binding.resources)
    assert (resource.name, resource.ownership, resource.retain, resource.release) == (
        "WidgetRef",
        "reference-counted",
        "WidgetRetain",
        "WidgetRelease",
    )
    assert binding.owned_results == ("WidgetCreate",)
    assert binding.borrowed_parameters == ("WidgetRead.widget",)


@pytest.mark.parametrize(
    ("before", "after", "message"),
    [
        ('ownership = "reference-counted"', 'ownership = "unique"', "reference-counted"),
        ('retain = "WidgetRetain"', 'retain = "Unknown"', "selected functions"),
        ('release = "WidgetRelease"', 'release = "WidgetRetain"', "distinct"),
        ('release = "WidgetRelease"', 'release = "WidgetRelease"\ncleanup = "code"', "unexpected field"),
        ('owned-results = ["WidgetCreate"]', 'owned-results = ["WidgetRelease"]', "reserved"),
        ('owned-results = ["WidgetCreate"]', 'owned-results = ["WidgetCreate", "WidgetCreate"]', "duplicate"),
        ('borrowed-parameters = ["WidgetRead.widget"]', 'borrowed-parameters = ["WidgetRead"]', "function.parameter"),
        ("resources.WidgetRef", "resources.Other", "selected typedefs"),
    ],
)
def test_native_resource_binding_rejects_invalid_facts(tmp_path, before, after, message):
    source = _binding_package(tmp_path, _RESOURCE_BINDING.replace(before, after))
    with pytest.raises(IncludeResolutionError, match=message):
        PackageUniverse().resolve_for(str(source), target="macos-aarch64")


def test_native_binding_is_owned_by_loaded_module_and_target(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BTRC_NATIVE_HEADER_READER", raising=False)
    source = _binding_package(tmp_path, _BINDING + 'os = ["macos"]\n')
    resolved = PackageUniverse().resolve_for(str(source), target="macos-aarch64")
    assert resolved.native_plan.for_sources([str(source)]).bindings == ()
    plan = resolved.native_plan.for_sources([str(source), str(tmp_path / "src/Api.btrc")])
    [binding] = plan.bindings
    assert binding.package == "bindings"
    assert binding.module == str(tmp_path / "src/Api.btrc")
    assert binding.header == str(tmp_path / "Native.h")
    assert binding.symbols == ("measure",)
    assert (binding.language, binding.standard) == ("c", "c11")
    assert "bindings" not in plan.as_dict(), "semantic imports are not linker schema-1 records"
    linux = PackageUniverse().resolve_for(str(source), target="linux-x86_64")
    assert linux.native_plan.for_sources([binding.module]).bindings == ()
    source.write_text("import ./Api.btrc;\nint main() { return 0; }\n", encoding="utf-8")
    assert _compile(source).successful, "inactive native bindings must not block unrelated targets"
    macos = Compiler().compile(
        source.read_text(), str(source), CompilerOptions(include_stdlib=False, use_cache=False, target="macos-aarch64")
    )
    assert not macos.successful
    assert "requires BTRC_NATIVE_HEADER_READER" in macos.failure.message


@pytest.mark.parametrize(
    ("before", "after", "message"),
    [
        ('module = "Api"', 'module = "Missing"', "unknown module"),
        ('module = "Api"', 'module = "../Api"', "dotted module"),
        ('module = "Api"', 'module = ["Api"]', "dotted module"),
        ('header = "Native.h"', 'header = "Missing.h"', "does not name a file"),
        ('header = "Native.h"', 'header = "/Native.h"', "package-relative"),
        ('symbols = ["measure"]', "symbols = []", "non-empty array"),
        ('symbols = ["measure"]', 'symbols = "measure"', "non-empty array"),
        ('symbols = ["measure"]', 'symbols = ["measure", "measure"]', "duplicate value"),
        ('symbols = ["measure"]', 'symbols = ["ns::"]', "qualified native names"),
        ('symbols = ["measure"]', 'symbols = ["ns:::measure"]', "qualified native names"),
        ('language = "c"', 'language = "rust"', "language is unsupported"),
        ('language = "c"', "language = []", "language is unsupported"),
        ('standard = "c11"', 'standard = "c++17"', "standard is unsupported"),
        ('standard = "c11"', "standard = {}", "standard is unsupported"),
        ('header = "Native.h"', 'header = "Native.h"\ncflags = "-DGUESS_ABI"', "unexpected field"),
    ],
)
def test_native_binding_manifest_rejects_invalid_input(tmp_path: Path, before, after, message) -> None:
    source = _binding_package(tmp_path, _BINDING.replace(before, after))
    with pytest.raises(IncludeResolutionError, match=message):
        PackageUniverse().resolve_for(str(source), target="macos-aarch64")


def test_native_binding_header_cannot_escape_through_symlink(tmp_path: Path) -> None:
    root = tmp_path / "package"
    source = _binding_package(root, _BINDING.replace("Native.h", "Escape.h"))
    outside = tmp_path / "Outside.h"
    outside.write_text("int external(void);\n", encoding="utf-8")
    (root / "Escape.h").symlink_to(outside)
    with pytest.raises(IncludeResolutionError, match="escapes package root"):
        PackageUniverse().resolve_for(str(source), target="macos-aarch64")


def test_native_bindings_allow_disjoint_providers_not_ambiguous_exports(tmp_path: Path) -> None:
    source = _binding_package(tmp_path, _BINDING + 'os = ["macos"]\n' + _BINDING + 'os = ["linux"]\n')
    resolved = PackageUniverse().resolve_for(str(source), target="macos-aarch64")
    assert len(resolved.native_plan.for_sources([str(tmp_path / "src/Api.btrc")]).bindings) == 1
    _manifest(tmp_path, "bindings", native=_BINDING + 'arch = ["aarch64"]\n' + _BINDING)
    with pytest.raises(IncludeResolutionError, match="overlaps a native binding"):
        PackageUniverse().resolve_for(str(source), target="linux-x86_64")


def test_native_plan_is_a_loaded_module_projection(tmp_path: Path) -> None:
    app = tmp_path / "app"
    dependency = app / "packages" / "seams"
    (dependency / "src").mkdir(parents=True)
    (dependency / "native").mkdir()
    (dependency / "src/Direct.btrc").write_text("extern int direct_native();\n", encoding="utf-8")
    (dependency / "src/Primary.btrc").write_text(
        'import "./Secondary.btrc"\nextern int primary_native();\n',
        encoding="utf-8",
    )
    (dependency / "src/Secondary.btrc").write_text("extern int secondary_native();\n", encoding="utf-8")
    for name in ("Direct", "Primary", "Secondary"):
        (dependency / f"native/{name}.c").write_text(f"int {name.lower()}_native(void) {{ return 1; }}\n")
    (dependency / "native/Common.h").write_text("#pragma once\n", encoding="utf-8")
    _manifest(
        dependency,
        "seams",
        native=(
            '\n[[native.headers]]\npath = "native/Common.h"\n'
            '\n[[native.include-directories]]\npath = "native"\n'
            '\n[[native.defines]]\nname = "SEAMS_COMMON"\nvalue = "1"\n'
            '\n[[native.sources]]\npath = "native/Direct.c"\nlanguage = "c"\nstandard = "c11"\n'
            'modules = ["Direct"]\n'
            '\n[[native.sources]]\npath = "native/Primary.c"\nlanguage = "c"\nstandard = "c11"\n'
            'modules = ["Primary"]\n'
            '\n[[native.sources]]\npath = "native/Secondary.c"\nlanguage = "c"\nstandard = "c11"\n'
            'modules = ["Secondary"]\n'
            '\n[[native.pkg-config]]\nname = "direct-native"\nmodules = ["Direct"]\n'
        ),
    )
    _manifest(app, "app", '\n[dependencies]\nseams = { path = "packages/seams" }\n')
    source = app / "src/Main.btrc"
    source.parent.mkdir()

    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    pure = _compile(source)
    assert pure.successful, pure.failure
    assert pure.source_bundle is not None
    assert SourceDependencyGraph.canonical_file(str(source)) in {
        SourceDependencyGraph.canonical_file(path) for path in pure.source_bundle.graph.source_paths()
    }
    pure_plan = pure.native_plan.as_dict()
    assert [package["name"] for package in pure_plan["packages"]] == ["app"]
    for field in ("defines", "frameworks", "headers", "include-directories", "pkg-config", "units"):
        assert pure_plan[field] == []

    source.write_text("import seams.Direct\nint main() { return 0; }\n", encoding="utf-8")
    direct = _compile(source)
    assert direct.successful, direct.failure
    direct_plan = direct.native_plan.as_dict()
    assert [package["name"] for package in direct_plan["packages"]] == ["app", "seams"]
    assert direct_plan["packages"][0]["dependencies"] == {"seams": "seams"}
    assert [Path(unit["path"]).name for unit in direct_plan["units"]] == ["Direct.c"]
    assert [Path(header["path"]).name for header in direct_plan["headers"]] == ["Common.h"]
    assert direct_plan["defines"] == [{"name": "SEAMS_COMMON", "package": "seams", "value": "1"}]
    assert direct_plan["pkg-config"] == [{"name": "direct-native", "package": "seams"}]

    source.write_text("import seams.Primary\nint main() { return 0; }\n", encoding="utf-8")
    transitive = _compile(source)
    assert transitive.successful, transitive.failure
    transitive_plan = transitive.native_plan.as_dict()
    assert transitive_plan["packages"][0]["dependencies"] == {"seams": "seams"}
    assert [Path(unit["path"]).name for unit in transitive_plan["units"]] == ["Primary.c", "Secondary.c"]
    assert transitive_plan["pkg-config"] == []


def test_nested_package_sources_belong_only_to_the_longest_root(tmp_path: Path) -> None:
    app = tmp_path / "app"
    parent = app / "packages" / "parent"
    child = parent / "child"
    for package in (parent, child):
        (package / "src").mkdir(parents=True)
        (package / "native").mkdir()
    (parent / "native/Parent.c").write_text("int parent_native(void) { return 1; }\n")
    (child / "native/Child.c").write_text("int child_native(void) { return 1; }\n")
    (child / "src/Api.btrc").write_text("extern int child_native();\n", encoding="utf-8")
    _manifest(
        parent,
        "parent",
        native=('\n[[native.sources]]\npath = "native/Parent.c"\nlanguage = "c"\nstandard = "c11"\n'),
    )
    _manifest(
        child,
        "child",
        native=('\n[[native.sources]]\npath = "native/Child.c"\nlanguage = "c"\nstandard = "c11"\nmodules = ["Api"]\n'),
    )
    _manifest(
        app,
        "app",
        '\n[dependencies]\nparent = { path = "packages/parent" }\nchild = { path = "packages/parent/child" }\n',
    )
    source = app / "src/Main.btrc"
    source.parent.mkdir()
    source.write_text("import child.Api\nint main() { return 0; }\n", encoding="utf-8")

    result = _compile(source)

    assert result.successful, result.failure
    plan = result.native_plan.as_dict()
    assert [package["name"] for package in plan["packages"]] == ["app", "child"]
    assert plan["packages"][0]["dependencies"] == {"child": "child"}
    assert [Path(unit["path"]).name for unit in plan["units"]] == ["Child.c"]


@pytest.mark.parametrize(
    ("modules", "message"),
    [
        ("[]", "modules must not be empty"),
        ('["Direct", "Direct"]', "modules contains a duplicate value"),
        ('["bad..module"]', "contains invalid module"),
        ('["Missing"]', "names unknown module"),
    ],
)
def test_native_module_scopes_fail_closed(tmp_path: Path, modules: str, message: str) -> None:
    (tmp_path / "native").mkdir()
    (tmp_path / "native/Seam.c").write_text("int seam(void) { return 1; }\n")
    _manifest(
        tmp_path,
        "app",
        native=(
            f'\n[[native.sources]]\npath = "native/Seam.c"\nlanguage = "c"\nstandard = "c11"\nmodules = {modules}\n'
        ),
    )

    with pytest.raises(ValueError, match=message):
        PackageUniverse().resolve_manifest(str(tmp_path / "btrc.toml"), target="linux-x64")


def test_one_native_record_cannot_be_split_across_module_scopes(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "native").mkdir()
    for module in ("Direct", "Other"):
        (tmp_path / f"src/{module}.btrc").write_text("extern int seam();\n", encoding="utf-8")
    (tmp_path / "native/Seam.c").write_text("int seam(void) { return 1; }\n")
    declaration = '\n[[native.sources]]\npath = "native/Seam.c"\nlanguage = "c"\nstandard = "c11"\n'
    _manifest(
        tmp_path,
        "app",
        native=declaration + 'modules = ["Direct"]\n' + declaration + 'modules = ["Other"]\n',
    )

    with pytest.raises(ValueError, match="duplicates an earlier native declaration"):
        PackageUniverse().resolve_manifest(str(tmp_path / "btrc.toml"), target="linux-x64")


def _compile_plan(plan: dict, generated_c: Path, output: Path, temporary: Path) -> None:
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    cxx = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if cc is None or cxx is None:
        pytest.skip("native package proof needs C and C++ compilers")
    includes = [f"-I{entry['path']}" for entry in plan["include-directories"]]
    defines = [
        f"-D{entry['name']}={entry['value']}" if entry["value"] else f"-D{entry['name']}" for entry in plan["defines"]
    ]
    objects = []
    generated_object = temporary / "generated.o"
    subprocess.run(
        [
            cc,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            *includes,
            *defines,
            "-c",
            str(generated_c),
            "-o",
            str(generated_object),
        ],
        check=True,
    )
    objects.append(generated_object)
    compilers = {"c": cc, "c++": cxx, "objective-c": cc, "objective-c++": cxx}
    for index, unit in enumerate(plan["units"]):
        object_path = temporary / f"native-{index}.o"
        subprocess.run(
            [
                compilers[unit["language"]],
                f"-std={unit['standard']}",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                *includes,
                *defines,
                "-c",
                unit["path"],
                "-o",
                str(object_path),
            ],
            check=True,
        )
        objects.append(object_path)
    linker = cxx if plan["linker-language"] == "c++" else cc
    subprocess.run([linker, *(str(path) for path in objects), "-lm", "-o", str(output)], check=True)


def test_recursive_aliases_lock_and_native_plan_are_canonical() -> None:
    source = EXAMPLE / "src" / "Main.btrc"
    packages = PackageUniverse().resolve_for(str(source), target="linux-x64")

    assert packages.root_package == "native_app"
    assert sorted(packages.nodes) == ["leaf", "middle", "native_app"]
    middle = packages.paths_for_import("middle.Api", str(source))[0]
    assert packages.paths_for_import("leaf.Api", middle)[0].endswith("packages/leaf/src/Api.btrc")

    plan_text = packages.native_plan.canonical_json()
    assert plan_text == packages.native_plan.canonical_json()
    plan = json.loads(plan_text)
    assert plan["schema"] == NATIVE_LINK_PLAN_SCHEMA
    assert plan["target"] == {"arch": "x86_64", "os": "linux"}
    assert plan["linker-language"] == "c++"
    assert [(unit["package"], unit["language"]) for unit in plan["units"]] == [
        ("leaf", "c"),
        ("middle", "c++"),
    ]
    assert plan["frameworks"] == []
    assert plan["pkg-config"] == []

    lock = json.loads((EXAMPLE / "btrc.lock").read_text(encoding="utf-8"))
    assert lock["schema"] == PACKAGE_GRAPH_LOCK_SCHEMA
    assert lock["root"] == "native_app"
    assert [package["name"] for package in lock["packages"]] == ["leaf", "middle", "native_app"]
    assert lock["packages"][1]["dependencies"] == {"leaf": "leaf"}


def test_platform_predicates_cover_objc_objcxx_frameworks_and_pkg_config() -> None:
    source = EXAMPLE / "src" / "Main.btrc"
    darwin = PackageUniverse().resolve_for(str(source), target="macos-arm64").native_plan.as_dict()
    windows = PackageUniverse().resolve_for(str(source), target="windows-x64").native_plan.as_dict()

    assert [unit["language"] for unit in darwin["units"]] == ["c", "c++", "objective-c", "objective-c++"]
    assert darwin["frameworks"] == [{"name": "Foundation", "package": "middle"}]
    assert darwin["pkg-config"] == []
    assert windows["frameworks"] == []
    assert windows["pkg-config"] == [{"name": "native-package-proof", "package": "middle"}]


def test_same_native_name_with_disjoint_platform_predicates_is_not_duplicate(
    tmp_path: Path,
) -> None:
    native = (
        '\n[[native.pkg-config]]\nname = "platform-native"\nos = ["macos"]\n'
        '\n[[native.pkg-config]]\nname = "platform-native"\nos = ["linux"]\n'
    )
    _manifest(tmp_path, "app", native=native)

    darwin = PackageUniverse().resolve_manifest(str(tmp_path / "btrc.toml"), target="macos-arm64").native_plan.as_dict()
    linux = PackageUniverse().resolve_manifest(str(tmp_path / "btrc.toml"), target="linux-x64").native_plan.as_dict()

    expected = [{"name": "platform-native", "package": "app"}]
    assert darwin["pkg-config"] == expected
    assert linux["pkg-config"] == expected


def test_reference_compiler_result_plan_compiles_links_and_runs(tmp_path: Path) -> None:
    source = EXAMPLE / "src" / "Main.btrc"
    result = Compiler().compile(
        source.read_text(encoding="utf-8"),
        str(source),
        CompilerOptions(include_stdlib=False, use_cache=False, target="linux-x86_64"),
    )

    assert result.successful, result.failure
    assert result.c_source is not None
    generated = tmp_path / "program.c"
    generated.write_text(result.c_source, encoding="utf-8")
    executable = tmp_path / "program"
    _compile_plan(result.native_plan.as_dict(), generated, executable, tmp_path)
    completed = subprocess.run([str(executable)], capture_output=True, check=True, text=True)
    assert completed.stdout == "PASS: native package graph\n"


def test_cli_atomically_emits_plan_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = EXAMPLE / "src" / "Main.btrc"
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "btrcpy",
            str(source),
            "--no-stdlib",
            "--no-cache",
            "--target",
            "linux-x64",
            "--emit-link-plan",
            str(plan),
            "-o",
            str(generated),
        ],
    )

    assert compiler_main() == 0
    assert generated.is_file()
    payload = json.loads(plan.read_text(encoding="utf-8"))
    assert payload["schema"] == NATIVE_LINK_PLAN_SCHEMA
    assert payload["units"][1]["language"] == "c++"


@pytest.mark.parametrize(
    ("requested", "expected"),
    (
        ("linux-x86_64", {"arch": "x86_64", "os": "linux"}),
        ("linux-x64", {"arch": "x86_64", "os": "linux"}),
        ("macos-arm64", {"arch": "aarch64", "os": "macos"}),
        ("macos-x86_64", {"arch": "x86_64", "os": "macos"}),
        ("windows-x86_64", {"arch": "x86_64", "os": "windows"}),
    ),
)
@pytest.mark.parametrize(
    "manifest", (None, 'manifest-version = 1\n\n[package]\nname = "p"\n', '[package]\nname = "p"\n')
)
def test_requested_target_reaches_the_plan_without_a_native_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requested: str,
    expected: dict[str, str],
    manifest: str | None,
) -> None:
    """--target governs the plan even when nothing declares native sources.

    A source with no manifest, and a legacy manifest that predates the native
    section, both produce an empty plan. That plan still has a target, and it
    is the requested one -- inferring the host instead is invisible whenever
    the host happens to be the target, so this asks for every target rather
    than the one the test machine runs.
    """

    root = tmp_path / "package"
    root.mkdir()
    if manifest is not None:
        (root / "btrc.toml").write_text(manifest, encoding="utf-8")
    source = root / "Main.btrc"
    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    plan = tmp_path / "program.link.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "btrcpy",
            str(source),
            "--no-stdlib",
            "--no-cache",
            "--target",
            requested,
            "--emit-link-plan",
            str(plan),
            "-o",
            str(tmp_path / "program.c"),
        ],
    )

    assert compiler_main() == 0
    payload = json.loads(plan.read_text(encoding="utf-8"))
    assert payload["target"] == expected
    assert payload["units"] == []


def test_dependency_local_aliases_form_a_diamond_once(tmp_path: Path) -> None:
    leaf = tmp_path / "leaf"
    _manifest(leaf, "leaf")
    for name in ("left", "right"):
        _manifest(
            tmp_path / name,
            name,
            '\n[dependencies]\nshared = { path = "../leaf" }\n',
        )
    app = tmp_path / "app"
    _manifest(
        app,
        "app",
        '\n[dependencies]\nl = { path = "../left" }\nr = { path = "../right" }\n',
    )

    resolved = PackageUniverse().resolve_manifest(str(app / "btrc.toml"), target="linux-x64")

    assert sorted(resolved.nodes) == ["app", "leaf", "left", "right"]
    assert resolved.nodes["left"].dependencies == {"shared": "leaf"}
    assert resolved.nodes["right"].dependencies == {"shared": "leaf"}
    assert [package["name"] for package in resolved.native_plan.as_dict()["packages"]].count("leaf") == 1


def test_recursive_package_cycle_reports_the_path(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    _manifest(a, "a", '\n[dependencies]\nb = { path = "../b" }\n')
    _manifest(b, "b", '\n[dependencies]\na = { path = "../a" }\n')

    with pytest.raises(ValueError, match=r"package dependency cycle: a -> b -> a"):
        PackageUniverse().resolve_manifest(str(a / "btrc.toml"), target="linux-x64")


def test_schema_three_lock_rejects_malformed_nested_graph(tmp_path: Path) -> None:
    _manifest(tmp_path, "app")
    (tmp_path / "btrc.lock").write_text(
        json.dumps(
            {
                "manifest-hash": "0" * 64,
                "packages": [
                    {
                        "dependencies": {},
                        "manifest-hash": "0" * 64,
                        "name": "app",
                        "source": {"path": str(tmp_path)},
                    }
                ],
                "root": "app",
                "schema": PACKAGE_GRAPH_LOCK_SCHEMA,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(LockfileError, match="invalid schema-3 package"):
        PackageUniverse().resolve_manifest(str(tmp_path / "btrc.toml"), target="linux-x64")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('manifest-version = 1\nunknown = true\n[package]\nname = "bad"\n', "unexpected field"),
        (
            'manifest-version = 1\n[package]\nname = "bad"\n[dependencies]\nx = { path = "x", git = "g" }\n',
            "exactly one of path or git",
        ),
        (
            'manifest-version = 1\n[package]\nname = "bad"\n[[native.sources]]\npath = "x.c"\n'
            'language = "rust"\nstandard = "c11"\n',
            "language is unsupported",
        ),
    ],
)
def test_strict_manifest_failures_are_precise(tmp_path: Path, body: str, message: str) -> None:
    (tmp_path / "btrc.toml").write_text(body, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        PackageUniverse().resolve_manifest(str(tmp_path / "btrc.toml"), target="linux-x64")


def test_compile_wraps_strict_manifest_failures_as_package_diagnostics(tmp_path: Path) -> None:
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    (tmp_path / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "app"\ninvalid = true\n',
        encoding="utf-8",
    )

    result = Compiler().compile(source.read_text(), str(source), CompilerOptions(include_stdlib=False))

    assert not result.successful
    assert result.failure is not None
    assert result.failure.kind.value == "package"
    assert "unexpected field" in result.failure.message
