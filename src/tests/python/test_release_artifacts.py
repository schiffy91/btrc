"""Production release-artifact and native-build gate contracts."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def test_lsp_dependency_floor_matches_the_imported_pygls_api() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))

    assert "pygls>=2.0.0" in project["project"]["dependencies"]

    from pygls.lsp.server import LanguageServer

    assert LanguageServer.__module__ == "pygls.lsp.server"


def _copy_package_source(destination: Path) -> None:
    destination.mkdir()
    for name in ("LICENSE", "README.md", "pyproject.toml"):
        shutil.copy2(REPO / name, destination / name)
    shutil.copytree(
        REPO / "src",
        destination / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.o", "*.a", "*.vsix", "build", "tests"),
    )


def test_python_wheel_and_sdist_carry_the_declared_mit_license(tmp_path: Path) -> None:
    source = tmp_path / "source"
    artifacts = tmp_path / "artifacts"
    _copy_package_source(source)
    subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(artifacts)],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )

    wheels = list(artifacts.glob("*.whl"))
    sdists = list(artifacts.glob("*.tar.gz"))
    assert len(wheels) == 1 and len(sdists) == 1
    wheel, sdist = wheels[0], sdists[0]
    expected = (REPO / "LICENSE").read_bytes()
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        license_names = [name for name in names if name.endswith(".dist-info/licenses/LICENSE")]
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        assert len(license_names) == 1
        assert archive.read(license_names[0]) == expected
        assert b"License-Expression: MIT\n" in archive.read(metadata_name)
    with tarfile.open(sdist, "r:gz") as archive:
        license_members = [member for member in archive.getmembers() if member.name.endswith("/LICENSE")]
        assert len(license_members) == 1
        stream = archive.extractfile(license_members[0])
        assert stream is not None and stream.read() == expected


def test_production_test_targets_require_gpu_and_cover_both_compilers() -> None:
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    ci = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    test_rule = next(line for line in makefile.splitlines() if line.startswith("test:"))
    c11_rule = next(line for line in makefile.splitlines() if line.startswith("test-c11:"))
    c11_recipe = makefile.split("test-c11:", 1)[1].split("test-generate-goldens:", 1)[0]

    assert "gpu-required" in test_rule
    assert "gpu-required" in c11_rule and "btrcc" in c11_rule
    assert 'BTRC_TEST_BTRCC="$(abspath bin/btrcc)"' in c11_recipe
    assert "--compilers=python,btrc" in c11_recipe
    assert "make NIX= gpu-required test" in ci


def _write_fake_native_tools(directory: Path) -> tuple[Path, Path]:
    compiler = directory / "fake-cc"
    compiler.write_text(
        """#!/bin/sh
phase=compile
source=
output=
while [ "$#" -gt 0 ]; do
    case "$1" in
        -E) phase=probe ;;
        *.c) source=$(basename "$1") ;;
        -o) shift; output=$1 ;;
    esac
    shift
done
if [ "$source" = "$FAIL_SOURCE" ] && [ "$phase" = "$FAIL_PHASE" ]; then
    exit 17
fi
if [ -n "$output" ] && [ "$output" != /dev/null ]; then
    : > "$output"
fi
""",
        encoding="utf-8",
    )
    archiver = directory / "fake-ar"
    archiver.write_text(
        """#!/bin/sh
if [ "$1" = rcs ]; then
    : > "$2"
fi
""",
        encoding="utf-8",
    )
    compiler.chmod(0o755)
    archiver.chmod(0o755)
    return compiler, archiver


@pytest.mark.parametrize(
    ("source_name", "phase", "stem", "succeeds"),
    (
        ("btrc_gui.c", "compile", "btrc_gui", False),
        ("btrc_gui_window.c", "probe", "btrc_gui_window", True),
        ("btrc_gui_window.c", "compile", "btrc_gui_window", False),
        ("btrc_gui_font.c", "probe", "btrc_gui_font", True),
        ("btrc_gui_font.c", "compile", "btrc_gui_font", False),
    ),
)
def test_gui_rule_removes_stale_outputs_on_probe_or_compile_failure(
    tmp_path: Path,
    source_name: str,
    phase: str,
    stem: str,
    succeeds: bool,
) -> None:
    build = tmp_path / "build/stdlib/gui"
    build.mkdir(parents=True)
    archive = build / f"lib{stem}.a"
    object_file = build / f"{stem}.o"
    archive.write_text("stale archive", encoding="utf-8")
    object_file.write_text("stale object", encoding="utf-8")
    compiler, archiver = _write_fake_native_tools(tmp_path)
    result = subprocess.run(
        ["make", "-f", str(REPO / "Makefile"), "gui", "NIX=", f"CC={compiler}", f"HOST_AR={archiver}"],
        cwd=tmp_path,
        env={**os.environ, "FAIL_SOURCE": source_name, "FAIL_PHASE": phase},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert (result.returncode == 0) is succeeds, result.stderr
    assert not archive.exists()
    assert not object_file.exists()
