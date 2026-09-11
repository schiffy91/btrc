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
RUNTIME = ROOT / "src" / "stdlib" / "BackgroundJobs"
FIXTURE = ROOT / "src" / "tests" / "native" / "background_jobs"
CONFORMANCE = FIXTURE / "BackgroundJobsConformance.btrc"
EXPECTED = FIXTURE / "background_jobs_conformance.expected"
COMPILE_TIMEOUT = 180
RUN_TIMEOUT = 90

PLANNED_CONSUMER = """\
#include <assert.h>

import Library.BackgroundJobs;

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
    source: Path = CONFORMANCE,
) -> None:
    target = PackageTarget.parse(None)
    target_text = f"{target.operating_system}-{target.architecture}"
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
            str(source),
            "--strict-imports",
            "--target",
            target_text,
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
            [str(btrcc), "--strict-imports", "--target", target_text, str(source)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        if result.returncode == 0:
            output.write_text(result.stdout)
    assert result.returncode == 0 and output.is_file(), result.stderr
    assert str(RUNTIME / "NativeThreads.h") in output.read_text()


def _compile(
    c_compiler: str,
    generated: Path,
    executable: Path,
    *,
    sanitized: bool = False,
    faults: bool = False,
) -> None:
    environment = dict(os.environ)
    sanitizer_flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    if sanitized and sys.platform == "darwin":
        environment.pop("DEVELOPER_DIR", None)
        environment.pop("SDKROOT", None)
    sdk_flags = []
    if sanitized and sys.platform == "darwin":
        sdk_flags = ["-isysroot", environment["BTRC_NATIVE_SYSROOT"], "-target", environment["BTRC_NATIVE_TARGET"]]
    flags = [
        *sanitizer_flags,
        *sdk_flags,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        "-pthread",
        f"-I{FIXTURE}",
    ]
    objects = []
    for name, source in (
        ("generated", generated),
        ("probe", FIXTURE / ("NativeThreadFaults.c" if faults else "background_job_probe.c")),
    ):
        object_path = executable.with_suffix(f".{name}.o")
        hooks = ["-include", str(FIXTURE / "NativeThreadFaults.h")] if faults and name == "generated" else []
        result = subprocess.run(
            [c_compiler, *flags, *hooks, "-c", str(source), "-o", str(object_path)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        assert result.returncode == 0, result.stderr
        objects.append(object_path)
    result = subprocess.run(
        [
            c_compiler,
            *sanitizer_flags,
            *sdk_flags,
            *(str(object_path) for object_path in objects),
            "-pthread",
            "-o",
            str(executable),
        ],
        env=environment,
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


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="requires a supported POSIX sanitizer toolchain")
def test_background_jobs_managed_callbacks_with_sanitizers(compiler, tmp_path, request):
    generated = tmp_path / f"background-jobs-{compiler}.c"
    executable = tmp_path / f"background-jobs-{compiler}"
    _transpile(compiler, generated, request)
    _compile("/usr/bin/clang" if sys.platform == "darwin" else "clang", generated, executable, sanitized=True)
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert result.stdout == EXPECTED.read_text()
    assert result.stderr == ""


@pytest.mark.parametrize("sanitized", [False, True])
def test_background_jobs_sdk_failures_and_retry(compiler, tmp_path, request, sanitized):
    if sanitized and sys.platform not in {"darwin", "linux"}:
        pytest.skip("requires a supported POSIX sanitizer toolchain")
    generated = tmp_path / f"background-jobs-failures-{compiler}.c"
    executable = tmp_path / f"background-jobs-failures-{compiler}"
    _transpile(compiler, generated, request, FIXTURE / "BackgroundJobsFailures.btrc")
    _compile(
        "/usr/bin/clang" if sanitized and sys.platform == "darwin" else "clang",
        generated,
        executable,
        sanitized=sanitized,
        faults=True,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: background jobs failure recovery\n"
    assert result.stderr == ""


def test_import_emits_and_links_sdk_declarations_without_native_executor(
    compiler: str,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    target = PackageTarget.parse(None)
    if target.operating_system == "windows":
        pytest.skip("Library.BackgroundJobs currently owns a POSIX runtime")
    target_text = f"{target.operating_system}-{target.architecture}"
    project = tmp_path / "project"
    project.mkdir()
    source = project / "Main.btrc"
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
    assert runtime_units == []
    assert "std_background_jobs_" not in generated.read_text()
    assert str(RUNTIME / "NativeThreads.h") in generated.read_text()
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
