"""Self-hosted parity for recursive packages and native link plans."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.native_plan import NativePlanBuilder

REPO = Path(__file__).resolve().parents[3]
EXAMPLE = REPO / "examples" / "native-package"


def _environment() -> dict[str, str]:
    return {**os.environ, "BTRC_HOME": str(REPO / "src")}


def _reference(
    source: Path,
    generated: Path,
    plan: Path | None = None,
    *,
    target: str = "linux-x64",
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "src.compiler.python.main",
        "--no-stdlib",
        "--no-cache",
        "--target",
        target,
    ]
    if plan is not None:
        command.extend(("--emit-link-plan", str(plan)))
    command.extend((str(source), "-o", str(generated)))
    return subprocess.run(command, cwd=REPO, capture_output=True, text=True, env=_environment())


def _selfhost(
    compiler: Path,
    source: Path,
    plan: Path | None = None,
    *,
    target: str = "linux-x64",
) -> subprocess.CompletedProcess[str]:
    command = [str(compiler), "--no-stdlib", "--target", target]
    if plan is not None:
        command.extend(("--emit-link-plan", str(plan)))
    command.append(str(source))
    return subprocess.run(command, cwd=REPO, capture_output=True, text=True, env=_environment())


def _manifest(path: Path, name: str, dependencies: str = "", native: str = "") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "btrc.toml").write_text(
        f'manifest-version = 1\n\n[package]\nname = "{name}"\n{dependencies}{native}',
        encoding="utf-8",
    )
    (path / "src").mkdir(exist_ok=True)


def _module_projection_project(tmp_path: Path) -> Path:
    app = tmp_path / "app"
    dependency = app / "packages" / "seams"
    (dependency / "native").mkdir(parents=True)
    for module, source in (
        ("Direct", "extern int direct_native();\n"),
        ("Primary", 'import "./Secondary.btrc"\nextern int primary_native();\n'),
        ("Secondary", "extern int secondary_native();\n"),
    ):
        (dependency / "src").mkdir(exist_ok=True)
        (dependency / f"src/{module}.btrc").write_text(source, encoding="utf-8")
        (dependency / f"native/{module}.c").write_text(
            f"int {module.lower()}_native(void) {{ return 1; }}\n",
            encoding="utf-8",
        )
    (dependency / "native/Common.h").write_text("#pragma once\n", encoding="utf-8")
    _manifest(
        dependency,
        "seams",
        native=(
            '\n[[native.headers]]\npath = "native/Common.h"\n'
            '\n[[native.include-directories]]\npath = "native"\n'
            '\n[[native.sources]]\npath = "native/Direct.c"\nlanguage = "c"\nstandard = "c11"\n'
            'modules = [\n    "Direct",\n]\n'
            '\n[[native.sources]]\npath = "native/Primary.c"\nlanguage = "c"\nstandard = "c11"\n'
            'modules = ["Primary"]\n'
            '\n[[native.sources]]\npath = "native/Secondary.c"\nlanguage = "c"\nstandard = "c11"\n'
            'modules = ["Secondary"]\n'
        ),
    )
    _manifest(app, "app", '\n[dependencies]\nseams = { path = "packages/seams" }\n')
    return app / "src/Main.btrc"


def test_selfhost_native_plan_is_exact_for_loaded_module_projection(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = _module_projection_project(tmp_path)
    cases = (
        ("pure", "int main() { return 0; }\n", [], ["app"]),
        ("direct", "import seams.Direct\nint main() { return 0; }\n", ["Direct.c"], ["app", "seams"]),
        (
            "transitive",
            "import seams.Primary\nint main() { return 0; }\n",
            ["Primary.c", "Secondary.c"],
            ["app", "seams"],
        ),
    )
    for name, content, units, packages in cases:
        source.write_text(content, encoding="utf-8")
        reference_plan = tmp_path / f"{name}-reference.json"
        selfhost_plan = tmp_path / f"{name}-selfhost.json"

        reference = _reference(source, tmp_path / f"{name}-reference.c", reference_plan)
        selfhost = _selfhost(semantic_btrcc, source, selfhost_plan)

        assert reference.returncode == 0, reference.stderr
        assert selfhost.returncode == 0, selfhost.stderr
        assert selfhost_plan.read_bytes() == reference_plan.read_bytes()
        payload = json.loads(selfhost_plan.read_text(encoding="utf-8"))
        assert [package["name"] for package in payload["packages"]] == packages
        assert [Path(unit["path"]).name for unit in payload["units"]] == units
        expected_dependencies = {} if name == "pure" else {"seams": "seams"}
        assert payload["packages"][0]["dependencies"] == expected_dependencies
        if name == "pure":
            for field in ("defines", "frameworks", "headers", "include-directories", "pkg-config"):
                assert payload[field] == []
        else:
            assert [Path(header["path"]).name for header in payload["headers"]] == ["Common.h"]


@pytest.mark.parametrize(
    ("modules", "message"),
    [
        ("[]", "modules must not be empty"),
        ('["Direct", "Direct"]', "modules contains a duplicate value"),
        ('["bad..module"]', "contains invalid module"),
        ('["Missing"]', "names unknown module"),
    ],
)
def test_selfhost_native_module_scope_failures_match_reference(
    semantic_btrcc: Path,
    tmp_path: Path,
    modules: str,
    message: str,
) -> None:
    source = tmp_path / "src/Main.btrc"
    source.parent.mkdir()
    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    (tmp_path / "native").mkdir()
    (tmp_path / "native/Seam.c").write_text("int seam(void) { return 1; }\n", encoding="utf-8")
    _manifest(
        tmp_path,
        "app",
        native=(
            f'\n[[native.sources]]\npath = "native/Seam.c"\nlanguage = "c"\nstandard = "c11"\nmodules = {modules}\n'
        ),
    )

    reference = _reference(source, tmp_path / "reference.c")
    selfhost = _selfhost(semantic_btrcc, source)

    assert reference.returncode != 0
    assert selfhost.returncode != 0
    assert message in reference.stderr
    assert message in selfhost.stderr


def test_selfhost_rejects_one_native_record_split_across_scopes(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/Main.btrc"
    source.parent.mkdir()
    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    for module in ("Direct", "Other"):
        (tmp_path / f"src/{module}.btrc").write_text("extern int seam();\n", encoding="utf-8")
    (tmp_path / "native").mkdir()
    (tmp_path / "native/Seam.c").write_text("int seam(void) { return 1; }\n", encoding="utf-8")
    declaration = '\n[[native.sources]]\npath = "native/Seam.c"\nlanguage = "c"\nstandard = "c11"\n'
    _manifest(
        tmp_path,
        "app",
        native=declaration + 'modules = ["Direct"]\n' + declaration + 'modules = ["Other"]\n',
    )

    reference = _reference(source, tmp_path / "reference.c")
    selfhost = _selfhost(semantic_btrcc, source)

    assert reference.returncode != 0
    assert selfhost.returncode != 0
    assert "duplicates an earlier native declaration" in reference.stderr
    assert "duplicates a native declaration" in selfhost.stderr


def test_selfhost_plan_is_reference_exact_and_builds_native_package(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = EXAMPLE / "src" / "main.btrc"
    reference_c = tmp_path / "reference.c"
    reference_plan = tmp_path / "reference.link.json"
    selfhost_c = tmp_path / "selfhost.c"
    selfhost_plan = tmp_path / "selfhost.link.json"
    lock_before = (EXAMPLE / "btrc.lock").read_bytes()

    reference = _reference(source, reference_c, reference_plan)
    selfhost = _selfhost(semantic_btrcc, source, selfhost_plan)

    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    selfhost_c.write_text(selfhost.stdout, encoding="utf-8")
    assert selfhost_plan.read_bytes() == reference_plan.read_bytes()
    assert (EXAMPLE / "btrc.lock").read_bytes() == lock_before
    executable = tmp_path / "native-package"
    NativePlanBuilder().build(plan_path=selfhost_plan, generated_c=selfhost_c, output=executable)
    completed = subprocess.run([str(executable)], capture_output=True, check=True, text=True)
    assert completed.stdout == "PASS: native package graph\n"


def test_fresh_selfhost_lock_is_reference_exact(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    reference_root = tmp_path / "reference"
    selfhost_root = tmp_path / "selfhost"
    shutil.copytree(EXAMPLE, reference_root, ignore=shutil.ignore_patterns(".btrc-cache"))
    shutil.copytree(EXAMPLE, selfhost_root, ignore=shutil.ignore_patterns(".btrc-cache"))
    (reference_root / "btrc.lock").unlink()
    (selfhost_root / "btrc.lock").unlink()

    reference = _reference(reference_root / "src/main.btrc", tmp_path / "reference.c")
    selfhost = _selfhost(semantic_btrcc, selfhost_root / "src/main.btrc")

    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    assert (selfhost_root / "btrc.lock").read_bytes() == (reference_root / "btrc.lock").read_bytes()
    assert not list(selfhost_root.glob(".btrc-package-*"))


@pytest.mark.parametrize(
    ("target", "languages", "frameworks", "pkg_config"),
    [
        ("macos-arm64", ["c", "c++", "objective-c", "objective-c++"], ["Foundation"], []),
        ("windows-x64", ["c", "c++"], [], ["native-package-proof"]),
    ],
)
def test_platform_native_plans_are_reference_exact(
    semantic_btrcc: Path,
    tmp_path: Path,
    target: str,
    languages: list[str],
    frameworks: list[str],
    pkg_config: list[str],
) -> None:
    source = EXAMPLE / "src/main.btrc"
    reference_plan = tmp_path / f"reference-{target}.json"
    selfhost_plan = tmp_path / f"selfhost-{target}.json"

    reference = _reference(
        source,
        tmp_path / f"reference-{target}.c",
        reference_plan,
        target=target,
    )
    selfhost = _selfhost(semantic_btrcc, source, selfhost_plan, target=target)

    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    assert selfhost_plan.read_bytes() == reference_plan.read_bytes()
    payload = json.loads(selfhost_plan.read_text())
    assert [unit["language"] for unit in payload["units"]] == languages
    assert [entry["name"] for entry in payload["frameworks"]] == frameworks
    assert [entry["name"] for entry in payload["pkg-config"]] == pkg_config


def test_disjoint_native_predicates_with_same_name_are_reference_exact(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/main.btrc"
    source.parent.mkdir()
    source.write_text("int main() { return 0; }\n")
    (tmp_path / "btrc.toml").write_text(
        'manifest-version = 1\n\n[package]\nname = "app"\n'
        '\n[[native.pkg-config]]\nname = "platform-native"\nos = ["macos"]\n'
        '\n[[native.pkg-config]]\nname = "platform-native"\nos = ["linux"]\n'
    )
    reference_plan = tmp_path / "reference.json"
    selfhost_plan = tmp_path / "selfhost.json"

    reference = _reference(
        source,
        tmp_path / "reference.c",
        reference_plan,
        target="macos-arm64",
    )
    selfhost = _selfhost(
        semantic_btrcc,
        source,
        selfhost_plan,
        target="macos-arm64",
    )

    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    assert selfhost_plan.read_bytes() == reference_plan.read_bytes()
    assert json.loads(selfhost_plan.read_text())["pkg-config"] == [{"name": "platform-native", "package": "app"}]


def test_exact_duplicate_native_declarations_still_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/main.btrc"
    source.parent.mkdir()
    source.write_text("int main() { return 0; }\n")
    declaration = '\n[[native.pkg-config]]\nname = "platform-native"\nos = ["macos"]\n'
    (tmp_path / "btrc.toml").write_text('manifest-version = 1\n\n[package]\nname = "app"\n' + declaration + declaration)

    reference = _reference(source, tmp_path / "reference.c", target="macos-arm64")
    selfhost = _selfhost(
        semantic_btrcc,
        source,
        target="macos-arm64",
    )

    assert reference.returncode != 0
    assert selfhost.returncode != 0
    assert "duplicates an earlier native declaration" in reference.stderr
    assert "duplicates a native declaration" in selfhost.stderr


def test_dependency_local_aliases_resolve_a_diamond_once(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    leaf = tmp_path / "leaf"
    _manifest(leaf, "leaf")
    (leaf / "src/shared.btrc").write_text("int shared_value() { return 20; }\n")
    for name, value in (("left", 1), ("right", 2)):
        package = tmp_path / name
        _manifest(package, name, '\n[dependencies]\nshared = { path = "../leaf" }\n')
        (package / f"src/{name}.btrc").write_text(
            f"import shared.shared\nint {name}_value() {{ return shared_value() + {value}; }}\n"
        )
    app = tmp_path / "app"
    _manifest(
        app,
        "app",
        '\n[dependencies]\nl = { path = "../left" }\nr = { path = "../right" }\n',
    )
    source = app / "src/main.btrc"
    source.write_text(
        "import l.left\nimport r.right\nint main() { assert(left_value() + right_value() == 43); return 0; }\n"
    )
    reference_plan = tmp_path / "reference.json"
    selfhost_plan = tmp_path / "selfhost.json"

    reference = _reference(source, tmp_path / "reference.c", reference_plan)
    reference_lock = (app / "btrc.lock").read_bytes() if reference.returncode == 0 else b""
    selfhost = _selfhost(semantic_btrcc, source, selfhost_plan)

    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    assert selfhost_plan.read_bytes() == reference_plan.read_bytes()
    assert [entry["name"] for entry in json.loads(selfhost_plan.read_text())["packages"]].count("leaf") == 1
    assert (app / "btrc.lock").read_bytes() == reference_lock


def test_selfhost_cycle_and_future_lock_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    _manifest(a, "a", '\n[dependencies]\nb = { path = "../b" }\n')
    _manifest(b, "b", '\n[dependencies]\na = { path = "../a" }\n')
    source = a / "src/main.btrc"
    source.write_text("int main() { return 0; }\n")

    cycle = _selfhost(semantic_btrcc, source)

    assert cycle.returncode != 0
    assert "package dependency cycle: a -> b -> a" in cycle.stderr

    (a / "btrc.lock").write_text(
        '{"manifest-hash":"' + "0" * 64 + '","packages":[],"root":"a","schema":4}',
        encoding="utf-8",
    )
    future = _selfhost(semantic_btrcc, source)
    assert future.returncode != 0
    assert "unsupported btrc.lock schema 4" in future.stderr


def test_selfhost_rejects_malformed_nested_lock(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    _manifest(tmp_path, "app")
    source = tmp_path / "src/main.btrc"
    source.write_text("int main() { return 0; }\n")
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
                "schema": 3,
            }
        )
    )

    result = _selfhost(semantic_btrcc, source)

    assert result.returncode != 0
    assert "invalid schema-3 package" in result.stderr


def test_selfhost_rejects_git_without_attempting_acquisition(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/main.btrc"
    source.parent.mkdir()
    source.write_text("int main() { return 0; }\n")
    (tmp_path / "btrc.toml").write_text(
        'manifest-version = 1\n\n[package]\nname = "app"\n\n[dependencies]\n'
        'remote = { git = "https://example.invalid/never.git", rev = "v1" }\n'
    )

    result = _selfhost(semantic_btrcc, source)

    assert result.returncode != 0
    assert "Git dependency 'remote' is not yet supported by btrcc" in result.stderr


def test_selfhost_versioned_manifest_requires_explicit_target(
    semantic_btrcc: Path,
) -> None:
    source = EXAMPLE / "src/main.btrc"

    result = subprocess.run(
        [str(semantic_btrcc), "--no-stdlib", str(source)],
        cwd=REPO,
        capture_output=True,
        text=True,
        env=_environment(),
    )

    assert result.returncode != 0
    assert "version-1 package manifests require --target OS-ARCH" in result.stderr


def test_selfhost_strict_manifest_rejects_arbitrary_build_fields(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.btrc"
    source.write_text("int main() { return 0; }\n")
    (tmp_path / "btrc.toml").write_text(
        'manifest-version = 1\ncflags = "-fno-something"\n[package]\nname = "bad"\n',
        encoding="utf-8",
    )

    result = _selfhost(semantic_btrcc, source)

    assert result.returncode != 0
    assert "must declare only integer manifest-version = 1 at its root" in result.stderr
