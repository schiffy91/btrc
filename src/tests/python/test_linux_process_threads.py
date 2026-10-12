"""Real Linux dirent failure coverage without changing shared BackgroundJobs tests."""

import subprocess
import sys

import pytest

from src.tests.native_bindings import NativeBindingPackage
from src.tests.python.test_background_jobs_runtime import COMPILE_TIMEOUT, FIXTURE, RUN_TIMEOUT, _transpile

SYMBOLS = (
    "process_threads_fault_reset",
    "process_threads_fault_entries",
    "process_threads_fault_closes",
    "process_threads_fault_live",
    "PROCESS_THREADS_NORMAL",
    "PROCESS_THREADS_OPEN_ERROR",
    "PROCESS_THREADS_INITIAL_ERROR",
    "PROCESS_THREADS_PARTIAL_ERROR",
    "PROCESS_THREADS_STALE_ERRNO",
)


@pytest.mark.skipif(sys.platform != "linux", reason="requires native Linux /proc/self/task and dirent errno")
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_process_thread_count_read_errors(compiler, tmp_path, request, sanitized):
    NativeBindingPackage.require_reader()
    source = NativeBindingPackage.write(
        FIXTURE / "BackgroundJobsProcessThreads.btrc",
        tmp_path / "package",
        FIXTURE / "ProcessThreadFaultControl.h",
        SYMBOLS,
    )
    generated = tmp_path / f"process-threads-{compiler}.c"
    executable = tmp_path / f"process-threads-{compiler}"
    _transpile(compiler, generated, request, source, threads=False)
    sanitizer_flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    flags = [
        *sanitizer_flags,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        "-pthread",
        f"-I{FIXTURE}",
    ]
    objects = []
    for name, unit in (("generated", generated), ("probe", FIXTURE / "ProcessThreadFaults.c")):
        object_path = executable.with_suffix(f".{name}.o")
        hooks = ["-include", str(FIXTURE / "ProcessThreadFaults.h")] if name == "generated" else []
        result = subprocess.run(
            ["clang", *flags, *hooks, "-c", str(unit), "-o", str(object_path)],
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        assert result.returncode == 0, result.stderr
        objects.append(object_path)
    linked = subprocess.run(
        ["clang", *sanitizer_flags, *(str(path) for path in objects), "-pthread", "-o", str(executable)],
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert linked.returncode == 0, linked.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ProcessThreads initial EIO count=-1\nPASS: Linux process thread read errors\n"
    assert result.stderr == ""
