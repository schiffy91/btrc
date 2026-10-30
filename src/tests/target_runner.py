"""Build and run the shared language corpus for one compilation target (Stage 25, CL-P1-17).

For each corpus program (``corpus_files.language_test_files``) and frontend
(``reference``: the Python compiler's API; ``selfhost``: the ``btrcc`` named by
``--btrcc`` or ``BTRC_TEST_BTRCC``), the runner transpiles with ``--target
<label>``, compiles the C through ``tools.native_plan.TargetToolchain`` with
strict C11 flags (the Windows compatibility overlay on the gnu rows), and
writes the executable into a bundle. An executor then runs the bundle on the
target, serially, and each program's output is compared with its
``expected/<Stem>.stdout``, ``.stderr`` and ``.warnings`` goldens exactly as
``src/tests/runner.py`` compares them. Like ``runner.py``, every compile is
uncached and uses no prebuilt stdlib archive, so each program's result
stands alone; since CL-P1-15 keys every cache by the row's label, a cached
mode would be sound.

    python -m src.tests.target_runner --target macos-aarch64 --frontend both --executor local
    python -m src.tests.target_runner --target windows-x86_64 --frontend both --compile-only --bundle out/x64
    python -m src.tests.target_runner --execute-bundle out/x64 --executor windows-native

Applicability. A program a target cannot build or run is *restricted*
(deliberately excluded there) or *missing* (not yet implemented there), with
the reason and a citation, never silently dropped. The verdict comes from
``BTRC_TEST_REQUIRES`` directives, ``src/tests/fixtures/target-applicability.toml``
and the ``corpus.*`` topic cells of ``docs/design/platform-inventory.toml``.

Outputs, under ``build/target-runs/<label>/`` unless ``--output`` says otherwise:
``<frontend>/<program>.{stdout,stderr,json}`` per program, ``junit.xml``,
``target-run.json`` (schema ``btrc.target-run/1``: per-frontend
passed/failed/restricted/missing counts and every program's result) and
``ledger.jsonl``, the ``tools.qualification`` records ``TargetRunAdapter``
derives from it (validated before the run reports success).

Executor protocol, version 1 (frozen 2026-10-17)
------------------------------------------------
The Windows (``CX-P1-07``), iOS (``CX-P1-08``) and Android (``CX-P1-09``) lanes
build against this contract; changing it needs their agreement.

An executor is a class with three methods. The runner calls them from one
thread, in the order prepare, run (once per program, serially), close:

``prepare(bundle_dir, label) -> None``
    Admit one bundle (``bundle.json``, below) for the ``targets.toml`` row
    ``label``. Refuse a bundle for another row, or for an architecture this
    executor would only emulate: emulation is not native evidence. Verify every
    artifact's SHA-256 against ``bundle.json``. Admission is atomic: it commits
    every program or raises and leaves the executor as it was -- never a
    partial set.
    *Digest to launch:* stage the admitted bytes where the target cannot replace
    them (a private copy, an installed package) and launch only those bytes,
    verifying the digest of the staged copy, not only of the bundle path.

``run(request: ExecutionRequest) -> ExecutionResult``
    Execute one admitted program once and return its outcome. An
    infrastructure failure -- a transport, launch, cleanup or protocol error --
    raises; it is never encoded as a program outcome.

``close() -> None``
    Release staged artifacts, guests and devices this executor acquired.
    Idempotent.

Optional members: ``granted_capabilities() -> frozenset[str]``, called after
``prepare``, names the ``BTRC_TEST_REQUIRES`` host facilities the prepared
target provides (``loopback-listener``); without it the applicability
manifest's ``[[capabilities]]`` grants for the executor's name apply.
``CWD_POLICIES`` and ``LAUNCH_MODES`` (frozensets; default ``{"isolated"}`` and
``{"process"}``) declare what ``run`` accepts; the runner never sends a policy
or mode an executor does not declare. A ``from_options(options)`` classmethod
receives the ``--executor-option NAME=VALUE`` pairs; without one the class is
constructed as ``Class(**options)``.

``ExecutionRequest`` (``program_id, argv, stdin, env, timeout_s, cwd_policy,
launch_mode, app_roots``):

- ``program_id`` keys ``bundle.json``'s ``programs`` (``[A-Za-z0-9][A-Za-z0-9_-]*``).
- ``argv`` is the arguments after ``argv[0]``; ``argv[0]`` is the executor's.
- ``stdin`` is bytes, delivered unmodified, then end of file.
- ``env`` holds overrides merged onto the target's ordinary process
  environment. Names match ``[A-Za-z_][A-Za-z0-9_]*``; values are NUL-free. An
  executor refuses names it reserves for itself.
- ``timeout_s`` (positive, finite) bounds the program's execution. Launch,
  installation and cleanup are bounded separately, never unbounded.
- ``cwd_policy``: ``isolated`` (a fresh, empty, writable directory used by this
  run alone and removed afterwards) or ``bundle`` (the staged artifact's
  directory).
- ``launch_mode``: ``process`` (an ordinary process, a simulator spawn, an adb
  shell) or ``app`` (the target's application model: an installed app on a
  fresh container).
- ``app_roots``: app mode only; names from ``{files, cache}``, no duplicates.
  The executor resolves each inside the launched app's own context, checks
  that it belongs to that app, and hands every root to the program as one
  structured value at the host entry, never through ambient environment; the
  host-side encoding is the mobile host owners' (CX-P2-41). The result's
  ``provenance["app_roots"]`` maps each requested name, and no other, to a
  distinct absolute path; the runner refuses a result that does not.

``ExecutionResult`` (``exit_status, signal, stdout, stderr, timed_out,
duration_s, provenance``). The runner accepts any object with these
attributes (the host spikes return their own dataclasses) and validates it:

- ``exit_status``: the exit code of a normal exit (0-255 on POSIX, the full
  unsigned 32-bit status on Windows), else ``None``.
- ``signal``: the terminating signal of an abnormal exit (Windows maps known
  crash NTSTATUS values to the POSIX number), else ``None``.
- ``timed_out``: only when the executor's deadline expired. Then
  ``exit_status`` is ``None``; ``signal`` may name how the executor stopped
  the program. An ordinary exit 124 or 137 is never a timeout. Otherwise
  exactly one of ``exit_status`` and ``signal`` is set.
- ``stdout``/``stderr``: the raw bytes, never decoded, newline-translated or
  truncated (an executor that bounds memory raises instead).
- ``duration_s``: wall time, finite and non-negative.
- ``provenance``: JSON-serializable, with at least ``executor``, ``device``,
  ``os_build`` and ``toolchain``. It names device classes or emulator serials,
  never host names, user names or hardware serial numbers.

The outcome comes from the operating system -- a wait status, a process or
Job Object exit code, a supervisor out of the program's reach -- never from a
file the program can write. Requests, staged stdin, ready/start handshakes and
status markers live outside the target's cwd; a marker the program could
write may corroborate the observed status, never decide it.

Registry. ``--executor`` takes ``local`` (`LocalExecutor`), a ``module:Class``
spec, or a ``TARGET_CAPABILITIES`` name (``windows-native``, ``ios-simulator``,
``android-emulator``, ...). A name is resolved by importing
``tools.target_hosts.<platform>.executor``, where ``<platform>`` is the name's
first word: its ``TARGET_EXECUTORS`` mapping (name to ``Class`` or
``module:Class``) if it has one, else the one class named for the capability
(``windows-native`` -> ``WindowsNativeExecutor``, case-insensitively). Adding
an executor therefore needs no edit here, and the executor module imports
nothing from this one unless it wants to.

Bundle (``bundle.json``, schema ``btrc.target-bundle/1``): ``target`` (label,
triple, operating_system, architecture), ``source_revision``,
``source_dirty``, ``toolchain`` and ``compilers`` provenance, and
``programs``: program id to ``{source, frontend, status}`` -- ``built`` with
``artifact`` (a file name in the bundle directory: ``<program_id>``, plus
``.exe`` on Windows), ``sha256``, ``requires``, the pinned ``request``
(``argv``, ``stdin_base64``, ``env``, ``timeout_s``, ``cwd_policy``,
``launch_mode``, ``app_roots``) and ``expected`` outcome (exit status 0, the
golden files' SHA-256, ``PASS`` in stdout, universal-newline comparison); or
``failed``, ``restricted`` or ``missing`` with ``phase``, ``reason`` and
``cites``. ``--execute-bundle`` admits a bundle only when its revision is this
checkout's and every pin, recomputed from this checkout's goldens, is equal;
executors then receive only requests built from those pins. A Windows program
may also record `companion`, with exactly `artifact` and `sha256`; its file is
`<artifact>.btrc-supervisor.exe`. The Windows executor stages, verifies and holds
both images before accepting the program. Other targets reject this field.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import contextlib
import datetime
import fnmatch
import hashlib
import importlib
import io
import json
import math
import os
import platform
import re
import shlex
import shutil
import signal as process_signal
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Protocol

from src.compiler.python import Compiler, CompilerOptions
from src.compiler.python.abi.generated import TARGET_ROWS, GeneratedTargetRow
from src.compiler.python.abi.hosted import TargetRepository
from src.tests.corpus_files import language_test_files
from src.tests.native_build import NativeCorpusBuild
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT, TOOL_TIMEOUT, TRANSPILE_TIMEOUT
from src.tests.runner import _GPU_BUILD, _GPU_DIR, _python_warnings, _selfhost_warnings, expected_warnings
from src.tests.runner_capabilities import (
    HOST_CAPABILITIES,
    TARGET_CAPABILITIES,
    darwin_gpu_flags,
    declared_capabilities,
    loopback_listener_error,
)
from tools.host_c_compiler import HostCCompiler
from tools.native_plan import NativePlanError, RuntimeObjects, TargetToolchain
from tools.qualification.adapters import HostProvenance, TargetRunAdapter
from tools.qualification.schema import LedgerDocument, Provenance

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "src" / "tests"
APPLICABILITY = CORPUS / "fixtures" / "target-applicability.toml"
INVENTORY = REPO / "docs" / "design" / "platform-inventory.toml"
OUTPUT_ROOT = REPO / "build" / "target-runs"

PROTOCOL_VERSION = 1
BUNDLE_SCHEMA = "btrc.target-bundle/1"
REPORT_SCHEMA = TargetRunAdapter.SCHEMA
APPLICABILITY_SCHEMA = "btrc.target-applicability/1"
FRONTENDS = ("reference", "selfhost")
STATUSES = TargetRunAdapter.STATUSES
# The flags the strict-C11 matrix and the Windows lane hold every generated unit to.
# zig cc treats -O2 as a release mode and defines NDEBUG, which compiles out every
# assert a corpus program checks with; -UNDEBUG keeps them live on every toolchain.
STRICT_CFLAGS = ("-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2", "-UNDEBUG")
# Retained per stream by the local executor; more is an infrastructure error.
OUTPUT_LIMIT_BYTES = 16 * 1024 * 1024
PROGRAM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
CWD_POLICIES = frozenset({"isolated", "bundle"})
LAUNCH_MODES = frozenset({"process", "app"})
APP_ROOTS = frozenset({"files", "cache"})
# Every corpus program prints this when it passes (runner.py asserts it too).
PASS_MARKER = "PASS"


class ExecutorProtocolError(RuntimeError):
    """An executor broke the frozen protocol, or a bundle failed admission."""


@dataclass(frozen=True)
class ExecutionRequest:
    """One execution of one admitted program (protocol version 1)."""

    program_id: str
    argv: tuple[str, ...] = ()
    stdin: bytes = b""
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: float = RUN_TIMEOUT
    cwd_policy: str = "isolated"
    launch_mode: str = "process"
    app_roots: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.program_id, str) or not PROGRAM_ID.fullmatch(self.program_id):
            raise ValueError(f"program_id must match {PROGRAM_ID.pattern}: {self.program_id!r}")
        if not isinstance(self.argv, tuple) or not all(
            isinstance(value, str) and "\0" not in value for value in self.argv
        ):
            raise ValueError("argv must be a tuple of NUL-free strings")
        if not isinstance(self.stdin, bytes):
            raise ValueError("stdin must be bytes")
        if not isinstance(self.env, Mapping) or not all(
            isinstance(name, str) and ENVIRONMENT_NAME.fullmatch(name) and isinstance(value, str) and "\0" not in value
            for name, value in self.env.items()
        ):
            raise ValueError("env must map names matching [A-Za-z_][A-Za-z0-9_]* to NUL-free strings")
        # A plain dict: executors serialize it (the Windows gate writes it as JSON).
        object.__setattr__(self, "env", dict(self.env))
        timeout = self.timeout_s
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int | float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout_s must be a positive finite number of seconds")
        if self.cwd_policy not in CWD_POLICIES:
            raise ValueError(f"cwd_policy must be one of {sorted(CWD_POLICIES)}: {self.cwd_policy!r}")
        if self.launch_mode not in LAUNCH_MODES:
            raise ValueError(f"launch_mode must be one of {sorted(LAUNCH_MODES)}: {self.launch_mode!r}")
        if not isinstance(self.app_roots, tuple) or not set(self.app_roots) <= APP_ROOTS:
            raise ValueError(f"app_roots must be a tuple of names from {sorted(APP_ROOTS)}")
        if len(set(self.app_roots)) != len(self.app_roots):
            raise ValueError(f"app_roots names a root twice: {self.app_roots}")
        if self.app_roots and self.launch_mode != "app":
            raise ValueError("app_roots exist only in the app launch mode")

    def pins(self) -> dict[str, Any]:
        """The request as a bundle pins it."""

        return {
            "argv": list(self.argv),
            "stdin_base64": base64.b64encode(self.stdin).decode("ascii"),
            "env": dict(sorted(self.env.items())),
            "timeout_s": self.timeout_s,
            "cwd_policy": self.cwd_policy,
            "launch_mode": self.launch_mode,
            "app_roots": list(self.app_roots),
        }

    @classmethod
    def from_pins(cls, program_id: str, pins: Mapping[str, Any]) -> ExecutionRequest:
        return cls(
            program_id=program_id,
            argv=tuple(pins["argv"]),
            stdin=base64.b64decode(pins["stdin_base64"], validate=True),
            env=dict(pins["env"]),
            timeout_s=pins["timeout_s"],
            cwd_policy=pins["cwd_policy"],
            launch_mode=pins["launch_mode"],
            app_roots=tuple(pins["app_roots"]),
        )


@dataclass(frozen=True)
class ExecutionResult:
    """What one execution observed (protocol version 1)."""

    exit_status: int | None
    signal: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    duration_s: float
    provenance: dict[str, Any]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "exit_status",
        "signal",
        "stdout",
        "stderr",
        "timed_out",
        "duration_s",
        "provenance",
    )
    PROVENANCE: ClassVar[tuple[str, ...]] = ("executor", "device", "os_build", "toolchain")

    @classmethod
    def adopt(cls, value: object, request: ExecutionRequest) -> ExecutionResult:
        """Validate any executor's result object and return it as this type."""

        missing = [name for name in cls.FIELDS if not hasattr(value, name)]
        if missing:
            raise ExecutorProtocolError(f"the executor's result lacks {', '.join(missing)}")
        fields = {name: getattr(value, name) for name in cls.FIELDS}
        for name in ("exit_status", "signal"):
            number = fields[name]
            if number is not None and (isinstance(number, bool) or not isinstance(number, int) or number < 0):
                raise ExecutorProtocolError(f"{name} must be a non-negative integer or None, not {number!r}")
        if fields["signal"] == 0:
            raise ExecutorProtocolError("signal 0 is not a terminating signal")
        for name in ("stdout", "stderr"):
            if not isinstance(fields[name], bytes):
                raise ExecutorProtocolError(f"{name} must be the raw bytes, not {type(fields[name]).__name__}")
        if not isinstance(fields["timed_out"], bool):
            raise ExecutorProtocolError("timed_out must be a bool")
        duration = fields["duration_s"]
        if isinstance(duration, bool) or not isinstance(duration, int | float) or not math.isfinite(duration):
            raise ExecutorProtocolError("duration_s must be a finite number")
        if duration < 0:
            raise ExecutorProtocolError("duration_s must not be negative")
        if fields["timed_out"]:
            if fields["exit_status"] is not None:
                raise ExecutorProtocolError("a timed-out execution has no exit status")
        elif (fields["exit_status"] is None) == (fields["signal"] is None):
            raise ExecutorProtocolError("an execution that did not time out has exactly one of exit_status and signal")
        provenance = fields["provenance"]
        if not isinstance(provenance, Mapping):
            raise ExecutorProtocolError("provenance must be a mapping")
        lacking = [name for name in cls.PROVENANCE if name not in provenance]
        if lacking:
            raise ExecutorProtocolError(f"provenance lacks {', '.join(lacking)}")
        try:
            provenance = json.loads(json.dumps(dict(provenance)))
        except (TypeError, ValueError) as error:
            raise ExecutorProtocolError(f"provenance is not JSON-serializable: {error}") from None
        cls.check_app_roots(provenance, request)
        fields["provenance"] = provenance
        return cls(**fields)

    @staticmethod
    def check_app_roots(provenance: Mapping[str, Any], request: ExecutionRequest) -> None:
        roots = provenance.get("app_roots")
        if not request.app_roots:
            if roots:
                raise ExecutorProtocolError("the executor reported app roots the request did not ask for")
            return
        if not isinstance(roots, Mapping) or set(roots) != set(request.app_roots):
            raise ExecutorProtocolError(f"provenance.app_roots must name exactly {sorted(request.app_roots)}")
        paths = list(roots.values())
        if not all(isinstance(path, str) and os.path.isabs(path) for path in paths):
            raise ExecutorProtocolError("every app root must be an absolute path")
        if len(set(paths)) != len(paths):
            raise ExecutorProtocolError("two app roots name the same path")

    def summary(self) -> dict[str, Any]:
        """The result without its streams, for a program's JSON log."""

        return {
            "exit_status": self.exit_status,
            "signal": self.signal,
            "timed_out": self.timed_out,
            "duration_s": round(self.duration_s, 6),
            "stdout_bytes": len(self.stdout),
            "stderr_bytes": len(self.stderr),
            "stdout_sha256": hashlib.sha256(self.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(self.stderr).hexdigest(),
            "provenance": self.provenance,
        }


class TargetExecutor(Protocol):
    """The executor shape the module docstring freezes."""

    def prepare(self, bundle_dir: Path, label: str) -> None: ...

    def run(self, request: ExecutionRequest) -> ExecutionResult: ...

    def close(self) -> None: ...


class ExecutorRegistry:
    """Executor names to ``module:Class`` specs, discovered by importing the host packages."""

    BUILTIN: ClassVar[Mapping[str, str]] = MappingProxyType({"local": "src.tests.target_runner:LocalExecutor"})
    PACKAGE = "tools.target_hosts"
    ROOT = REPO / "tools" / "target_hosts"
    METHODS = ("prepare", "run", "close")

    def __init__(self, root: Path = ROOT, package: str = PACKAGE) -> None:
        self.root = root
        self.package = package

    @staticmethod
    def platform_of(name: str) -> str:
        return name.split("-", 1)[0]

    def names(self) -> tuple[str, ...]:
        """``local`` and every capability name whose host package has an executor module."""

        discovered = sorted(
            name for name in TARGET_CAPABILITIES if (self.root / self.platform_of(name) / "executor.py").is_file()
        )
        return (*self.BUILTIN, *discovered)

    def spec(self, name: str) -> str:
        """The ``module:Class`` an executor name resolves to."""

        if ":" in name:
            return name
        if name in self.BUILTIN:
            return self.BUILTIN[name]
        if name not in TARGET_CAPABILITIES:
            known = ", ".join(sorted({*self.BUILTIN, *TARGET_CAPABILITIES}))
            raise LookupError(f"unknown executor {name!r}: expected a module:Class spec or one of {known}")
        module_name = f"{self.package}.{self.platform_of(name)}.executor"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            raise LookupError(f"no executor module for {name!r}: {module_name} ({error})") from error
        declared = getattr(module, "TARGET_EXECUTORS", None)
        if declared is not None:
            if not isinstance(declared, Mapping) or name not in declared:
                raise LookupError(f"{module_name}.TARGET_EXECUTORS does not register {name!r}")
            target = declared[name]
            return target if ":" in target else f"{module_name}:{target}"
        wanted = name.replace("-", "") + "executor"
        matches = sorted(
            attribute
            for attribute, value in vars(module).items()
            if isinstance(value, type) and value.__module__ == module.__name__ and attribute.lower() == wanted
        )
        if len(matches) != 1:
            raise LookupError(f"{module_name} defines no single executor class for {name!r} (looked for {wanted})")
        return f"{module_name}:{matches[0]}"

    def load(self, name: str) -> type:
        spec = self.spec(name)
        module_name, _, class_name = spec.partition(":")
        try:
            value = getattr(importlib.import_module(module_name), class_name, None)
        except ModuleNotFoundError as error:
            raise LookupError(f"executor {spec} cannot be imported: {error}") from error
        if not isinstance(value, type) or not all(callable(getattr(value, method, None)) for method in self.METHODS):
            raise LookupError(f"executor {spec} is not a class with prepare, run and close")
        return value

    def create(self, name: str, options: Mapping[str, str] | None = None) -> TargetExecutor:
        executor_class = self.load(name)
        factory = getattr(executor_class, "from_options", None)
        if callable(factory):
            return factory(dict(options or {}))
        return executor_class(**dict(options or {}))


class BoundedCapture:
    """Drain a child's stdout and stderr concurrently, retaining at most a fixed number of bytes each."""

    STREAMS = ("stdout", "stderr")
    LIMIT = OUTPUT_LIMIT_BYTES

    def __init__(self, process: subprocess.Popen[bytes], limit: int | None = None) -> None:
        self.limit = self.LIMIT if limit is None else limit
        self.buffers = (bytearray(), bytearray())
        self.overflowed: list[str] = []
        self.errors: list[BaseException] = []
        self.threads = [
            threading.Thread(target=self.drain, args=(index, stream), daemon=True)
            for index, stream in enumerate((process.stdout, process.stderr))
        ]
        for thread in self.threads:
            thread.start()

    def drain(self, index: int, stream: io.BufferedReader) -> None:
        # Keep reading past the limit, so the child never blocks on a full pipe.
        try:
            with stream:
                while chunk := stream.read1(65536):
                    room = self.limit - len(self.buffers[index])
                    if len(chunk) > room and self.STREAMS[index] not in self.overflowed:
                        self.overflowed.append(self.STREAMS[index])
                    self.buffers[index].extend(chunk[: max(room, 0)])
        except BaseException as error:
            self.errors.append(error)

    def join(self, timeout: float) -> tuple[bytes, bytes]:
        deadline = time.monotonic() + timeout
        for thread in self.threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self.threads):
            raise RuntimeError("the program's output pipes stayed open after its process group was killed")
        if self.errors:
            raise RuntimeError(f"reading the program's output failed: {self.errors[0]}")
        if self.overflowed:
            raise RuntimeError(f"the program's {' and '.join(self.overflowed)} exceeded {self.limit} bytes")
        return bytes(self.buffers[0]), bytes(self.buffers[1])


class LocalExecutor:
    """Run a bundle built for this host's own row as ordinary child processes.

    Each program runs in a new session (its own process group), from an empty
    cwd, with stdin staged in a separate private directory. Its exit, signal or
    the deadline comes from the wait status; the whole process group is killed
    when the program returns or times out, so no descendant outlives a run.
    """

    NAME = "local"
    CWD_POLICIES: ClassVar[frozenset[str]] = frozenset({"isolated", "bundle"})
    LAUNCH_MODES: ClassVar[frozenset[str]] = frozenset({"process"})

    def __init__(self) -> None:
        self.label: str | None = None
        self.programs: dict[str, Path] = {}
        self.staging: Path | None = None
        self.toolchain: dict[str, Any] = {}

    def prepare(self, bundle_dir: Path | str, label: str) -> None:
        host = TargetRepository.host()
        if host is None or label != host.label:
            raise ValueError(
                f"the local executor runs only this host's row ({host.label if host else 'none'}), not {label}"
            )
        bundle = TargetBundle.load(Path(bundle_dir))
        if bundle.label != label:
            raise ValueError(f"the bundle was built for {bundle.label}, not {label}")
        staging = Path(tempfile.mkdtemp(prefix="btrc-local-executor-"))
        programs: dict[str, Path] = {}
        try:
            for program_id, entry in bundle.built():
                if bundle.companion(program_id) is not None:
                    raise ValueError("Windows companion bundles require the windows-native executor")
                source = bundle.artifact_path(program_id)
                staged = staging / source.name
                shutil.copyfile(source, staged)
                staged.chmod(0o500)
                if TargetBundle.digest(staged) != entry["sha256"]:
                    raise ValueError(f"{program_id}: the staged artifact does not match its bundle digest")
                programs[program_id] = staged
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        self.close()
        self.label, self.programs, self.staging, self.toolchain = label, programs, staging, bundle.toolchain

    def granted_capabilities(self) -> frozenset[str]:
        return frozenset() if loopback_listener_error() else frozenset({"loopback-listener"})

    def provenance(self) -> dict[str, Any]:
        return {
            "executor": self.NAME,
            "device": platform.machine() or "unknown",
            "os_build": f"{platform.system()} {platform.release()}",
            "toolchain": self.toolchain,
            "label": self.label,
        }

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        if self.staging is None:
            raise RuntimeError("prepare a bundle before running")
        if request.program_id not in self.programs:
            raise ValueError(f"unknown program_id: {request.program_id}")
        if request.cwd_policy not in self.CWD_POLICIES or request.launch_mode not in self.LAUNCH_MODES:
            raise ValueError(f"the local executor runs {sorted(self.LAUNCH_MODES)} in {sorted(self.CWD_POLICIES)} cwds")
        executable = self.programs[request.program_id]
        started = time.monotonic()
        with (
            tempfile.TemporaryDirectory(prefix="btrc-local-run-") as workspace,
            tempfile.TemporaryDirectory(prefix="btrc-local-control-") as control,
        ):
            stdin_path = Path(control) / "stdin"
            stdin_path.write_bytes(request.stdin)
            with stdin_path.open("rb") as stdin:
                process = subprocess.Popen(
                    [str(executable), *request.argv],
                    cwd=workspace if request.cwd_policy == "isolated" else str(executable.parent),
                    env={**os.environ, **request.env},
                    stdin=stdin,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=os.name == "posix",
                )
            capture = BoundedCapture(process)
            timed_out = False
            try:
                try:
                    process.wait(timeout=request.timeout_s)
                except subprocess.TimeoutExpired:
                    timed_out = True
            finally:
                self.kill(process)
                process.wait(timeout=10)
                stdout, stderr = capture.join(timeout=10)
        returncode = process.returncode
        if timed_out:
            exit_status, signal = None, None
        elif returncode < 0:
            exit_status, signal = None, -returncode
        else:
            exit_status, signal = returncode, None
        return ExecutionResult(
            exit_status, signal, stdout, stderr, timed_out, time.monotonic() - started, self.provenance()
        )

    @staticmethod
    def kill(process: subprocess.Popen[bytes]) -> None:
        """Kill the program's whole process group, so no descendant outlives the run."""

        if os.name == "posix":
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, process_signal.SIGKILL)
        elif process.poll() is None:
            process.kill()

    def close(self) -> None:
        if self.staging is not None:
            shutil.rmtree(self.staging, ignore_errors=True)
        self.label, self.programs, self.staging = None, {}, None


class TargetRows:
    """The targets.toml rows the runner builds for, and their toolchains."""

    BY_LABEL: ClassVar[Mapping[str, GeneratedTargetRow]] = MappingProxyType({row.label: row for row in TARGET_ROWS})

    @classmethod
    def row(cls, label: str) -> GeneratedTargetRow:
        if label not in cls.BY_LABEL:
            raise ValueError(f"unknown target {label!r}: expected one of {', '.join(sorted(cls.BY_LABEL))}")
        return cls.BY_LABEL[label]

    @staticmethod
    def is_host(row: GeneratedTargetRow) -> bool:
        return row == TargetRepository.host()

    @staticmethod
    def suffix(row: GeneratedTargetRow) -> str:
        return ".exe" if row.operating_system == "windows" else ""

    @classmethod
    def toolchain(cls, row: GeneratedTargetRow) -> TargetToolchain:
        """The row's toolchain; the host row keeps the corpus runner's configured C compiler."""

        if not cls.is_host(row):
            return TargetToolchain(row)
        command = HostCCompiler.configured()
        if len(command) != 1:
            raise NativePlanError(f"the target runner needs BTRC_CC to name one executable, not {command}")
        return TargetToolchain(row, cc=command[0], cxx=HostCCompiler.default_cxx())

    @staticmethod
    def describe(toolchain: TargetToolchain, cflags: Sequence[str]) -> dict[str, Any]:
        """The toolchain a bundle records: drivers, arguments, flags and the driver's version line."""

        try:
            completed = subprocess.run(
                [*toolchain.drivers["cc"], "--version"],
                capture_output=True,
                text=True,
                timeout=TOOL_TIMEOUT,
                check=False,
            )
            version = completed.stdout.splitlines()[0] if completed.returncode == 0 and completed.stdout else None
        except (OSError, subprocess.TimeoutExpired):
            version = None
        return {
            "cc": list(toolchain.drivers["cc"]),
            "arguments": list(toolchain.arguments),
            "generated_arguments": list(toolchain.generated_arguments),
            "cflags": list(cflags),
            "libraries": toolchain.runtime_libraries(),
            "version": version,
        }


@dataclass(frozen=True)
class CorpusProgram:
    """One runnable corpus program, by its corpus-relative path."""

    source: str

    @property
    def path(self) -> Path:
        return CORPUS / self.source

    @property
    def topic(self) -> str:
        return self.source.split("/", 1)[0]

    @property
    def stem(self) -> str:
        return Path(self.source).stem

    @property
    def log_name(self) -> str:
        return self.source.removesuffix(".btrc")

    def program_id(self, frontend: str) -> str:
        identifier = f"{frontend}-{self.log_name.replace('/', '-')}"
        if not PROGRAM_ID.fullmatch(identifier):
            raise ValueError(f"{self.source} has no valid program id")
        return identifier

    @property
    def stdout_golden(self) -> Path:
        return self.path.parent / "expected" / f"{self.stem}.stdout"

    @property
    def stderr_golden(self) -> Path:
        return self.path.parent / "expected" / f"{self.stem}.stderr"

    def requires(self) -> frozenset[str]:
        return declared_capabilities(self.path)

    @classmethod
    def select(cls, patterns: Sequence[str] = ()) -> list[CorpusProgram]:
        """Every corpus program, or those whose corpus path matches one of `patterns`."""

        programs = [cls(path.replace(os.sep, "/")) for path in language_test_files(CORPUS)]
        if not patterns:
            return programs
        chosen = [program for program in programs if any(fnmatch.fnmatchcase(program.source, p) for p in patterns)]
        if not chosen:
            raise ValueError(f"no corpus program matches {list(patterns)}")
        return chosen


@dataclass(frozen=True)
class GoldenExpectation:
    """What a passing run prints, read from the program's goldens as runner.py reads them."""

    stdout: bytes
    stderr: bytes

    @classmethod
    def of(cls, program: CorpusProgram) -> GoldenExpectation:
        stderr = program.stderr_golden.read_bytes() if program.stderr_golden.is_file() else b""
        return cls(program.stdout_golden.read_bytes(), stderr)

    def pins(self) -> dict[str, Any]:
        return {
            "exit_status": 0,
            "signal": None,
            "timed_out": False,
            "stdout_sha256": hashlib.sha256(self.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(self.stderr).hexdigest(),
            "stdout_contains": PASS_MARKER,
            "newlines": "universal",
        }

    @staticmethod
    def text(data: bytes) -> str:
        """Bytes as runner.py sees them: UTF-8 text with universal newlines."""

        return io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", newline=None).read()

    @staticmethod
    def first_difference(expected: str, actual: str) -> str:
        expected_lines, actual_lines = expected.splitlines(), actual.splitlines()
        for number, (want, got) in enumerate(zip(expected_lines, actual_lines), start=1):
            if want != got:
                return f"line {number}: expected {want!r}, got {got!r}"
        number = min(len(expected_lines), len(actual_lines)) + 1
        return f"line {number}: expected {len(expected_lines)} lines, got {len(actual_lines)}"

    def mismatch(self, result: ExecutionResult) -> str | None:
        """Why `result` is not a pass, in runner.py's order, or None."""

        if result.timed_out:
            return f"timed out after {result.duration_s:.1f}s"
        if result.signal is not None:
            return f"terminated by signal {result.signal}"
        if result.exit_status != 0:
            return f"exited with status {result.exit_status}"
        try:
            stdout, stderr = self.text(result.stdout), self.text(result.stderr)
        except UnicodeDecodeError as error:
            return f"the program's output is not UTF-8: {error}"
        if PASS_MARKER not in stdout:
            return f"no {PASS_MARKER} in stdout"
        golden = self.text(self.stdout)
        if stdout != golden:
            return f"stdout differs from the golden at {self.first_difference(golden, stdout)}"
        golden = self.text(self.stderr)
        if stderr != golden:
            return f"stderr differs from the golden at {self.first_difference(golden, stderr)}"
        return None


@dataclass(frozen=True)
class Verdict:
    """Why a program is not built or not run on a target."""

    status: str  # restricted | missing
    scope: str  # build: never compiled; run: compiled, never executed
    reason: str
    cites: str


@dataclass(frozen=True)
class Facility:
    """A runtime library some programs' emitted C needs, and the rows that have it."""

    name: str
    header: str
    targets: frozenset[str]
    status: str
    reason: str
    cites: str


class InventoryCells:
    """The ``corpus.*`` rows of the P0 inventory: one cell per corpus topic and target slice."""

    def __init__(self, path: Path = INVENTORY) -> None:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        self.cells: dict[tuple[str, str], Mapping[str, Any]] = {}
        self.rows: set[str] = set()
        for row in document.get("rows", ()):
            identifier = row.get("id", "")
            self.rows.add(identifier)
            for name, cell in row.items():
                if isinstance(cell, Mapping):
                    self.cells[(identifier, name)] = cell

    def cell(self, row: str, slice_name: str) -> Mapping[str, Any] | None:
        return self.cells.get((row, slice_name))

    def topic_verdict(self, topic: str, label: str) -> Verdict | None:
        """A whole corpus topic the inventory classifies as restricted or missing on the row's slice."""

        slice_name = TargetRunAdapter.ROW_SLICES.get(label)
        cell = self.cell(f"corpus.{topic}", slice_name) if slice_name else None
        if cell is None:
            return None
        cites = f"corpus.{topic}@{slice_name}"
        reason = cell.get("reason") or f"the inventory classifies corpus.{topic} on {slice_name}"
        if cell.get("parity") == "os-restricted":
            return Verdict("restricted", "build", reason, cites)
        if cell.get("parity") == "missing" or cell.get("implementation") in {"missing", "source-only"}:
            return Verdict("missing", "build", reason, cites)
        return None


class ApplicabilityManifest:
    """``target-applicability.toml``: which corpus programs each target builds and runs, and why not."""

    SCHEMA = APPLICABILITY_SCHEMA
    STATUSES = ("restricted", "missing")
    SCOPES = ("build", "run")
    CONTRACT_CITE = re.compile(r"(?P<path>[A-Za-z0-9_./-]+)#(?P<anchor>[A-Za-z0-9_.-]+)")
    INVENTORY_CITE = re.compile(r"(?P<row>[A-Za-z0-9_.]+)@(?P<slice>[A-Za-z0-9_-]+)")

    def __init__(self, document: Mapping[str, Any], inventory: InventoryCells, corpus: Sequence[str]) -> None:
        self.inventory = inventory
        if document.get("schema") != self.SCHEMA:
            raise ValueError(f"the applicability manifest's schema is not {self.SCHEMA}")
        unknown = set(document) - {"schema", "programs", "capabilities", "facilities"}
        if unknown:
            raise ValueError(f"unknown applicability field(s): {', '.join(sorted(unknown))}")
        self.programs = [
            self.program_entry(entry, index, corpus) for index, entry in enumerate(document.get("programs", ()))
        ]
        self.check_overlaps(corpus)
        self.capabilities: dict[str, dict[str, Any]] = {}
        for index, entry in enumerate(document.get("capabilities", ())):
            where = f"capabilities[{index}]"
            self.fields(entry, where, {"name", "executors", "reason", "cites"})
            if entry["name"] not in HOST_CAPABILITIES:
                raise ValueError(f"{where}: {entry['name']!r} is not a BTRC_TEST_REQUIRES host capability")
            self.cite(entry["cites"], where)
            self.capabilities[entry["name"]] = {**entry, "executors": frozenset(entry["executors"])}
        self.facilities: list[Facility] = []
        for index, entry in enumerate(document.get("facilities", ())):
            where = f"facilities[{index}]"
            self.fields(entry, where, {"name", "header", "targets", "status", "reason", "cites"})
            self.check_status(entry["status"], where)
            self.check_targets(entry["targets"], where)
            self.cite(entry["cites"], where)
            self.facilities.append(
                Facility(
                    entry["name"],
                    entry["header"],
                    frozenset(entry["targets"]),
                    entry["status"],
                    entry["reason"],
                    entry["cites"],
                )
            )

    @classmethod
    def load(cls, path: Path = APPLICABILITY, inventory: Path = INVENTORY) -> ApplicabilityManifest:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls(document, InventoryCells(inventory), [program.source for program in CorpusProgram.select()])

    @staticmethod
    def fields(entry: object, where: str, allowed: set[str], optional: frozenset[str] = frozenset()) -> None:
        if not isinstance(entry, Mapping):
            raise ValueError(f"{where}: expected a table")
        unknown, lacking = set(entry) - allowed, allowed - optional - set(entry)
        if unknown or lacking:
            raise ValueError(f"{where}: unknown {sorted(unknown)}, lacking {sorted(lacking)}")
        if "reason" in entry and (not isinstance(entry["reason"], str) or not entry["reason"].strip()):
            raise ValueError(f"{where}: every exclusion states its reason")

    def check_status(self, status: object, where: str) -> None:
        if status not in self.STATUSES:
            raise ValueError(f"{where}: status must be one of {self.STATUSES}, not {status!r}")

    @staticmethod
    def check_targets(targets: object, where: str) -> None:
        if not isinstance(targets, list) or not all(target in TargetRows.BY_LABEL for target in targets):
            raise ValueError(f"{where}: targets must be targets.toml labels")

    def cite(self, cites: object, where: str) -> None:
        """A citation names an inventory cell (``corpus.strings@windows-x64``) or a contract (``path#anchor``)."""

        if not isinstance(cites, str):
            raise ValueError(f"{where}: cites must be text")
        if match := self.INVENTORY_CITE.fullmatch(cites):
            if self.inventory.cell(match["row"], match["slice"]) is None:
                raise ValueError(f"{where}: {cites} names no platform-inventory cell")
            return
        if match := self.CONTRACT_CITE.fullmatch(cites):
            if not (REPO / match["path"]).is_file():
                raise ValueError(f"{where}: {match['path']} does not exist")
            return
        raise ValueError(f"{where}: cite an inventory cell (row@slice) or a contract (path#anchor), not {cites!r}")

    def program_entry(self, entry: object, index: int, corpus: Sequence[str]) -> dict[str, Any]:
        where = f"programs[{index}]"
        allowed = {"paths", "targets", "frontends", "status", "scope", "reason", "cites"}
        self.fields(entry, where, allowed, optional=frozenset({"frontends"}))
        paths = entry["paths"]
        if not isinstance(paths, list) or not paths or not all(isinstance(path, str) for path in paths):
            raise ValueError(f"{where}: paths must list corpus paths or globs")
        for path in paths:
            if not any(fnmatch.fnmatchcase(source, path) for source in corpus):
                raise ValueError(f"{where}: {path!r} matches no corpus program")
        self.check_status(entry["status"], where)
        self.check_targets(entry["targets"], where)
        if entry["scope"] not in self.SCOPES:
            raise ValueError(f"{where}: scope must be one of {self.SCOPES}")
        frontends = entry.get("frontends", list(FRONTENDS))
        if not frontends or not set(frontends) <= set(FRONTENDS):
            raise ValueError(f"{where}: frontends must name {FRONTENDS}")
        self.cite(entry["cites"], where)
        return {**entry, "targets": frozenset(entry["targets"]), "frontends": frozenset(frontends)}

    @staticmethod
    def matches(entry: Mapping[str, Any], source: str) -> bool:
        return any(fnmatch.fnmatchcase(source, path) for path in entry["paths"])

    def check_overlaps(self, corpus: Sequence[str]) -> None:
        """Refuse two entries that would both decide one program, target and frontend."""

        for source in corpus:
            claimed: dict[tuple[str, str], int] = {}
            for index, entry in enumerate(self.programs):
                if not self.matches(entry, source):
                    continue
                for slot in ((target, frontend) for target in entry["targets"] for frontend in entry["frontends"]):
                    if slot in claimed:
                        raise ValueError(
                            f"programs[{claimed[slot]}] and programs[{index}] both decide {source} on {slot}"
                        )
                    claimed[slot] = index

    def program_verdict(self, program: CorpusProgram, label: str, frontend: str) -> Verdict | None:
        """The manifest's, then the inventory's, verdict on one program, target and frontend."""

        for entry in self.programs:
            if label in entry["targets"] and frontend in entry["frontends"] and self.matches(entry, program.source):
                return Verdict(entry["status"], entry["scope"], entry["reason"], entry["cites"])
        return self.inventory.topic_verdict(program.topic, label)

    def capability_verdict(self, capability: str, executor: str, granted: frozenset[str] | None) -> Verdict | None:
        """Why `executor` cannot run a program that declares `capability`, or None."""

        if capability in TARGET_CAPABILITIES:
            if capability == executor or (granted is not None and capability in granted):
                return None
            return Verdict(
                "restricted",
                "run",
                f"requires {capability}, which only the {capability} executor provides",
                "src/tests/runner_capabilities.py#TARGET_CAPABILITIES",
            )
        entry = self.capabilities.get(capability)
        # A prepared executor that reports its facilities is authoritative; otherwise the manifest grants.
        if granted is not None:
            allowed = capability in granted
        else:
            allowed = entry is not None and executor in entry["executors"]
        if allowed:
            return None
        reason = f"requires {capability}, which the {executor} executor does not grant"
        if entry is not None:
            return Verdict("restricted", "run", f"{reason}: {entry['reason']}", entry["cites"])
        return Verdict("restricted", "run", reason, "src/tests/runner_capabilities.py#HOST_CAPABILITIES")

    def facility(self, name: str) -> Facility | None:
        return next((facility for facility in self.facilities if facility.name == name), None)


class ComputeRuntime:
    """Where a host build finds the @gpu compute runtime, exactly as the corpus runner looks."""

    HEADER = "btrc_gpu_compute_internal.h"
    FACILITY = "compute-runtime"
    COMPILE_PREFIXES = ("-I", "-D", "-isystem")

    @classmethod
    def split(cls, flags: Sequence[str]) -> tuple[list[str], list[str]]:
        """Separate preprocessor flags (for the compile) from library flags (for the link)."""

        return NativeCorpusBuild.split_dependency_flags(flags)

    @classmethod
    def host_flags(cls) -> tuple[tuple[str, ...], tuple[str, ...]] | str:
        """(compile flags, link flags) for the host row, or why the runtime is unavailable."""

        if not os.path.isfile(os.path.join(_GPU_BUILD, "libbtrc_gpu.a")):
            return "Compute runtime not built (run make gpu)"
        compile_flags, link_flags = [f"-I{_GPU_DIR}"], [f"-L{_GPU_BUILD}", "-lbtrc_gpu"]
        dependency_cflags, dependency_ldflags = os.environ.get("GPU_CFLAGS"), os.environ.get("GPU_LDFLAGS")
        if bool(dependency_cflags) != bool(dependency_ldflags):
            return "WebGPU toolchain is unavailable: GPU_CFLAGS and GPU_LDFLAGS must be set together"
        if dependency_cflags and dependency_ldflags:
            compile_flags += shlex.split(dependency_cflags)
            link_flags += shlex.split(dependency_ldflags)
        elif platform.system() == "Darwin":
            flags, error = darwin_gpu_flags()
            if error:
                return error
            extra_compile, extra_link = cls.split(flags)
            compile_flags += extra_compile
            link_flags += extra_link
        elif platform.system() == "Linux":
            link_flags += ["-lwgpu_native", "-lpthread"]
        else:
            return f"WebGPU toolchain is unavailable on {platform.system()}: set GPU_CFLAGS and GPU_LDFLAGS"
        return tuple(compile_flags), tuple(link_flags)

    @staticmethod
    def verdict(
        row: GeneratedTargetRow, host: tuple[tuple[str, ...], tuple[str, ...]] | str, facility: Facility | None
    ) -> Verdict | tuple[tuple[str, ...], tuple[str, ...]]:
        """The flags a dispatching program links the runtime with on `row`, or why it cannot.

        `host` is `host_flags()` for the host row (ignored for any other row).
        """

        cites = facility.cites if facility else "src/tests/runner.py#_gcc_flags"
        if TargetRows.is_host(row):
            return Verdict("missing", "build", host, cites) if isinstance(host, str) else host
        if facility is None or row.label not in facility.targets:
            reason = facility.reason if facility else "no compute runtime is built for this row"
            return Verdict(facility.status if facility else "missing", "build", reason, cites)
        # A row the manifest lists as having a cross-built runtime needs its link flags first.
        raise BuildFailure("facility", f"the runner has no link flags yet for {row.label}'s compute runtime")


class BuildFailure(Exception):
    """One phase of a program's build failed."""

    def __init__(self, phase: str, reason: str) -> None:
        super().__init__(reason)
        self.phase = phase


@dataclass
class BuildResult:
    """One program, built (or not) through one frontend for one target."""

    program: str
    frontend: str
    program_id: str
    status: str  # built | failed | restricted | missing
    phase: str | None = None
    reason: str | None = None
    cites: str | None = None
    artifact: str | None = None
    sha256: str | None = None
    duration_s: float = 0.0
    companion: dict[str, str] | None = None

    def entry(
        self, request: ExecutionRequest | None, expected: Mapping[str, Any] | None, requires: Sequence[str]
    ) -> dict:
        """This result as a bundle.json program entry."""

        entry: dict[str, Any] = {"source": self.program, "frontend": self.frontend, "status": self.status}
        if self.status == "built":
            entry.update(
                artifact=self.artifact,
                sha256=self.sha256,
                requires=sorted(requires),
                request=request.pins() if request else None,
                expected=dict(expected or {}),
            )
            if self.companion is not None:
                entry["companion"] = dict(self.companion)
        else:
            entry.update(phase=self.phase, reason=self.reason, cites=self.cites)
        return entry

    @classmethod
    def from_entry(cls, program_id: str, entry: Mapping[str, Any]) -> BuildResult:
        return cls(
            program=entry["source"],
            frontend=entry["frontend"],
            program_id=program_id,
            status=entry["status"],
            phase=entry.get("phase"),
            reason=entry.get("reason"),
            cites=entry.get("cites"),
            artifact=entry.get("artifact"),
            sha256=entry.get("sha256"),
            companion=entry.get("companion"),
        )


@dataclass(frozen=True)
class BuildConfiguration:
    """Everything one target build needs that is the same for every program."""

    label: str
    work: Path
    bundle: Path
    btrcc: Path | None
    cflags: tuple[str, ...]
    compute: tuple[tuple[str, ...], tuple[str, ...]] | str
    facility: Facility | None


class ProgramBuilder:
    """Turn corpus programs into target executables through either frontend."""

    def __init__(self, configuration: BuildConfiguration, toolchain: TargetToolchain) -> None:
        self.configuration = configuration
        self.row = TargetRows.row(configuration.label)
        self.toolchain = toolchain
        self.compiler = Compiler()
        # The reference compiler is one in-process object: compiles take turns.
        self.reference_lock = threading.Lock()

    def build(self, program: CorpusProgram, frontend: str) -> BuildResult:
        started = time.monotonic()
        program_id = program.program_id(frontend)
        try:
            result = self.build_steps(program, frontend, program_id)
        except BuildFailure as failure:
            result = BuildResult(program.source, frontend, program_id, "failed", failure.phase, str(failure)[-8000:])
        result.duration_s = time.monotonic() - started
        return result

    def build_steps(self, program: CorpusProgram, frontend: str, program_id: str) -> BuildResult:
        if frontend == "reference":
            c_source, warnings = self.transpile_reference(program)
        else:
            c_source, warnings = self.transpile_selfhost(program)
        native = c_source if isinstance(c_source, NativeCorpusBuild) else None
        if native is not None:
            c_source = "\n".join(native.sources())
        golden = expected_warnings(str(program.path))
        if warnings != golden:
            raise BuildFailure(
                "warnings", f"{frontend} warnings differ from the warning golden: expected {golden}, got {warnings}"
            )
        compile_flags: tuple[str, ...] = ()
        link_flags: tuple[str, ...] = ()
        if ComputeRuntime.HEADER in c_source:
            verdict = ComputeRuntime.verdict(self.row, self.configuration.compute, self.configuration.facility)
            if isinstance(verdict, Verdict):
                return BuildResult(
                    program.source, frontend, program_id, verdict.status, "facility", verdict.reason, verdict.cites
                )
            compile_flags, link_flags = verdict
        work = self.configuration.work / frontend
        work.mkdir(parents=True, exist_ok=True)
        c_path = work / f"{program_id}.c"
        object_path = c_path.with_suffix(".o")
        c_path.write_text(c_source, encoding="utf-8")
        artifact = self.configuration.bundle / f"{program_id}{TargetRows.suffix(self.row)}"
        if native is not None:
            try:
                report = native.build(
                    artifact,
                    cc=self.toolchain.drivers["cc"],
                    compile_flags=[*self.configuration.cflags, *compile_flags],
                    link_flags=[*self.configuration.cflags, *link_flags],
                    report=work / f"{program_id}.native-build.json",
                )
            except (NativePlanError, OSError, subprocess.TimeoutExpired) as error:
                raise BuildFailure("native-build", str(error)) from error
            c_path.unlink()
            return BuildResult(
                program.source,
                frontend,
                program_id,
                "built",
                artifact=artifact.name,
                sha256=TargetBundle.digest(artifact),
                companion={"artifact": Path(report.auxiliary["path"]).name, "sha256": report.auxiliary["sha256"]}
                if report.auxiliary is not None
                else None,
            )
        self.run_tool(
            self.toolchain.compile_command(
                c_path, object_path, generated=True, flags=[*self.configuration.cflags, *compile_flags]
            ),
            "compile",
        )
        # A separately compiled runtime object the program retains is its own
        # unit, built without the generated-unit overlay and linked whole.
        runtime_objects = RuntimeObjects.selected([c_source])
        runtime_paths = []
        for index, source in enumerate(RuntimeObjects.sources(runtime_objects)):
            runtime_path = work / f"{program_id}.runtime-{index}.o"
            self.run_tool(
                self.toolchain.compile_command(source, runtime_path, generated=False, flags=self.configuration.cflags),
                "compile",
            )
            runtime_paths.append(runtime_path)
        self.run_tool(
            [
                *self.toolchain.drivers["cc"],
                *self.toolchain.arguments,
                str(object_path),
                *(str(path) for path in runtime_paths),
                *link_flags,
                *RuntimeObjects.library_flags(runtime_objects, self.row.operating_system),
                *self.toolchain.runtime_libraries(),
                "-o",
                str(artifact),
            ],
            "link",
        )
        c_path.unlink()
        object_path.unlink()
        for path in runtime_paths:
            path.unlink()
        return BuildResult(
            program.source, frontend, program_id, "built", artifact=artifact.name, sha256=TargetBundle.digest(artifact)
        )

    def transpile_reference(self, program: CorpusProgram) -> tuple[str | NativeCorpusBuild, list[str]]:
        options = CompilerOptions(
            map_stdlib_positions=True, use_cache=False, use_ast_cache=False, target=self.row.label
        )
        path = str(program.path)
        try:
            with self.reference_lock:
                result = self.compiler.compile(program.path.read_text(encoding="utf-8"), path, options)
        except Exception as error:
            raise BuildFailure("transpile", f"the reference compiler raised {error!r}") from error
        if result.failure is not None:
            raise BuildFailure("transpile", f"compile failed: {result.failure.kind.value}: {result.failure.message}")
        if result.analyzed is not None and result.analyzed.errors:
            raise BuildFailure("transpile", f"analyzer errors: {result.analyzed.errors}")
        if result.c_source is None:
            raise BuildFailure("transpile", "the compiler emitted no C")
        source = NativeCorpusBuild.from_result(
            result, self.configuration.work / "reference" / program.program_id("reference")
        )
        return source, _python_warnings(result, path)

    def transpile_selfhost(self, program: CorpusProgram) -> tuple[str | NativeCorpusBuild, list[str]]:
        btrcc = self.configuration.btrcc
        if btrcc is None:
            raise BuildFailure("transpile", "no self-hosted compiler: pass --btrcc or set BTRC_TEST_BTRCC")
        directory = self.configuration.work / "selfhost" / program.program_id("selfhost")
        directory.mkdir(parents=True, exist_ok=True)
        artifact = NativeCorpusBuild(directory / "program.c", directory / "program.json", (str(btrcc),))
        try:
            completed = subprocess.run(
                [
                    str(btrcc),
                    "--no-cache",
                    "--target",
                    self.row.label,
                    str(program.path),
                    "-o",
                    str(artifact.primary),
                    "--emit-link-plan",
                    str(artifact.plan),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=TRANSPILE_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BuildFailure("transpile", f"btrcc did not finish: {error}") from error
        if completed.returncode != 0 or not artifact.primary.is_file():
            raise BuildFailure("transpile", f"btrcc exited {completed.returncode}: {completed.stderr[:4000]}")
        return (artifact if artifact.required() else artifact.primary.read_text(encoding="utf-8")), _selfhost_warnings(
            completed.stderr
        )

    @staticmethod
    def run_tool(command: list[str], phase: str) -> None:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=C_COMPILE_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BuildFailure(phase, f"{command[0]} did not finish: {error}") from error
        if completed.returncode != 0:
            # The first diagnostics name the cause; later ones mostly follow from it.
            output = (completed.stderr or completed.stdout).strip()
            raise BuildFailure(phase, f"{phase} exited {completed.returncode}: {output[:4000]}")


class TargetBundle:
    """``bundle.json`` and the artifacts beside it."""

    SCHEMA = BUNDLE_SCHEMA
    MANIFEST = "bundle.json"
    PROGRAM_STATUSES = ("built", "failed", "restricted", "missing")

    def __init__(self, directory: Path, document: dict[str, Any]) -> None:
        self.directory = directory
        self.document = document

    @property
    def label(self) -> str:
        return self.document["target"]["label"]

    @property
    def programs(self) -> dict[str, dict[str, Any]]:
        return self.document["programs"]

    @property
    def toolchain(self) -> dict[str, Any]:
        return self.document.get("toolchain", {})

    @staticmethod
    def digest(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def built(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for program_id, entry in sorted(self.programs.items()):
            if entry["status"] == "built":
                yield program_id, entry

    def artifact_path(self, program_id: str) -> Path:
        name = self.programs[program_id]["artifact"]
        if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}:
            raise ValueError(f"{program_id}: an artifact is a file name in the bundle directory, not {name!r}")
        path = self.directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"{program_id}: {name} is not a regular file in the bundle")
        return path

    def companion(self, program_id: str):
        from tools.target_hosts.windows.bundle import CompanionArtifact

        return CompanionArtifact.read(self.directory, program_id, self.programs[program_id], self.label)

    @classmethod
    def load(cls, directory: Path) -> TargetBundle:
        directory = directory.resolve(strict=True)
        document = json.loads((directory / cls.MANIFEST).read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("schema") != cls.SCHEMA:
            raise ValueError(f"{directory} holds no {cls.SCHEMA} bundle")
        if document.get("target", {}).get("label") not in TargetRows.BY_LABEL:
            raise ValueError("the bundle names no targets.toml row")
        programs = document.get("programs")
        if not isinstance(programs, dict):
            raise ValueError("the bundle's programs must be a table")
        bundle = cls(directory, document)
        for program_id, entry in programs.items():
            if (
                not PROGRAM_ID.fullmatch(program_id)
                or not isinstance(entry, dict)
                or entry.get("status") not in cls.PROGRAM_STATUSES
            ):
                raise ValueError(f"invalid bundle program {program_id!r}")
            if entry["status"] == "built":
                bundle.artifact_path(program_id)
                bundle.companion(program_id)
                if not SHA256.fullmatch(entry.get("sha256") or ""):
                    raise ValueError(f"{program_id}: no SHA-256")
        return bundle

    @classmethod
    def prepare_directory(cls, directory: Path) -> None:
        """Empty a bundle directory this runner wrote before, never anything else."""

        if directory.exists():
            if any(directory.iterdir()) and not (directory / cls.MANIFEST).is_file():
                raise ValueError(f"{directory} is not empty and holds no bundle; refusing to replace it")
            shutil.rmtree(directory)
        directory.mkdir(parents=True)

    def write(self) -> None:
        staged = self.directory / f"{self.MANIFEST}.partial"
        staged.write_text(json.dumps(self.document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        staged.replace(self.directory / self.MANIFEST)


class SourceRevision:
    """The checkout a bundle is built from and executed against."""

    @staticmethod
    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments], cwd=REPO, capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=False
        )
        if completed.returncode != 0:
            raise RuntimeError(f"git {' '.join(arguments)} failed: {completed.stderr.strip()}")
        return completed.stdout.strip()

    @classmethod
    def current(cls) -> str:
        return cls.git("rev-parse", "HEAD")

    @classmethod
    def dirty(cls) -> bool:
        return bool(cls.git("status", "--porcelain", "--untracked-files=no"))


class TargetEnvironment:
    """The process environment one target build runs in.

    Caches and compiler state live in run-private directories (one target per
    directory, so nothing reads another target's artifacts), btrcc finds its
    data root explicitly, and a cross row names its triple and sysroot for the
    native reader as the ABI fixture does.
    """

    PRIVATE = ("cache", "state", "zig")

    def __init__(self, row: GeneratedTargetRow, toolchain: TargetToolchain, scratch: Path) -> None:
        self.row = row
        self.toolchain = toolchain
        self.scratch = scratch

    def discard(self) -> None:
        """Remove the run-private caches and state, keeping anything else under the scratch directory."""

        for name in self.PRIVATE:
            shutil.rmtree(self.scratch / name, ignore_errors=True)

    def variables(self) -> dict[str, str]:
        state = self.scratch / "state"
        state.mkdir(parents=True, exist_ok=True)
        state.chmod(0o700)
        variables = {
            "BTRC_HOME": str(REPO / "src"),
            "BTRC_CACHE_DIR": str(self.scratch / "cache"),
            "BTRC_STATE_DIR": str(state),
            "ZIG_LOCAL_CACHE_DIR": str(self.scratch / "zig"),
        }
        if not TargetRows.is_host(self.row):
            variables["BTRC_NATIVE_TARGET"] = self.row.triple
            with contextlib.suppress(NativePlanError):
                variables["BTRC_NATIVE_SYSROOT"] = str(self.toolchain.sysroot())
        return variables

    @contextlib.contextmanager
    def applied(self) -> Iterator[None]:
        variables = self.variables()
        saved = {name: os.environ.get(name) for name in variables}
        os.environ.update(variables)
        try:
            yield
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


@dataclass
class ProgramOutcome:
    """One program's final result on the target through one frontend."""

    program: str
    frontend: str
    program_id: str
    status: str  # passed | failed | restricted | missing
    observed: str  # passed | built | failed | error | restricted | missing
    phase: str | None = None
    reason: str | None = None
    cites: str | None = None
    duration_s: float = 0.0
    result: ExecutionResult | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def log_name(self) -> str:
        return CorpusProgram(self.program).log_name

    @property
    def artifact(self) -> str:
        return f"{self.frontend}/{self.log_name}.json"

    def as_dict(self) -> dict[str, Any]:
        record = {
            "program": self.program,
            "frontend": self.frontend,
            "program_id": self.program_id,
            "status": self.status,
            "observed": self.observed,
            "phase": self.phase,
            "reason": self.reason,
            "cites": self.cites,
            "duration_s": round(self.duration_s, 6),
            "artifact": self.artifact,
        }
        if self.notes:
            record["notes"] = list(self.notes)
        if self.result is not None:
            record["result"] = self.result.summary()
        return {key: value for key, value in record.items() if value is not None}


class TargetCorpusRunner:
    """Build the corpus for one target, run it on one executor, and report every program."""

    def __init__(
        self,
        label: str,
        frontends: Sequence[str],
        *,
        output: Path | None = None,
        bundle: Path | None = None,
        btrcc: Path | None = None,
        jobs: int = 1,
        programs: Sequence[str] = (),
        cflags: Sequence[str] = STRICT_CFLAGS,
        executor: str = LocalExecutor.NAME,
        executor_options: Mapping[str, str] | None = None,
        manifest: ApplicabilityManifest | None = None,
        registry: ExecutorRegistry | None = None,
    ) -> None:
        self.row = TargetRows.row(label)
        if not frontends or not set(frontends) <= set(FRONTENDS):
            raise ValueError(f"frontends must be drawn from {FRONTENDS}")
        self.frontends = tuple(frontend for frontend in FRONTENDS if frontend in frontends)
        self.output = (output or OUTPUT_ROOT / label).resolve()
        self.bundle_dir = (bundle or self.output / "bundle").resolve()
        self.btrcc = btrcc
        if jobs < 1:
            raise ValueError("jobs must be at least 1")
        self.jobs = jobs
        self.selection = tuple(programs)
        self.programs = CorpusProgram.select(programs)
        self.cflags = tuple(cflags)
        self.executor_name = executor
        self.executor_options = dict(executor_options or {})
        self.manifest = manifest or ApplicabilityManifest.load()
        self.registry = registry or ExecutorRegistry()
        self.started_at = datetime.datetime.now(datetime.UTC)

    @staticmethod
    def request_for(program_id: str) -> ExecutionRequest:
        """Every corpus program runs with no arguments, empty stdin and the corpus deadline, in an isolated cwd."""

        return ExecutionRequest(program_id, timeout_s=RUN_TIMEOUT)

    # Building --------------------------------------------------------------

    def build(self) -> tuple[TargetBundle, list[BuildResult]]:
        """Build every applicable program through every frontend into a fresh bundle."""

        if "selfhost" in self.frontends and self.btrcc is None:
            raise ValueError("the selfhost frontend needs a compiler: pass --btrcc or set BTRC_TEST_BTRCC")
        toolchain = TargetRows.toolchain(self.row)
        TargetBundle.prepare_directory(self.bundle_dir)
        # The C and objects of programs that failed to build stay in <output>/work for triage.
        scratch = self.output / "work"
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        environment = TargetEnvironment(self.row, toolchain, scratch)
        try:
            with environment.applied():
                configuration = BuildConfiguration(
                    label=self.row.label,
                    work=scratch,
                    bundle=self.bundle_dir,
                    btrcc=self.btrcc,
                    cflags=self.cflags,
                    compute=ComputeRuntime.host_flags() if TargetRows.is_host(self.row) else "",
                    facility=self.manifest.facility(ComputeRuntime.FACILITY),
                )
                results = self.build_programs(ProgramBuilder(configuration, toolchain))
                described = TargetRows.describe(toolchain, self.cflags)
        finally:
            environment.discard()
        document = {
            "schema": TargetBundle.SCHEMA,
            "protocol": PROTOCOL_VERSION,
            "target": {
                "label": self.row.label,
                "triple": self.row.triple,
                "operating_system": self.row.operating_system,
                "architecture": self.row.architecture,
            },
            "source_revision": SourceRevision.current(),
            "source_dirty": SourceRevision.dirty(),
            "frontends": list(self.frontends),
            "selection": list(self.selection),
            "toolchain": described,
            "compilers": self.compilers(),
            "programs": {},
        }
        for result in results:
            program = CorpusProgram(result.program)
            request = self.request_for(result.program_id) if result.status == "built" else None
            expected = GoldenExpectation.of(program).pins() if result.status == "built" else None
            document["programs"][result.program_id] = result.entry(request, expected, program.requires())
        bundle = TargetBundle(self.bundle_dir.resolve(), document)
        bundle.write()
        return bundle, results

    def compilers(self) -> dict[str, Any]:
        compilers: dict[str, Any] = {}
        if "reference" in self.frontends:
            compilers["reference"] = {"python": platform.python_version()}
        if "selfhost" in self.frontends and self.btrcc is not None:
            compilers["selfhost"] = {"btrcc_sha256": TargetBundle.digest(self.btrcc)}
        return compilers

    def build_programs(self, builder: ProgramBuilder) -> list[BuildResult]:
        results: list[BuildResult] = []
        tasks: list[tuple[CorpusProgram, str]] = []
        for program in self.programs:
            for frontend in self.frontends:
                program_id = program.program_id(frontend)
                verdict = self.manifest.program_verdict(program, self.row.label, frontend)
                if verdict is not None and verdict.scope == "build":
                    results.append(
                        BuildResult(
                            program.source,
                            frontend,
                            program_id,
                            verdict.status,
                            "applicability",
                            verdict.reason,
                            verdict.cites,
                        )
                    )
                elif not program.stdout_golden.is_file():
                    reason = f"Runnable corpus case is missing its stdout golden: {program.stdout_golden}"
                    results.append(BuildResult(program.source, frontend, program_id, "failed", "golden", reason))
                else:
                    tasks.append((program, frontend))
        if self.jobs == 1:
            results.extend(builder.build(program, frontend) for program, frontend in tasks)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.jobs) as pool:
                results.extend(pool.map(lambda task: builder.build(*task), tasks))
        return sorted(results, key=lambda result: (FRONTENDS.index(result.frontend), result.program))

    # Admission and execution ----------------------------------------------

    def admit(self, bundle: TargetBundle) -> list[BuildResult]:
        """The bundle's build results, after checking every pin against this checkout."""

        if bundle.label != self.row.label:
            raise ExecutorProtocolError(f"the bundle was built for {bundle.label}, not {self.row.label}")
        revision = SourceRevision.current()
        if bundle.document.get("source_revision") != revision:
            raise ExecutorProtocolError(
                f"the bundle was built at {bundle.document.get('source_revision')}, this checkout is {revision}"
            )
        results = []
        for program in self.programs:
            for frontend in self.frontends:
                program_id = program.program_id(frontend)
                entry = bundle.programs.get(program_id)
                if entry is None:
                    raise ExecutorProtocolError(f"the bundle has no {program_id}")
                if entry["source"] != program.source or entry["frontend"] != frontend:
                    raise ExecutorProtocolError(f"{program_id} names {entry['source']} through {entry['frontend']}")
                verdict = self.manifest.program_verdict(program, self.row.label, frontend)
                build_verdict = verdict if verdict is not None and verdict.scope == "build" else None
                excluded = entry["status"] in ("restricted", "missing") and entry.get("phase") == "applicability"
                if (build_verdict is not None) != excluded or (
                    build_verdict is not None
                    and (build_verdict.status, build_verdict.reason) != (entry["status"], entry["reason"])
                ):
                    raise ExecutorProtocolError(
                        f"{program_id}: the applicability manifest changed since the bundle was built"
                    )
                if entry["status"] == "built":
                    if entry.get("request") != self.request_for(program_id).pins():
                        raise ExecutorProtocolError(f"{program_id}: the bundle pins a different request")
                    if (
                        not program.stdout_golden.is_file()
                        or entry.get("expected") != GoldenExpectation.of(program).pins()
                    ):
                        raise ExecutorProtocolError(f"{program_id}: the bundle pins a different expected outcome")
                    if entry.get("requires") != sorted(program.requires()):
                        raise ExecutorProtocolError(f"{program_id}: the bundle pins different requirements")
                    if TargetBundle.digest(bundle.artifact_path(program_id)) != entry["sha256"]:
                        raise ExecutorProtocolError(f"{program_id}: the artifact does not match its digest")
                    companion = bundle.companion(program_id)
                    if companion is not None and TargetBundle.digest(companion.path) != companion.sha256:
                        raise ExecutorProtocolError(f"{program_id}: the companion does not match its digest")
                results.append(BuildResult.from_entry(program_id, entry))
        return results

    def execute(self, bundle: TargetBundle, builds: Sequence[BuildResult]) -> list[ProgramOutcome]:
        outcomes = [outcome for build in builds if (outcome := self.unbuilt(build)) is not None]
        runnable = [build for build in builds if build.status == "built"]
        if not runnable:
            return outcomes
        executor = self.registry.create(self.executor_name, self.executor_options)
        try:
            try:
                executor.prepare(bundle.directory, self.row.label)
            except Exception as error:
                raise ExecutorProtocolError(
                    f"the {self.executor_name} executor refused the bundle: {error!r}"
                ) from error
            granted_capabilities = getattr(executor, "granted_capabilities", None)
            granted = frozenset(granted_capabilities()) if callable(granted_capabilities) else None
            policies = getattr(executor, "CWD_POLICIES", frozenset({"isolated"}))
            modes = getattr(executor, "LAUNCH_MODES", frozenset({"process"}))
            for build in runnable:
                outcomes.append(self.execute_one(executor, bundle, build, granted, policies, modes))
        finally:
            executor.close()
        return outcomes

    def execute_one(
        self,
        executor: TargetExecutor,
        bundle: TargetBundle,
        build: BuildResult,
        granted: frozenset[str] | None,
        policies: frozenset[str],
        modes: frozenset[str],
    ) -> ProgramOutcome:
        program = CorpusProgram(build.program)
        entry = bundle.programs[build.program_id]
        verdict = self.manifest.program_verdict(program, self.row.label, build.frontend)
        if verdict is None or verdict.scope != "run":
            verdict = next(
                (
                    found
                    for capability in entry["requires"]
                    if (found := self.manifest.capability_verdict(capability, self.executor_name, granted)) is not None
                ),
                None,
            )
        if verdict is not None:
            return ProgramOutcome(
                build.program,
                build.frontend,
                build.program_id,
                verdict.status,
                verdict.status,
                "run",
                verdict.reason,
                verdict.cites,
            )
        request = ExecutionRequest.from_pins(build.program_id, entry["request"])
        if request.cwd_policy not in policies or request.launch_mode not in modes:
            return ProgramOutcome(
                build.program,
                build.frontend,
                build.program_id,
                "failed",
                "error",
                "execute",
                f"the {self.executor_name} executor declares no {request.launch_mode} launch in a {request.cwd_policy} cwd",
            )
        started = time.monotonic()
        try:
            result = ExecutionResult.adopt(executor.run(request), request)
        except Exception as error:
            return ProgramOutcome(
                build.program,
                build.frontend,
                build.program_id,
                "failed",
                "error",
                "execute",
                f"the executor failed: {error!r}",
                duration_s=time.monotonic() - started,
            )
        mismatch = GoldenExpectation.of(program).mismatch(result)
        return ProgramOutcome(
            build.program,
            build.frontend,
            build.program_id,
            "failed" if mismatch else "passed",
            "failed" if mismatch else "passed",
            "compare" if mismatch else None,
            mismatch,
            duration_s=result.duration_s,
            result=result,
        )

    @staticmethod
    def unbuilt(build: BuildResult) -> ProgramOutcome | None:
        """The final outcome of a program that was never built, or None for a built one."""

        if build.status == "built":
            return None
        observed = build.status if build.status in ("restricted", "missing") else "failed"
        return ProgramOutcome(
            build.program,
            build.frontend,
            build.program_id,
            build.status,
            observed,
            build.phase,
            build.reason,
            build.cites,
            build.duration_s,
        )

    def compile_only(self, builds: Sequence[BuildResult]) -> list[ProgramOutcome]:
        outcomes = []
        for build in builds:
            outcome = self.unbuilt(build)
            if outcome is None:
                outcome = ProgramOutcome(
                    build.program, build.frontend, build.program_id, "passed", "built", duration_s=build.duration_s
                )
                program = CorpusProgram(build.program)
                verdict = self.manifest.program_verdict(program, self.row.label, build.frontend)
                if verdict is not None and verdict.scope == "run":
                    outcome.notes.append(f"built; never run here ({verdict.status}): {verdict.reason}")
                outcome.notes.extend(f"running it requires {capability}" for capability in sorted(program.requires()))
            outcomes.append(outcome)
        return outcomes

    # The whole run ---------------------------------------------------------

    def run(self, *, compile_only: bool = False, execute_bundle: Path | None = None) -> TargetRunReport:
        if execute_bundle is not None:
            bundle = TargetBundle.load(execute_bundle)
            if not self.selection and bundle.document.get("selection"):
                # A bundle built from a subset is executed as that subset unless asked otherwise.
                self.selection = tuple(bundle.document["selection"])
                self.programs = CorpusProgram.select(self.selection)
            builds = self.admit(bundle)
        else:
            bundle, builds = self.build()
        if compile_only:
            outcomes = self.compile_only(builds)
        else:
            outcomes = self.execute(bundle, builds)
        outcomes.sort(key=lambda outcome: (FRONTENDS.index(outcome.frontend), outcome.program))
        report = TargetRunReport(self, bundle, outcomes, "compile-only" if compile_only else "execute")
        report.write()
        return report


class TargetRunReport:
    """Everything a run wrote: per-program logs, the summary, the JUnit file and the ledger."""

    SUMMARY = "target-run.json"
    JUNIT = "junit.xml"
    LEDGER = "ledger.jsonl"

    def __init__(
        self, runner: TargetCorpusRunner, bundle: TargetBundle, outcomes: list[ProgramOutcome], mode: str
    ) -> None:
        self.runner = runner
        self.bundle = bundle
        self.outcomes = outcomes
        self.mode = mode
        self.finished_at = datetime.datetime.now(datetime.UTC)

    def counts(self) -> dict[str, dict[str, int]]:
        counts = {frontend: dict.fromkeys(STATUSES, 0) for frontend in self.runner.frontends}
        for outcome in self.outcomes:
            counts[outcome.frontend][outcome.status] += 1
        return counts

    @property
    def failed(self) -> bool:
        return any(outcome.status == "failed" for outcome in self.outcomes)

    def executor_provenance(self) -> dict[str, Any] | None:
        return next((outcome.result.provenance for outcome in self.outcomes if outcome.result is not None), None)

    def summary(self) -> dict[str, Any]:
        return {
            "schema": REPORT_SCHEMA,
            "protocol": PROTOCOL_VERSION,
            "target": self.bundle.document["target"],
            "mode": self.mode,
            "executor": self.runner.executor_name if self.mode == "execute" else None,
            "executor_provenance": self.executor_provenance(),
            "frontends": list(self.runner.frontends),
            "selection": list(self.runner.selection),
            "source_revision": self.bundle.document["source_revision"],
            "source_dirty": self.bundle.document["source_dirty"],
            "toolchain": self.bundle.toolchain,
            "compilers": self.bundle.document.get("compilers", {}),
            "started_at": self.runner.started_at.isoformat(timespec="seconds"),
            "finished_at": self.finished_at.isoformat(timespec="seconds"),
            "host": HostProvenance().summary(),
            "counts": self.counts(),
            "results": [outcome.as_dict() for outcome in self.outcomes],
        }

    def write(self) -> None:
        output = self.runner.output
        output.mkdir(parents=True, exist_ok=True)
        for frontend in self.runner.frontends:
            shutil.rmtree(output / frontend, ignore_errors=True)
        for outcome in self.outcomes:
            stem = output / outcome.frontend / outcome.log_name
            stem.parent.mkdir(parents=True, exist_ok=True)
            if outcome.result is not None:
                stem.with_name(f"{stem.name}.stdout").write_bytes(outcome.result.stdout)
                stem.with_name(f"{stem.name}.stderr").write_bytes(outcome.result.stderr)
            stem.with_name(f"{stem.name}.json").write_text(
                json.dumps(outcome.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        summary = self.summary()
        (output / self.SUMMARY).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.write_junit(output / self.JUNIT)
        # This machine's hardware describes the evidence only when the programs ran on it.
        local = self.mode == "execute" and self.runner.executor_name == LocalExecutor.NAME
        base = HostProvenance().detect() if local else Provenance()
        summary_path = (output / self.SUMMARY).resolve()
        artifact = summary_path.relative_to(REPO) if summary_path.is_relative_to(REPO) else summary_path
        records = TargetRunAdapter(base).records(summary, artifact=artifact.as_posix())
        ledger = output / self.LEDGER
        ledger.write_text(LedgerDocument.dumps_jsonl(records), encoding="utf-8")
        LedgerDocument.load(ledger)

    def write_junit(self, path: Path) -> None:
        label = self.runner.row.label
        suite = ElementTree.Element(
            "testsuite",
            name=f"target-runner {label}",
            tests=str(len(self.outcomes)),
            failures=str(sum(outcome.status == "failed" for outcome in self.outcomes)),
            skipped=str(sum(outcome.status in ("restricted", "missing") for outcome in self.outcomes)),
            timestamp=self.finished_at.isoformat(timespec="seconds"),
        )
        for outcome in self.outcomes:
            case = ElementTree.SubElement(
                suite,
                "testcase",
                classname=f"src.tests.target_runner.{label}",
                name=f"{outcome.frontend}-{outcome.program}",
                time=f"{outcome.duration_s:.3f}",
            )
            if outcome.status == "failed":
                failure = ElementTree.SubElement(case, "failure", message=f"{outcome.phase}: {outcome.reason}")
                failure.text = outcome.reason
            elif outcome.status in ("restricted", "missing"):
                ElementTree.SubElement(case, "skipped", message=f"{outcome.status}: {outcome.reason} [{outcome.cites}]")
        ElementTree.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)

    def lines(self) -> list[str]:
        where = self.runner.executor_name if self.mode == "execute" else "compile-only"
        lines = [f"target-runner {self.runner.row.label} ({where}) -> {self.runner.output}"]
        for frontend, counts in self.counts().items():
            lines.append(f"  {frontend}: " + ", ".join(f"{counts[status]} {status}" for status in STATUSES))
        for outcome in self.outcomes:
            if outcome.status == "failed":
                reason = (outcome.reason or "").splitlines() or [""]
                first = next((line for line in reason if "error" in line), reason[0])
                lines.append(f"  FAILED {outcome.frontend} {outcome.program} [{outcome.phase}]: {first.strip()[:300]}")
        return lines


class TargetRunnerCommand:
    """The command line: ``python -m src.tests.target_runner``."""

    @staticmethod
    def parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="python -m src.tests.target_runner", description=__doc__.split("\n\n")[0])
        parser.add_argument("--target", help="the targets.toml label to build for (default: the bundle's)")
        parser.add_argument("--frontend", choices=(*FRONTENDS, "both"), default="both")
        parser.add_argument("--executor", default=LocalExecutor.NAME, help="local, a capability name, or module:Class")
        parser.add_argument("--executor-option", action="append", default=[], metavar="NAME=VALUE")
        parser.add_argument("--compile-only", action="store_true", help="build the bundle without executing it")
        parser.add_argument("--bundle", type=Path, help="where to write the bundle (default: <output>/bundle)")
        parser.add_argument("--execute-bundle", type=Path, help="admit and run a bundle built earlier")
        parser.add_argument("--output", type=Path, help="the run directory (default: build/target-runs/<label>)")
        parser.add_argument("--btrcc", type=Path, help="the self-hosted compiler (default: $BTRC_TEST_BTRCC)")
        parser.add_argument("--jobs", type=int, default=1, help="programs built at once (execution is serial)")
        parser.add_argument("--program", action="append", default=[], metavar="GLOB", help="corpus paths to select")
        parser.add_argument("--cflags", help=f"flags for every generated unit (default: {' '.join(STRICT_CFLAGS)})")
        parser.add_argument("--list-executors", action="store_true", help="print the discoverable executor names")
        return parser

    @classmethod
    def main(cls, argv: Sequence[str] | None = None) -> int:
        parser = cls.parser()
        arguments = parser.parse_args(argv)
        registry = ExecutorRegistry()
        if arguments.list_executors:
            for name in registry.names():
                print(f"{name}\t{registry.spec(name)}")
            return 0
        if arguments.execute_bundle and (arguments.compile_only or arguments.bundle):
            parser.error("--execute-bundle runs an existing bundle; it takes neither --compile-only nor --bundle")
        label = arguments.target
        if arguments.execute_bundle:
            bundle_label = TargetBundle.load(arguments.execute_bundle).label
            if label not in (None, bundle_label):
                parser.error(f"the bundle was built for {bundle_label}, not {label}")
            label = bundle_label
        if label is None:
            parser.error("--target is required")
        options = {}
        for option in arguments.executor_option:
            name, separator, value = option.partition("=")
            if not separator or not name:
                parser.error(f"--executor-option takes NAME=VALUE, not {option!r}")
            options[name] = value
        btrcc = arguments.btrcc or (Path(os.environ["BTRC_TEST_BTRCC"]) if os.environ.get("BTRC_TEST_BTRCC") else None)
        frontends = FRONTENDS if arguments.frontend == "both" else (arguments.frontend,)
        try:
            runner = TargetCorpusRunner(
                label,
                frontends,
                output=arguments.output,
                bundle=arguments.bundle,
                btrcc=btrcc.resolve() if btrcc else None,
                jobs=arguments.jobs,
                programs=arguments.program,
                cflags=shlex.split(arguments.cflags) if arguments.cflags is not None else STRICT_CFLAGS,
                executor=arguments.executor,
                executor_options=options,
                registry=registry,
            )
            report = runner.run(compile_only=arguments.compile_only, execute_bundle=arguments.execute_bundle)
        except (ValueError, LookupError, NativePlanError, ExecutorProtocolError) as error:
            print(f"target-runner: {error}", file=sys.stderr)
            return 2
        print("\n".join(report.lines()))
        return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(TargetRunnerCommand.main())
