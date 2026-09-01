import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "src" / "stdlib" / "background_jobs"
FIXTURE = ROOT / "src" / "tests" / "native" / "background_jobs"
CONFORMANCE = FIXTURE / "background_jobs_conformance.btrc"
EXPECTED = FIXTURE / "background_jobs_conformance.expected"
COMPILE_TIMEOUT = 180
RUN_TIMEOUT = 90

PLANNED_CONSUMER = """\
#include <assert.h>

import std.background_jobs;

int main() {
    BackgroundJobsOpenOutcome opened = BackgroundJobExecutor.open(1, 1);
    assert(opened.kind == BACKGROUND_JOBS_OPENED);
    assert(opened.executor != null);
    BackgroundJobExecutor executor = opened.executor;
    BackgroundJobsCloseOutcome closed = executor.close(BACKGROUND_JOBS_DRAIN);
    assert(closed.kind == BACKGROUND_JOBS_CLOSED);
    print("PASS: planned background jobs runtime");
    return 0;
}
"""


def _transpile(
    frontend: str,
    output: Path,
    request: pytest.FixtureRequest,
) -> None:
    environment = {
        **os.environ,
        "BTRC_CACHE_DIR": str(output.parent / f"cache-{frontend}"),
        "BTRC_HOME": str(ROOT / "src"),
    }
    if frontend == "python":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(CONFORMANCE),
            "--strict-imports",
            "--no-cache",
            "-o",
            str(output),
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
    else:
        btrcc = request.getfixturevalue("immutable_btrcc")
        result = subprocess.run(
            [str(btrcc), "--strict-imports", str(CONFORMANCE)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        if result.returncode == 0:
            output.write_text(result.stdout)
    assert result.returncode == 0 and output.is_file(), result.stderr


def _compile(
    c_compiler: str,
    generated: Path,
    executable: Path,
) -> None:
    flags = [
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        "-pthread",
        f"-I{RUNTIME}",
        f"-I{FIXTURE}",
    ]
    objects = []
    for name, source in (
        ("generated", generated),
        ("runtime", RUNTIME / "btrc_background_jobs.c"),
        ("probe", FIXTURE / "background_job_probe.c"),
    ):
        object_path = executable.with_suffix(f".{name}.o")
        result = subprocess.run(
            [c_compiler, *flags, "-c", str(source), "-o", str(object_path)],
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        assert result.returncode == 0, result.stderr
        objects.append(object_path)
    result = subprocess.run(
        [
            c_compiler,
            *(str(object_path) for object_path in objects),
            "-pthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_bounded_background_jobs_on_both_frontends_and_c_compilers(
    compiler: str,
    c_compiler: str,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    generated = tmp_path / f"background-jobs-{compiler}-{c_compiler}.c"
    executable = tmp_path / f"background-jobs-{compiler}-{c_compiler}"
    _transpile(compiler, generated, request)
    _compile(c_compiler, generated, executable)
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == EXPECTED.read_text()
    assert result.stderr == ""


def test_import_emits_and_links_compiler_owned_runtime(
    compiler: str,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    target = PackageTarget.parse(None)
    if target.operating_system == "windows":
        pytest.skip("std.background_jobs currently owns a POSIX runtime")
    target_text = f"{target.operating_system}-{target.architecture}"
    project = tmp_path / "project"
    project.mkdir()
    source = project / "main.btrc"
    source.write_text(PLANNED_CONSUMER)
    (project / "btrc.toml").write_text('manifest-version = 1\n\n[package]\nname = "planned_jobs"\n')
    generated = tmp_path / f"planned-{compiler}.c"
    plan = tmp_path / f"planned-{compiler}.json"
    environment = {
        **os.environ,
        "BTRC_CACHE_DIR": str(tmp_path / f"cache-{compiler}"),
        "BTRC_HOME": str(ROOT / "src"),
    }
    if compiler == "python":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--strict-imports",
            "--no-cache",
            "--target",
            target_text,
            "--emit-link-plan",
            str(plan),
            str(source),
            "-o",
            str(generated),
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
    else:
        btrcc = request.getfixturevalue("immutable_btrcc")
        command = [
            str(btrcc),
            "--strict-imports",
            "--target",
            target_text,
            "--emit-link-plan",
            str(plan),
            str(source),
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        if completed.returncode == 0:
            generated.write_text(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    if compiler == "btrc":
        reference_generated = tmp_path / "planned-reference.c"
        reference_plan = tmp_path / "planned-reference.json"
        reference = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.compiler.python.main",
                "--strict-imports",
                "--no-cache",
                "--target",
                target_text,
                "--emit-link-plan",
                str(reference_plan),
                str(source),
                "-o",
                str(reference_generated),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        assert reference.returncode == 0, reference.stderr
        assert plan.read_bytes() == reference_plan.read_bytes()
    payload = json.loads(plan.read_text())
    runtime_units = [unit for unit in payload["units"] if unit["package"] == "btrc_stdlib_runtime"]
    assert runtime_units == [
        {
            "language": "c",
            "package": "btrc_stdlib_runtime",
            "path": str(RUNTIME / "btrc_background_jobs.c"),
            "standard": "c11",
        }
    ]
    executable = tmp_path / f"planned-{compiler}"
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
    )
    ran = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: planned background jobs runtime\n"
    assert ran.stderr == ""
