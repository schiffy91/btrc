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
    LockfileError,
    PackageUniverse,
)
from src.compiler.python.main import main as compiler_main

REPO = Path(__file__).resolve().parents[3]
EXAMPLE = REPO / "examples" / "native-package"


def _manifest(path: Path, name: str, dependencies: str = "", native: str = "") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "btrc.toml").write_text(
        f'manifest-version = 1\n\n[package]\nname = "{name}"\n{dependencies}{native}',
        encoding="utf-8",
    )


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
    source = EXAMPLE / "src" / "main.btrc"
    packages = PackageUniverse().resolve_for(str(source), target="linux-x64")

    assert packages.root_package == "native_app"
    assert sorted(packages.nodes) == ["leaf", "middle", "native_app"]
    middle = packages.paths_for_import("middle.api", str(source))[0]
    assert packages.paths_for_import("leaf.api", middle)[0].endswith("packages/leaf/src/api.btrc")

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
    source = EXAMPLE / "src" / "main.btrc"
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
    source = EXAMPLE / "src" / "main.btrc"
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
    source = EXAMPLE / "src" / "main.btrc"
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
    source = tmp_path / "main.btrc"
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
