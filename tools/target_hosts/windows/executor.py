"""Standalone Windows target executor with gated launch and Job Object cleanup.

The CL-P1-17 protocol is provisional. The Python launch gate waits for its
assignment to a kill-on-close Job Object before creating the target process,
so the target cannot spawn descendants in Popen's assignment window.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

if __package__:
    from .bundle import TARGETS, digest, pe_machine
else:
    from bundle import TARGETS, digest, pe_machine


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", ctypes.c_uint32),
        ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t),
        ("process_limit", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority", ctypes.c_uint32),
        ("scheduling", ctypes.c_uint32),
    ]


class IOCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", BasicLimits),
        ("io", IOCounters),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in ("user", "kernel", "period_user", "period_kernel")] + [
        (name, ctypes.c_uint32) for name in ("faults", "total_processes", "active_processes", "terminated_processes")
    ]


class WindowsJob:
    """Own a Job Object and a named event that releases its assigned launch gate."""

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("Windows Job Objects require native Windows execution")
        self.api = self.bind()
        self.name = f"Local\\btrc-host-{uuid.uuid4().hex}"
        self.event = None
        self.job = self.api.CreateJobObjectW(None, None)
        self.require(self.job)
        self.event = self.api.CreateEventW(None, True, False, self.name)
        if not self.event:
            code = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(code)
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000 | 0x400  # KILL_ON_JOB_CLOSE | DIE_ON_UNHANDLED_EXCEPTION
        try:
            self.require(self.api.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except BaseException:
            self.close()
            raise

    @staticmethod
    def bind():
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        handle, dword, boolean, pointer = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p
        signatures = {
            "CreateJobObjectW": ([pointer, ctypes.c_wchar_p], handle),
            "CreateEventW": ([pointer, boolean, boolean, ctypes.c_wchar_p], handle),
            "OpenEventW": ([dword, boolean, ctypes.c_wchar_p], handle),
            "SetInformationJobObject": ([handle, ctypes.c_int, pointer, dword], boolean),
            "AssignProcessToJobObject": ([handle, handle], boolean),
            "TerminateJobObject": ([handle, dword], boolean),
            "QueryInformationJobObject": ([handle, ctypes.c_int, pointer, dword, pointer], boolean),
            "SetEvent": ([handle], boolean),
            "CloseHandle": ([handle], boolean),
            "WaitForSingleObject": ([handle, dword], dword),
            "ExitProcess": ([dword], None),
            "GetErrorMode": ([], dword),
            "SetErrorMode": ([dword], dword),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(api, name)
            function.argtypes, function.restype = arguments, result
        return api

    @staticmethod
    def require(value):
        if not value:
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process):
        self.require(self.api.AssignProcessToJobObject(self.job, int(process._handle)))

    def release(self):
        self.require(self.api.SetEvent(self.event))

    def terminate(self):
        self.require(self.api.TerminateJobObject(self.job, 0xB7C00001))

    def wait_empty(self, timeout_s=10):
        deadline = time.monotonic() + timeout_s
        while True:
            accounting = Accounting()
            self.require(
                self.api.QueryInformationJobObject(
                    self.job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
                )
            )
            if accounting.active_processes == 0:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("Windows Job Object still contains live processes after termination")
            time.sleep(0.01)

    def close(self):
        for attribute in ("event", "job"):
            if value := getattr(self, attribute, None):
                self.api.CloseHandle(value)
                setattr(self, attribute, None)

    @classmethod
    def gate(cls, name, request):
        api = cls.bind()
        event = api.OpenEventW(0x00100000, False, name)  # SYNCHRONIZE
        cls.require(event)
        try:
            if api.WaitForSingleObject(event, 30000) != 0:
                raise RuntimeError("parent did not release the Windows launch gate")
        finally:
            api.CloseHandle(event)
        specification = json.loads(Path(request).read_text(encoding="utf-8"))
        # The assigned Job Object and parent deadline bound this wait, including
        # target descendants. Its error mode is inherited by every target.
        api.SetErrorMode(api.GetErrorMode() | 0x0001 | 0x0002 | 0x8000)
        try:
            process = subprocess.run(
                specification["command"],
                cwd=specification["cwd"],
                env=merged_environment(os.environ, specification["env"]),
                check=False,
            )
        except OSError as error:
            failure = Path(specification["launch_error"])
            temporary = failure.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "stage": "CreateProcessW",
                        "message": str(error),
                        "winerror": getattr(error, "winerror", None),
                        "errno": error.errno,
                    }
                ),
                encoding="utf-8",
            )
            temporary.replace(failure)
            raise
        status_file = Path(specification["status"])
        temporary = status_file.with_suffix(".tmp")
        temporary.write_text(str(process.returncode & 0xFFFFFFFF), encoding="ascii")
        temporary.replace(status_file)
        # Preserve all 32 bits of NTSTATUS; sys.exit's signed conversion may truncate them.
        api.ExitProcess(process.returncode & 0xFFFFFFFF)


@dataclass(frozen=True)
class ExecutionRequest:
    program_id: str
    argv: tuple[str, ...] = ()
    stdin: bytes = b""
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 10
    cwd_policy: str = "isolated"


@dataclass(frozen=True)
class ExecutionResult:
    exit_status: int | None
    signal: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    duration_s: float
    provenance: dict


OUTPUT_LIMIT_BYTES = 1024 * 1024  # Per stream, independent of the target deadline.


class BoundedOutput:
    """Drain both pipes concurrently while retaining at most a fixed byte budget."""

    def __init__(self, process, limit=OUTPUT_LIMIT_BYTES):
        self.process, self.limit = process, limit
        self.buffers = [bytearray(), bytearray()]
        self.errors = []
        self.threads = []
        for index, stream in enumerate((process.stdout, process.stderr)):
            thread = threading.Thread(target=self.read, args=(index, stream), daemon=True)
            self.threads.append(thread)
            thread.start()

    def read(self, index, stream):
        try:
            while chunk := stream.read(65536):
                available = self.limit - len(self.buffers[index])
                self.buffers[index].extend(chunk[:available])
                if len(chunk) > available:
                    raise RuntimeError(
                        f"Windows target {'stdout' if index == 0 else 'stderr'} exceeded {self.limit} bytes"
                    )
        except Exception as error:
            self.errors.append(error)
        finally:
            stream.close()

    def communicate(self, timeout):
        deadline = time.monotonic() + timeout
        try:
            self.process.wait(timeout=timeout)
            for thread in self.threads:
                thread.join(max(0, deadline - time.monotonic()))
            if any(thread.is_alive() for thread in self.threads):
                raise subprocess.TimeoutExpired("Windows output drain", timeout)
        finally:
            if self.errors:
                raise self.errors[0]
        return tuple(bytes(buffer) for buffer in self.buffers)


def merged_environment(base, overrides):
    # Windows names are case-insensitive; an override must replace, not coexist.
    return {key.upper(): value for mapping in (base, overrides) for key, value in mapping.items()}


@contextmanager
def execution_workspace():
    directory = tempfile.mkdtemp(prefix="btrc host λ ")
    warnings = []
    primary = None
    try:
        yield Path(directory), warnings
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            shutil.rmtree(directory)
        except OSError as error:
            message = f"Windows temporary workspace cleanup failed at {directory}: {error}"
            if primary is not None:
                primary.add_note(message)
            else:
                warnings.append(message)


class WindowsNativeExecutor:
    CRASHES: ClassVar = {
        0xC0000005: (11, "access-violation"),
        0xC000001D: (4, "illegal-instruction"),
        0xC0000094: (8, "integer-divide-by-zero"),
        0xC00000FD: (11, "stack-overflow"),
        0x40000015: (6, "fatal-app-exit"),
        0xC0000409: (6, "fail-fast"),
    }

    def __init__(
        self, *, job_factory=WindowsJob, spawn=subprocess.Popen, clock=time.monotonic, capture_factory=BoundedOutput
    ):
        self.job_factory, self.spawn, self.clock = job_factory, spawn, clock
        self.capture_factory = capture_factory
        self.bundle = None

    def prepare(self, bundle_dir, label):
        bundle = Path(bundle_dir).resolve()
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema") != "btrc.windows-host-bundle/1":
            raise ValueError("unsupported Windows host bundle schema")
        target = manifest.get("target")
        if target not in TARGETS or manifest.get("pe_machine") != TARGETS[target][1]:
            raise ValueError("bundle target label and PE machine must identify the same supported architecture")
        programs = manifest["programs"]
        for name, record in programs.items():
            if record["executable"] != f"{name}.exe" or Path(name).name != name:
                raise ValueError("bundle executable mapping must be the exact program name plus .exe")
            executable = self.artifact(record["executable"], bundle=bundle)
            if (
                digest(executable.read_bytes()) != record["sha256"]
                or record.get("pe_machine") != manifest["pe_machine"]
                or pe_machine(executable) != manifest["pe_machine"]
            ):
                raise ValueError("bundle executable digest or PE machine does not match its manifest")
        if sys.platform == "win32":
            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.GetCurrentProcess.restype = ctypes.c_void_p
            api.IsWow64Process2.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint16),
                ctypes.POINTER(ctypes.c_uint16),
            ]
            api.IsWow64Process2.restype = ctypes.c_int
            process_machine, native_machine = ctypes.c_uint16(), ctypes.c_uint16()
            WindowsJob.require(
                api.IsWow64Process2(
                    api.GetCurrentProcess(), ctypes.byref(process_machine), ctypes.byref(native_machine)
                )
            )
            if native_machine.value != manifest["pe_machine"]:
                raise ValueError(
                    "bundle architecture must match native Windows hardware; emulated target runs are not evidence"
                )
        provenance = {
            "executor": "windows-native",
            "device": os.environ.get("COMPUTERNAME", "unrecorded"),
            "os_build": str(sys.getwindowsversion()) if sys.platform == "win32" else "unit-test transport",
            "toolchain": manifest.get("toolchain", {}),
            "label": label,
        }

        self.bundle, self.manifest, self.programs, self.provenance = bundle, manifest, programs, provenance

    def artifact(self, relative, *, bundle=None):
        bundle = self.bundle if bundle is None else bundle
        path = (bundle / relative).resolve()
        if Path(relative).suffix.lower() != ".exe" or path.suffix.lower() != ".exe":
            raise ValueError("bundle executables must use the .exe extension")
        if not path.is_file() or not path.is_relative_to(bundle):
            raise ValueError("bundle executable must be an existing file inside the bundle")
        return path

    def run(self, request):
        if self.bundle is None:
            raise RuntimeError("prepare a bundle before execution")
        if request.cwd_policy != "isolated" or not math.isfinite(request.timeout_s) or request.timeout_s <= 0:
            raise ValueError("use isolated cwd and a positive finite deadline")
        if any("\0" in value for value in request.argv) or any(
            not key or "\0" in key + value or "=" in key for key, value in request.env.items()
        ):
            raise ValueError("arguments and environment must be representable by CreateProcessW")
        started = self.clock()
        executable = self.artifact(self.programs[request.program_id]["executable"])
        with execution_workspace() as (workspace, cleanup_warnings):
            directory = workspace / "target cwd"
            directory.mkdir()
            control = workspace / "control"
            control.mkdir()
            job = self.job_factory()
            process = None
            capture = None
            timed_out = False
            original_error = None
            try:
                configuration = control / "request.json"
                status_file = control / "status.txt"
                launch_error_file = control / "launch-error.json"
                configuration.write_text(
                    json.dumps(
                        {
                            "command": [str(executable), *request.argv],
                            "cwd": str(directory),
                            "env": request.env,
                            "status": str(status_file),
                            "launch_error": str(launch_error_file),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                stdin_path = control / "stdin.bin"
                stdin_path.write_bytes(request.stdin)
                with stdin_path.open("rb") as stdin_file:
                    if digest(executable.read_bytes()) != self.programs[request.program_id]["sha256"]:
                        raise ValueError("bundle executable digest changed after prepare")
                    process = self.spawn(
                        [
                            getattr(sys, "_base_executable", sys.executable),
                            str(Path(__file__).resolve()),
                            "--gate",
                            job.name,
                            "--request",
                            str(configuration),
                        ],
                        cwd=str(directory),
                        stdin=stdin_file,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=(0x00000008 | 0x00000200) if sys.platform == "win32" else 0,
                    )
                capture = self.capture_factory(process)
                job.assign(process)
                job.release()
                while True:
                    remaining = request.timeout_s - (self.clock() - started)
                    if process.poll() is not None or remaining <= 0:
                        timed_out = process.poll() is None
                        job.terminate()
                        stdout, stderr = capture.communicate(timeout=10)
                        break
                    try:
                        stdout, stderr = capture.communicate(timeout=min(0.05, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        pass
                if not timed_out and not status_file.is_file():
                    if launch_error_file.is_file():
                        failure = json.loads(launch_error_file.read_text(encoding="utf-8"))
                        raise RuntimeError(
                            f"Windows target launch failed at {failure['stage']}: "
                            f"winerror={failure['winerror']} errno={failure['errno']}: {failure['message']}"
                        )
                    raise RuntimeError("Windows launch gate failed before reporting the target status")
                job.terminate()  # Also clean descendants of a program that returned normally.
                job.wait_empty()
                status = process.returncode & 0xFFFFFFFF  # The gate preserves the actual target exit code.
                signal, name = self.CRASHES.get(status, (None, None))
                return ExecutionResult(
                    None if timed_out or signal else status,
                    signal,
                    stdout,
                    stderr,
                    timed_out,
                    self.clock() - started,
                    {
                        **self.provenance,
                        "ntstatus": f"0x{status:08x}",
                        "crash": name,
                        "cleanup_warnings": cleanup_warnings,
                    },
                )
            except BaseException as error:
                original_error = error
                raise
            finally:
                cleanup_errors = []
                # Kill descendants before draining pipes, including on errors.
                # An unassigned gate must also be killed explicitly.
                actions = [job.terminate]
                if process is not None:
                    actions += [
                        lambda: process.kill() if process.poll() is None else None,
                        lambda: capture.communicate(timeout=10) if capture is not None else process.wait(timeout=10),
                    ]
                actions += [job.wait_empty, job.close]
                for action in actions:
                    try:
                        action()
                    except BaseException as error:
                        cleanup_errors.append(error)
                if cleanup_errors:
                    if original_error is None:
                        raise cleanup_errors[0]
                    for error in cleanup_errors:
                        original_error.add_note(f"Windows cleanup also failed: {error}")

    def close(self):
        self.bundle = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--request", required=True)
    args = parser.parse_args(argv)
    WindowsJob.gate(args.gate, args.request)


if __name__ == "__main__":
    main()
