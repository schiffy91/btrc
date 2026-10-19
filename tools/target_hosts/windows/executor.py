"""The native Windows target executor, executor protocol 1 (CX-P1-07).

``src/tests/target_runner.py`` freezes the protocol and finds this class as
``windows-native``. The module imports nothing from the runner: its launch
gate runs this file as a script, once per program.

Admission. ``prepare(bundle_dir, label)`` reads the bundle's ``bundle.json``
(``btrc.target-bundle/1``) for the ``targets.toml`` row ``label``, which must
be the bundle's own row and a Windows row of `TARGETS`, and refuses a bundle
whose architecture this hardware would only emulate (``IsWow64Process2`` names
the native machine). Every built program's ``<program_id>.exe`` is copied into
a private staging directory and opened so that, on Windows, no other process
can write, replace or delete the copy while the executor holds it; the SHA-256
and PE machine are checked on the bytes read through that handle. Only those
staged copies are ever launched. Admission is atomic: a failure leaves the
executor as it was.

Launch. Each run creates a kill-on-close Job Object. ``Popen`` starts a Python
launch gate (this file, ``--gate``) that waits on a named event; the executor
assigns the gate to the job and only then releases it, so the program and
every descendant start inside the job. The gate starts the program from a
fresh, empty cwd with the staged stdin, waits, and exits with the program's
full 32-bit status.

Outcome. The result comes only from the operating system: the gate's process
exit code (the program's status; known crash NTSTATUS values map to a POSIX
signal number), the executor's own deadline, and the job's accounting. A gate
that ends having started no process in its job never launched the program,
which is an infrastructure error carrying the gate's diagnostics, never a
program outcome. No file decides anything: the request and stdin sit in a
control directory inside the staging root, never in or beside the program's
cwd, and nothing reads them back.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

if __package__:
    from .bundle import TARGETS, digest, pe_machine
else:
    from bundle import TARGETS, digest, pe_machine

BUNDLE_SCHEMA = "btrc.target-bundle/1"
BUNDLE_MANIFEST = "bundle.json"
PROGRAM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
OUTPUT_LIMIT_BYTES = 1024 * 1024  # Per stream, independent of the target deadline.
MACHINES = {0x8664: "x86_64", 0xAA64: "arm64"}


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

    def accounting(self):
        accounting = Accounting()
        self.require(
            self.api.QueryInformationJobObject(self.job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None)
        )
        return accounting

    def processes_started(self):
        """Every process the job ever held: the gate, then the program and its descendants."""
        return self.accounting().total_processes

    def wait_empty(self, timeout_s=10):
        deadline = time.monotonic() + timeout_s
        while self.accounting().active_processes:
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
                # The gate stays detached; targets use a windowless console process.
                # Explicit stdio handles survive the gate, and Job membership
                # still owns every descendant regardless of console flags.
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
                creationflags=(0x08000000 | 0x00000200) if sys.platform == "win32" else 0,
                check=False,
            )
        except OSError as error:
            # Nothing started in the job: the executor learns that from the job's
            # accounting and reports these words, which only the gate can have
            # written to the pipe, as the launch failure.
            sys.stderr.write(
                f"btrc Windows gate: CreateProcessW failed: winerror={getattr(error, 'winerror', None)} "
                f"errno={error.errno}: {error.strerror or error}\n"
            )
            sys.stderr.flush()
            api.ExitProcess(1)
            return
        # Preserve all 32 bits of NTSTATUS; sys.exit's signed conversion may truncate them.
        api.ExitProcess(process.returncode & 0xFFFFFFFF)


@dataclass(frozen=True)
class ExecutionRequest:
    """The runner's request (protocol 1); `check.py` builds these without importing the runner."""

    program_id: str
    argv: tuple[str, ...] = ()
    stdin: bytes = b""
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 10
    cwd_policy: str = "isolated"
    launch_mode: str = "process"
    app_roots: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionResult:
    exit_status: int | None
    signal: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    duration_s: float
    provenance: dict


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


def remove_tree(path):
    """``shutil.rmtree`` that clears a read-only bit and retries.

    A program may leave a read-only file (a Windows attribute) or directory (a
    POSIX mode) in its cwd; a plain rmtree then fails and leaks the directory.
    """

    def retry(function, failed, error):
        if not isinstance(error, PermissionError):
            raise error
        for target in (failed, os.path.dirname(failed)):
            with suppress(OSError):
                os.chmod(target, stat.S_IRWXU)
        if function in (os.rmdir, os.unlink, os.remove):
            function(failed)
        elif os.path.isdir(failed) and not os.path.islink(failed):
            shutil.rmtree(failed)
        else:
            os.unlink(failed)

    shutil.rmtree(path, onexc=retry)


@contextmanager
def private_directory(prefix, warnings, *, parent=None):
    """A fresh directory removed afterwards; a failed removal is a warning unless the body raised."""
    directory = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    primary = None
    try:
        yield directory
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            remove_tree(directory)
        except OSError as error:
            message = f"Windows temporary directory cleanup failed at {directory}: {error}"
            if primary is not None:
                primary.add_note(message)
            else:
                warnings.append(message)


class HeldArtifact:
    """A staged program that, on Windows, no process can write, replace or delete while it is held.

    The hold is a raw handle (no C runtime descriptor, so thousands of programs
    fit) that shares only reading: ``CreateProcessW``'s own open of the image,
    and `read`, need nothing more, while any open for writing or deletion, or a
    rename over the file, fails with a sharing violation until `close`. An
    existing writer would have made the hold itself fail, so the bytes `read`
    returns after the hold is taken are the bytes every launch maps. POSIX has
    no such share modes: there the copy is a 0500 file in a 0700 directory.
    """

    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x00000001
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80

    def __init__(self, path):
        self.path = Path(path)
        self.handle, self.api, self.closed = None, None, False
        if sys.platform == "win32":
            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.CreateFileW.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
            ]
            api.CreateFileW.restype = ctypes.c_void_p
            api.CloseHandle.argtypes = [ctypes.c_void_p]
            api.CloseHandle.restype = ctypes.c_int
            handle = api.CreateFileW(
                str(self.path),
                self.GENERIC_READ,
                self.FILE_SHARE_READ,
                None,
                self.OPEN_EXISTING,
                self.FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if handle is None or handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle, self.api = handle, api

    def read(self):
        if self.closed:
            raise ValueError(f"{self.path} is no longer held")
        return self.path.read_bytes()

    def close(self):
        if self.handle is not None:
            self.api.CloseHandle(self.handle)
            self.handle = None
        self.closed = True


class WindowsNativeExecutor:
    """Run a Windows bundle's programs natively, one Job Object per run (executor protocol 1)."""

    NAME = "windows-native"
    CWD_POLICIES: ClassVar[frozenset[str]] = frozenset({"isolated"})
    LAUNCH_MODES: ClassVar[frozenset[str]] = frozenset({"process"})
    CRASHES: ClassVar = {
        0xC0000005: (11, "access-violation"),
        0xC000001D: (4, "illegal-instruction"),
        0xC0000094: (8, "integer-divide-by-zero"),
        0xC00000FD: (11, "stack-overflow"),
        0x40000015: (6, "fatal-app-exit"),
        0xC0000409: (6, "fail-fast"),
    }

    def __init__(
        self,
        *,
        job_factory=WindowsJob,
        spawn=subprocess.Popen,
        clock=time.monotonic,
        capture_factory=BoundedOutput,
        hold=HeldArtifact,
        machine=None,
    ):
        self.job_factory, self.spawn, self.clock = job_factory, spawn, clock
        self.capture_factory, self.hold = capture_factory, hold
        self.machine = machine if machine is not None else self.native_machine
        self.label, self.staging, self.programs, self.provenance = None, None, {}, {}

    @staticmethod
    def native_machine():
        """This hardware's IMAGE_FILE_MACHINE value, whatever the interpreter's; None off Windows."""
        if sys.platform != "win32":
            return None
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
            api.IsWow64Process2(api.GetCurrentProcess(), ctypes.byref(process_machine), ctypes.byref(native_machine))
        )
        return native_machine.value

    @staticmethod
    def read_bundle(bundle, label):
        document = json.loads((bundle / BUNDLE_MANIFEST).read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("schema") != BUNDLE_SCHEMA:
            raise ValueError(f"{bundle} holds no {BUNDLE_SCHEMA} bundle")
        target = document.get("target")
        built_for = target.get("label") if isinstance(target, dict) else None
        if built_for != label:
            raise ValueError(f"the bundle was built for {built_for!r}, not {label!r}")
        if label not in TARGETS:
            raise ValueError(f"{label!r} is not a Windows row this executor runs ({', '.join(sorted(TARGETS))})")
        if not isinstance(document.get("programs"), dict):
            raise ValueError("the bundle's programs must be a table")
        return document

    @staticmethod
    def artifact(bundle, program_id, entry):
        """The bundle file a built program names, refusing any other launcher or location."""
        if not PROGRAM_ID.fullmatch(program_id) or not isinstance(entry, dict):
            raise ValueError(f"invalid bundle program {program_id!r}")
        if entry.get("artifact") != f"{program_id}.exe":
            raise ValueError("bundle executable mapping must be the exact program name plus .exe")
        if not SHA256.fullmatch(str(entry.get("sha256") or "")):
            raise ValueError(f"{program_id}: the bundle records no SHA-256")
        path = bundle / entry["artifact"]
        if path.resolve().suffix.lower() != ".exe":
            raise ValueError("bundle executables must use the .exe extension")
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(bundle):
            raise ValueError("bundle executable must be a regular file inside the bundle")
        return path

    def prepare(self, bundle_dir, label):
        bundle = Path(bundle_dir).resolve(strict=True)
        document = self.read_bundle(bundle, label)
        machine = TARGETS[label][1]
        native = self.machine()
        if native is not None and native != machine:
            raise ValueError(
                f"{label} is PE machine 0x{machine:04x} but this hardware is 0x{native:04x}; "
                "emulated target runs are not evidence"
            )
        staging = Path(tempfile.mkdtemp(prefix="btrc-windows-executor-"))
        programs = {}
        try:
            (staging / "programs").mkdir()
            for program_id, entry in sorted(document["programs"].items()):
                if not isinstance(entry, dict) or entry.get("status") != "built":
                    continue
                source = self.artifact(bundle, program_id, entry)
                staged = staging / "programs" / source.name
                shutil.copyfile(source, staged)
                os.chmod(staged, stat.S_IRUSR | stat.S_IXUSR)
                programs[program_id] = held = self.hold(staged)
                # Read once held: no writer can change these bytes before close, so they are what every run launches.
                data = held.read()
                if digest(data) != entry["sha256"]:
                    raise ValueError(f"{program_id}: the staged copy does not match the bundle's SHA-256")
                if pe_machine(data) != machine:
                    raise ValueError(f"{program_id}: the executable is not PE machine 0x{machine:04x} ({label})")
        except BaseException:
            for held in programs.values():
                with suppress(Exception):
                    held.close()
            with suppress(OSError):
                remove_tree(staging)
            raise
        self.close()
        self.label, self.staging, self.programs = label, staging, programs
        self.provenance = {
            "executor": self.NAME,
            "device": self.device(native),
            "os_build": self.os_build(),
            "toolchain": document.get("toolchain", {}),
            "label": label,
        }

    @staticmethod
    def device(native):
        """A device class (the processor model and architecture), never a host name or serial."""
        if native is None:
            return "unit-test transport"
        return f"{platform.processor() or 'unrecorded processor'} ({MACHINES.get(native, f'0x{native:04x}')})"

    @staticmethod
    def os_build():
        if sys.platform != "win32":
            return "unit-test transport"
        return f"Windows {platform.version()} {platform.win32_edition() or ''}".strip()

    def check_request(self, request):
        if request.program_id not in self.programs:
            raise ValueError(f"unknown program_id: {request.program_id}")
        timeout = request.timeout_s
        if (
            request.cwd_policy not in self.CWD_POLICIES
            or isinstance(timeout, bool)
            or not isinstance(timeout, int | float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("use isolated cwd and a positive finite deadline")
        if getattr(request, "launch_mode", "process") not in self.LAUNCH_MODES or getattr(request, "app_roots", ()):
            raise ValueError("the Windows executor launches ordinary processes, with no app roots")
        if any("\0" in value for value in request.argv) or any(
            not key or "\0" in key + value or "=" in key for key, value in request.env.items()
        ):
            raise ValueError("arguments and environment must be representable by CreateProcessW")

    def run(self, request):
        if self.staging is None:
            raise RuntimeError("prepare a bundle before execution")
        self.check_request(request)
        started = self.clock()
        executable = self.programs[request.program_id].path
        cleanup_warnings = []
        with (
            private_directory("btrc host λ ", cleanup_warnings) as directory,
            private_directory("control-", cleanup_warnings, parent=self.staging) as control,
        ):
            job = self.job_factory()
            process = None
            capture = None
            timed_out = False
            original_error = None
            try:
                configuration = control / "request.json"
                configuration.write_text(
                    json.dumps(
                        {"command": [str(executable), *request.argv], "cwd": str(directory), "env": request.env},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                stdin_path = control / "stdin.bin"
                stdin_path.write_bytes(request.stdin)
                with stdin_path.open("rb") as stdin_file:
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
                job.terminate()  # Also clean descendants of a program that returned normally.
                job.wait_empty()
                # The gate is the job's first process; a second one is the program.
                if job.processes_started() < 2:
                    diagnostics = stderr.decode("utf-8", "replace").strip() or "no diagnostics"
                    if timed_out:
                        raise RuntimeError(
                            f"the Windows launch gate had not started {request.program_id} when its "
                            f"{request.timeout_s:g}s deadline expired: {diagnostics}"
                        )
                    raise RuntimeError(
                        f"the Windows launch gate exited with 0x{process.returncode & 0xFFFFFFFF:08x} "
                        f"without starting {request.program_id}: {diagnostics}"
                    )
                status = process.returncode & 0xFFFFFFFF  # The gate exits with the target's own status.
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
                        # Draining the pipes again re-raises the error being handled.
                        if error is not original_error:
                            cleanup_errors.append(error)
                if cleanup_errors:
                    if original_error is None:
                        raise cleanup_errors[0]
                    for error in cleanup_errors:
                        original_error.add_note(f"Windows cleanup also failed: {error}")

    def close(self):
        for held in self.programs.values():
            with suppress(Exception):
                held.close()
        if self.staging is not None:
            with suppress(OSError):
                remove_tree(self.staging)
        self.label, self.staging, self.programs = None, None, {}


TARGET_EXECUTORS = {WindowsNativeExecutor.NAME: "WindowsNativeExecutor"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--request", required=True)
    args = parser.parse_args(argv)
    WindowsJob.gate(args.gate, args.request)


if __name__ == "__main__":
    main()
