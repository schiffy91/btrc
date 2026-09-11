"""Production Make adapter proofs for compiler-emitted native plans."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import NativeGeneratedUnit, NativeLinkPlan, PackageTarget
from tools.native_plan import NativePlanBuilder, NativePlanError, NativePlanReader, main

REPO = Path(__file__).resolve().parents[3]
EXAMPLE = REPO / "examples" / "native-package"


def generated_plan(source="int answer(void) { return 42; }\n", language="c", standard="c11", memory="manual"):
    return NativeLinkPlan(
        PackageTarget.parse(None),
        generated_units=(NativeGeneratedUnit("Adapter", language, standard, memory, source),),
    ).as_dict()


@pytest.mark.parametrize(
    "corruption",
    ["empty", "duplicate", "name", "language", "standard", "memory", "source", "flags", "linker", "schema"],
)
def test_generated_unit_invalid_plan_never_invokes_compiler(tmp_path, corruption):
    payload = generated_plan()
    unit = payload["generated-units"][0]
    if corruption == "empty":
        payload["generated-units"] = []
    elif corruption == "duplicate":
        payload["generated-units"].append(dict(unit))
    elif corruption == "name":
        unit["name"] = "../Escape"
    elif corruption == "language":
        unit["language"] = "c -include injected.h"
    elif corruption == "standard":
        unit["standard"] = "c89"
    elif corruption == "memory":
        unit["memory-management"] = "arc"
    elif corruption == "source":
        unit["source"] = "bad\0source"
    elif corruption == "flags":
        unit["flags"] = ["-include", "injected.h"]
    elif corruption == "linker":
        payload["linker-language"] = "c++"
    else:
        payload["schema"] = 1
    plan = tmp_path / "Program.link.json"
    plan.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")

    def never_run(*args, **kwargs):
        pytest.fail("invalid generated plan reached a build tool")

    with pytest.raises(NativePlanError):
        NativePlanBuilder(runner=never_run).build(
            plan_path=plan, generated_c=tmp_path / "absent.c", output=tmp_path / "absent"
        )


@pytest.mark.parametrize(
    "language,standard,memory,source",
    [
        ("c", "c11", "manual", "int answer(void) { return 42; }\n"),
        (
            "c++",
            "c++17",
            "raii",
            '#include <string>\nextern "C" int answer(void) { try { throw std::string("forty two"); } catch (const std::string& text) { return text.size() == 9 ? 42 : 0; } }\n',
        ),
    ],
)
def test_generated_unit_build_isolated_from_source_tree(tmp_path, language, standard, memory, source):
    payload = generated_plan(source, language, standard, memory)
    plan = tmp_path / "Program.link.json"
    plan.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    caller = tmp_path / "Caller.c"
    caller.write_text("int answer(void); int main(void) { return answer() == 42 ? 0 : 1; }\n")
    output = tmp_path / "Program"
    NativePlanBuilder().build(plan_path=plan, generated_c=caller, output=output)
    run = subprocess.run([str(output)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert set(path.name for path in tmp_path.iterdir()) == {"Program.link.json", "Caller.c", "Program"}


def test_failed_generated_unit_preserves_output_and_removes_temporary_files(tmp_path):
    payload = generated_plan('#error "generated adapter failure"\n')
    plan = tmp_path / "Program.link.json"
    plan.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    caller = tmp_path / "Caller.c"
    caller.write_text("int main(void) { return 0; }\n")
    output = tmp_path / "Program"
    output.write_bytes(b"previous output")
    with pytest.raises(NativePlanError, match="generated adapter failure"):
        NativePlanBuilder().build(plan_path=plan, generated_c=caller, output=output)
    assert output.read_bytes() == b"previous output"
    assert set(path.name for path in tmp_path.iterdir()) == {"Program.link.json", "Caller.c", "Program"}


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
            str(root / "src/Main.btrc"),
            "-o",
            str(generated),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("optimization", [None, 0, 1, 2, 3])
def test_builder_compiles_only_plan_units_and_runs(tmp_path: Path, optimization: int | None) -> None:
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".btrc-cache", "build"))
    poison = project / "packages/middle/native/not-declared.c"
    poison.write_text('#error "a native-plan consumer must not scan source directories"\n')
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    output = tmp_path / "program"
    _emit_plan(project, generated, plan)

    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.run(command, **kwargs)

    options = {} if optimization is None else {"optimization": optimization}
    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=output, **options)

    compiles = [command for command in commands if "-c" in command]
    assert len(compiles) == 1 + len(json.loads(plan.read_text())["units"])
    for command in compiles:
        assert [flag for flag in command if flag.startswith("-O")] == [
            f"-O{2 if optimization is None else optimization}"
        ]
        assert "-Werror" in command

    completed = subprocess.run([str(output)], capture_output=True, check=True, text=True)
    assert completed.stdout == "PASS: native package graph\n"
    assert poison.is_file()


@pytest.mark.parametrize("optimization", [-1, 4, True, 2.0, "2 -ffast-math"])
def test_builder_rejects_invalid_optimization_before_build(tmp_path: Path, optimization: object) -> None:
    with pytest.raises(NativePlanError, match="optimization must be an integer from 0 through 3"):
        NativePlanBuilder().build(
            plan_path=tmp_path / "absent.link.json",
            generated_c=tmp_path / "absent.c",
            output=tmp_path / "must-not-exist",
            optimization=optimization,
        )
    assert not (tmp_path / "must-not-exist").exists()


def test_cli_rejects_free_form_optimization(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as failure:
        main(
            [
                "--plan",
                str(tmp_path / "absent.link.json"),
                "--generated-c",
                str(tmp_path / "absent.c"),
                "--output",
                str(tmp_path / "must-not-exist"),
                "--optimization",
                "2 -ffast-math",
            ]
        )
    assert failure.value.code == 2


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
