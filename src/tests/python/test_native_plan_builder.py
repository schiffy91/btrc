"""Production Make adapter proofs for compiler-emitted native plans."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.native_plan import NativePlanBuilder, NativePlanError, NativePlanReader

REPO = Path(__file__).resolve().parents[3]
EXAMPLE = REPO / "examples" / "native-package"


def _emit_plan(root: Path, generated: Path, plan: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-stdlib",
            "--no-cache",
            "--target",
            "linux-x64",
            "--emit-link-plan",
            str(plan),
            str(root / "src/main.btrc"),
            "-o",
            str(generated),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_builder_compiles_only_plan_units_and_runs(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".btrc-cache", "build"))
    poison = project / "packages/middle/native/not-declared.c"
    poison.write_text('#error "a native-plan consumer must not scan source directories"\n')
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    output = tmp_path / "program"
    _emit_plan(project, generated, plan)

    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=output)

    completed = subprocess.run([str(output)], capture_output=True, check=True, text=True)
    assert completed.stdout == "PASS: native package graph\n"
    assert poison.is_file()


def test_builder_rejects_non_schema_flags_before_build(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".btrc-cache", "build"))
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    _emit_plan(project, generated, plan)
    payload = json.loads(plan.read_text())
    payload["cflags"] = ["-include", "/tmp/injected.h"]
    plan.write_text(
        json.dumps(payload, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )

    with pytest.raises(NativePlanError, match="must contain exactly"):
        NativePlanBuilder().build(
            plan_path=plan,
            generated_c=generated,
            output=tmp_path / "must-not-exist",
        )

    assert not (tmp_path / "must-not-exist").exists()


def test_reader_compares_real_paths_for_package_containment(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".btrc-cache", "build"))
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    _emit_plan(project, generated, plan)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escaped.c").write_text("int escaped(void) { return 0; }\n")
    escape = project / "packages/leaf/native/escape"
    try:
        escape.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink containment proof is unavailable on this host")
    payload = json.loads(plan.read_text())
    payload["units"].append(
        {
            "language": "c",
            "package": "leaf",
            "path": str(escape / "escaped.c"),
            "standard": "c11",
        }
    )
    payload["units"].sort(key=lambda unit: (unit["package"], unit["path"], unit["language"]))
    plan.write_text(
        json.dumps(payload, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )

    with pytest.raises(NativePlanError, match="escapes package root"):
        NativePlanReader().read(plan)


def test_reader_rejects_frameworks_for_non_macos_target(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".btrc-cache", "build"))
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    _emit_plan(project, generated, plan)
    payload = json.loads(plan.read_text())
    payload["frameworks"] = [{"name": "Cocoa", "package": "middle"}]
    plan.write_text(
        json.dumps(payload, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )

    with pytest.raises(NativePlanError, match="frameworks require a macos target"):
        NativePlanReader().read(plan)


def test_example_makefile_realizes_the_canonical_plan() -> None:
    cc = shutil.which("cc")
    cxx = shutil.which("c++")
    make = shutil.which("make")
    if cc is None or cxx is None or make is None:
        pytest.skip("native Make proof needs make, C, and C++ compilers")
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        completed = subprocess.run(
            [
                make,
                "-C",
                str(EXAMPLE),
                "clean",
                "run",
                "TARGET=linux-x64",
                f"PYTHON={sys.executable}",
                f"CC={cc}",
                f"CXX={cxx}",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert completed.returncode == 0, completed.stderr
        assert "PASS: native package graph" in completed.stdout
        plan = EXAMPLE / "build/native-package.link.json"
        assert plan.is_file()
        assert json.loads(plan.read_text())["units"][1]["language"] == "c++"
    finally:
        shutil.rmtree(EXAMPLE / "build", ignore_errors=True)


def test_adapter_has_no_shell_or_source_discovery_surface() -> None:
    source = (REPO / "tools/native_plan.py").read_text()

    assert "shell=False" in source
    assert ".glob(" not in source
    assert ".rglob(" not in source
    assert "os.walk(" not in source
    marker = "ROOT_FIELDS = frozenset("
    start = source.index(marker)
    end = source.index("TARGET_OPERATING_SYSTEMS", start)
    assert '"cflags"' not in source[start:end]


def test_flake_installs_adapter_and_runs_native_plan_check() -> None:
    flake = (REPO / "flake.nix").read_text()

    assert 'name = "btrc-native-plan";' in flake
    assert 'prefixes = [ "tools/native_plan.py" ];' in flake
    assert "btrc = pkgs.symlinkJoin" in flake
    assert "native-package-plan = pkgs.runCommand" in flake
    assert "NATIVE_PLAN=${self.packages.${system}.btrc-native-plan}/bin/btrc-native-plan" in flake
