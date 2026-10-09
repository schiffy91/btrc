import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.native_bindings import NativeBindingPackage
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "src" / "stdlib" / "BackgroundJobs"
FIXTURE = ROOT / "src" / "tests" / "native" / "background_jobs"
CONFORMANCE = FIXTURE / "BackgroundJobsConformance.btrc"
FAILURES = FIXTURE / "BackgroundJobsFailures.btrc"
EXPECTED = FIXTURE / "background_jobs_conformance.expected"
WORKER_POOLS = FIXTURE / "HostWorkerPools.btrc"
WORKER_POOLS_EXPECTED = FIXTURE / "host_worker_pools.expected"
COMPILE_TIMEOUT = 180
RUN_TIMEOUT = 90
NATIVE_WORKER = FIXTURE / "NativeWorkerFailures.btrc"
FAULT_CONTROLS = (
    FIXTURE / "NativeThreadFaultControl.h",
    (
        "job_fault_reset",
        "job_fault_at",
        "job_fault_calls",
        "job_fault_live_threads",
        "job_fault_disposals",
        "job_fault_dispose",
        "FAULT_MUTEX_INIT",
        "FAULT_COND_INIT",
        "FAULT_CREATE",
        "FAULT_JOIN",
        "FAULT_MUTEX_DESTROY",
        "FAULT_COND_DESTROY",
    ),
)
# Each probe program binds its fixture's header; it re-spells no prototype.
BINDINGS = {
    CONFORMANCE: (
        FIXTURE / "background_job_probe.h",
        (
            "job_probe_reset",
            "job_probe_release",
            "job_probe_released",
            "job_probe_mark_started",
            "job_probe_mark_finished",
            "job_probe_record_disposal",
            "job_probe_started",
            "job_probe_finished",
            "job_probe_runs",
            "job_probe_disposals",
            "job_probe_yield",
            "JobProbeBehavior",
            "JOB_PROBE_COMPLETE",
            "JOB_PROBE_HOLD",
            "JOB_PROBE_CANCEL",
            "JOB_PROBE_FAIL",
            "JOB_PROBE_THROW",
            "JOB_PROBE_CLEANUP_THROW",
        ),
    ),
    FAILURES: FAULT_CONTROLS,
    NATIVE_WORKER: FAULT_CONTROLS,
}

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
    *,
    threads: bool = True,
) -> None:
    if source in BINDINGS:
        NativeBindingPackage.require_reader()
        source = NativeBindingPackage.write(source, output.parent / f"{output.stem}-package", *BINDINGS[source])
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
    if threads:
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


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="HostWorkerPools forks only on linux and macOS")
def test_host_worker_pools_on_both_frontends(compiler, tmp_path, request):
    """HostWorkerPools selects its provider by target, so this program needs
    --target and cannot run in the target-less corpus runner."""
    generated = tmp_path / f"host-worker-pools-{compiler}.c"
    executable = tmp_path / f"host-worker-pools-{compiler}"
    _transpile(compiler, generated, request, WORKER_POOLS, threads=False)
    flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors", "-O2"]
    built = subprocess.run(
        ["cc", *flags, str(generated), "-o", str(executable), "-lm", "-pthread"],
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert built.returncode == 0, built.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert result.stdout == WORKER_POOLS_EXPECTED.read_text()
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
    _transpile(compiler, generated, request, FAILURES)
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


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_worker_retains_its_body_until_join(compiler, tmp_path, request, sanitized):
    """NativeWorker owns the start/join envelope BackgroundJobExecutor and the
    ALSA stream share: it retains the body only while the thread lives and
    survives SDK create and join failures."""
    if sanitized and sys.platform not in {"darwin", "linux"}:
        pytest.skip("requires a supported POSIX sanitizer toolchain")
    generated = tmp_path / f"native-worker-{compiler}.c"
    executable = tmp_path / f"native-worker-{compiler}"
    _transpile(compiler, generated, request, NATIVE_WORKER)
    _compile(
        "/usr/bin/clang" if sanitized and sys.platform == "darwin" else "clang",
        generated,
        executable,
        sanitized=sanitized,
        faults=True,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: native worker failure recovery\n"
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
    runtime_units = [unit for unit in payload["units"] if unit["package"] == "btrc_stdlib_backgroundjobs"]
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


class WindowsProcessThreadsFixture:
    """Two-stage native proof: SDK projection on a reader-capable host, then
    strict C11 execution on the corresponding real Windows architecture.

    The allocated Windows qualifier calls these methods explicitly. This does
    not add platform-skipped default-suite rows or pretend WindowsMain owns a
    native SDK reader. A Clang VFS maps authenticated relocated headers without
    changing the emitted C or any SDK declarations.
    """

    SYMBOLS = (
        "ProcessThreadFault",
        "PROCESS_THREADS_REAL",
        "PROCESS_THREADS_SNAPSHOT_FAILURE",
        "PROCESS_THREADS_FIRST_FAILURE",
        "PROCESS_THREADS_NEXT_FAILURE",
        "PROCESS_THREADS_SHORT_FIRST",
        "PROCESS_THREADS_SHORT_NEXT",
        "PROCESS_THREADS_SHORT_VALID",
        "PROCESS_THREADS_CLOSE_FAILURE",
        "PROCESS_THREADS_EMPTY",
        "PROCESS_THREADS_FOREIGN_ONLY",
        "process_threads_child_mode",
        "process_threads_start_held",
        "process_threads_stop_held",
        "process_threads_start_foreign",
        "process_threads_stop_foreign",
        "process_threads_reset",
        "process_threads_snapshots",
        "process_threads_closes",
        "process_threads_next_calls",
        "process_threads_bad_sizes",
        "process_threads_live_snapshots",
        "process_threads_foreign_seen",
    )

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def command(argv: list[str], directory: Path, label: str, timeout: int, *, env=None) -> subprocess.CompletedProcess:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, cwd=ROOT)
        (directory / f"{label}.stdout").write_text(result.stdout)
        (directory / f"{label}.stderr").write_text(result.stderr)
        assert result.returncode == 0, (argv, result.stderr)
        assert not result.stderr, result.stderr
        return result

    @classmethod
    def project(cls, frontend: str, target: str, directory: Path, *, btrcc: Path | None = None) -> Path:
        assert frontend in {"python", "btrc"}
        assert target in {"windows-x64", "windows-arm64"}
        assert os.environ.get("BTRC_NATIVE_HEADER_READER"), "explicit SDK reader required"
        assert directory.is_absolute(), "projection paths must be absolute"
        directory.mkdir(parents=True, exist_ok=False)
        source = NativeBindingPackage.write(
            FIXTURE / "WindowsProcessThreads.btrc",
            directory / "project",
            FIXTURE / "WindowsProcessThreadsProbe.h",
            cls.SYMBOLS,
        )
        generated, plan = directory / "Program.c", directory / "plan.json"
        if frontend == "python":
            compiler = [sys.executable, "-B", "-m", "src.compiler.python.main"]
        else:
            assert btrcc is not None and btrcc.is_file(), "allocated immutable compiler required"
            compiler = [str(btrcc)]
        flags = [
            "--strict-imports",
            "--no-cache",
            "--target",
            target,
            "--emit-link-plan",
            str(plan),
            str(source),
            "-o",
            str(generated),
        ]
        environment = {**os.environ, "BTRC_HOME": str(ROOT / "src"), "BTRC_CACHE_DIR": str(directory / "cache")}
        cls.command([*compiler, *flags], directory, "project", 120, env=environment)
        text = generated.read_text()
        includes = [RUNTIME / "Windows/ProcessThreads.h", directory / "project/WindowsProcessThreadsProbe.h"]
        mappings = {}
        for header in includes:
            assert f'#include "{header}"' in text, header
            destination = directory / "headers" / header.name
            destination.parent.mkdir(exist_ok=True)
            shutil.copyfile(header, destination)
            mappings[str(header)] = str(destination.relative_to(directory))
        for name in ("WindowsProcessThreadsProbe.c", "WindowsProcessThreadsFaults.h"):
            shutil.copyfile(FIXTURE / name, directory / name)
        files = [
            "Program.c",
            "plan.json",
            "WindowsProcessThreadsProbe.c",
            "WindowsProcessThreadsFaults.h",
            *mappings.values(),
        ]
        proof = {
            "frontend": frontend,
            "target": target,
            "compiler": compiler,
            "compiler_sha256": cls.digest(btrcc) if btrcc is not None and frontend == "btrc" else None,
            "files": {name: cls.digest(directory / name) for name in files},
            "header_mappings": mappings,
            "source": {
                str(path.relative_to(ROOT)): cls.digest(path)
                for path in (
                    RUNTIME / "ProcessThreads.btrc",
                    RUNTIME / "Windows/ProcessThreadsProvider.btrc",
                    RUNTIME / "btrc.toml",
                    FIXTURE / "WindowsProcessThreads.btrc",
                )
            },
        }
        receipt = directory / "projection.json"
        receipt.write_text(json.dumps(proof, indent=2) + "\n")
        return receipt

    @classmethod
    def run_native(cls, projection: Path, output: Path, *, cc: tuple[str, ...]) -> None:
        assert sys.platform == "win32", "requires actual Windows native execution"
        proof = json.loads(projection.read_text())
        architectures = {
            "arm64": "windows-arm64",
            "aarch64": "windows-arm64",
            "amd64": "windows-x64",
            "x86_64": "windows-x64",
        }
        assert platform.machine().lower() in architectures, platform.machine()
        expected = architectures[platform.machine().lower()]
        assert proof["target"] == expected, (proof["target"], platform.machine())
        directory = projection.parent
        for name, digest in proof["files"].items():
            path = directory / name
            assert path.resolve().is_relative_to(directory.resolve()) and cls.digest(path) == digest
        output.mkdir(parents=True, exist_ok=False)
        overlay = {
            "version": 0,
            "roots": [
                {"type": "file", "name": original, "external-contents": str((directory / relative).resolve())}
                for original, relative in proof["header_mappings"].items()
            ],
        }
        overlay_path = output / "headers.json"
        overlay_path.write_text(json.dumps(overlay, indent=2) + "\n")
        flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors", "-O2", "-I", str(directory / "headers")]
        generated_object, probe_object = output / "Program.o", output / "Probe.o"
        cls.command(
            [
                *cc,
                *flags,
                "-ivfsoverlay",
                str(overlay_path),
                "-include",
                str(directory / "WindowsProcessThreadsFaults.h"),
                "-c",
                str(directory / "Program.c"),
                "-o",
                str(generated_object),
            ],
            output,
            "generated-build",
            COMPILE_TIMEOUT,
        )
        cls.command(
            [*cc, *flags, "-c", str(directory / "WindowsProcessThreadsProbe.c"), "-o", str(probe_object)],
            output,
            "probe-build",
            COMPILE_TIMEOUT,
        )
        executable = output / "WindowsProcessThreads.exe"
        cls.command(
            [*cc, str(generated_object), str(probe_object), "-o", str(executable)], output, "link", COMPILE_TIMEOUT
        )
        ran = cls.command([str(executable)], output, "native", RUN_TIMEOUT)
        assert ran.stdout == "PASS: Windows process thread count\n", ran.stdout
        for name, digest in proof["files"].items():
            assert cls.digest(directory / name) == digest, name
