"""Explicit, immutable package ownership across compiler invocations."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from src.compiler.python.frontend.packages import (
    IncludeResolutionError,
    PackageUniverse,
    ResolvedPackages,
)
from src.compiler.python.frontend.stage import FrontendStage


def _project(root: Path, marker: str) -> tuple[Path, str]:
    dependency = root / f"dependency-{marker}"
    (dependency / "src").mkdir(parents=True)
    (dependency / "src" / "dep.btrc").write_text(f"class Dep{marker.title()} {{}}\n")

    application = root / f"application-{marker}"
    application.mkdir()
    (application / "btrc.toml").write_text(f'[dependencies]\ndep = {{ path = "../dependency-{marker}" }}\n')
    source_path = application / "main.btrc"
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

    loose = tmp_path / "loose" / "main.btrc"
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
    broken_path = broken / "main.btrc"
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
