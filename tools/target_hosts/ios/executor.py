"""The iOS simulator target executor, executor protocol 1 (CX-P1-08).

``src/tests/target_runner.py`` freezes the protocol and finds this class as
``ios-simulator`` through `TARGET_EXECUTORS`. The module imports nothing from
the runner.

Admission. ``prepare(bundle_dir, label)`` reads the bundle's ``bundle.json``
(``btrc.target-bundle/1``) for ``ios-aarch64-simulator`` only, and refuses a
host that is not arm64: the arm64 simulator runs natively only on Apple
silicon, so anything else would be emulation or nothing. Every built program
is copied into a private 0700 staging directory as a 0500 file, and the
staged bytes must match the bundle's SHA-256 and be an arm64 Mach-O for the
iOS simulator platform. `supervisor.c` is compiled for the bundle's triple
with Xcode's clang. The simulator is booted (`simhost.py`) and warmed: the
first spawn after a cold boot outlasted 30 s on a hosted runner (run
37579929097), so a probe gets `WARMUP_TIMEOUT_S`, and a self-test runs the
supervisor as a child of itself to prove a spawn and a wait inside the
simulator before any program runs. Admission is atomic: a failure leaves the
executor as it was.

Launch. Each run is one ``simctl spawn <device> supervisor run <control>
<deadline-ms> <cwd> <program> <argument...>``, with the request's environment
passed as ``SIMCTL_CHILD_<name>``. The supervisor starts the program as its
child in a new process group, with stdin from the staged request file, stdout
and stderr into files in the run's control directory, and the cwd the policy
names: a fresh empty directory beside, never inside, the control directory
(``isolated``), or the staged program's directory (``bundle``). Before
launching, the staged copy's digest is checked again, so only the admitted
bytes run.

Outcome. The supervisor's ``waitpid`` decides it: it reports the exit status,
the terminating signal, or its own deadline (after which it has killed the
program's whole process group) as a line on its stdout, which simctl relays
to this process and the program never holds. Its own exit status, as simctl
returns it, must be 0. A spawn that never starts the program within
`launch_timeout_s`, a supervisor that reports no outcome by the program's
deadline plus `GRACE_S`, or an output larger than `OUTPUT_LIMIT_BYTES` is an
infrastructure error, raised with simctl's diagnostics; it is never encoded
as a program outcome.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import queue
import re
import shutil
import signal as process_signal
import stat
import struct
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from tools.target_hosts.ios.simhost import AppleEnvironment, IOSSimulatorHost, SimulatorError

BUNDLE_SCHEMA = "btrc.target-bundle/1"
BUNDLE_MANIFEST = "bundle.json"
PROGRAM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
# Retained per stream, as the runner's own local executor retains it; more is an infrastructure error.
OUTPUT_LIMIT_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ExecutionRequest:
    """The runner's request (protocol 1); `spike.py` builds these without importing the runner."""

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


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def remove_tree(path: Path) -> None:
    """``shutil.rmtree`` that restores owner permissions a program removed, and retries."""

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


class MachOImage:
    """The architecture and platform of a thin 64-bit Mach-O image."""

    MAGIC_64 = 0xFEEDFACF
    ARM64 = 0x0100000C
    BUILD_VERSION = 0x32
    IOS_SIMULATOR = 7
    HEADER = struct.Struct("<IiiIIIII")
    COMMAND = struct.Struct("<II")

    @classmethod
    def describe(cls, data: bytes) -> tuple[int, int | None]:
        """(CPU type, LC_BUILD_VERSION platform or None) of `data`; ValueError for anything else."""

        if len(data) < cls.HEADER.size:
            raise ValueError("not a Mach-O image: too short")
        magic, cpu, _subtype, _kind, commands, _size, _flags, _reserved = cls.HEADER.unpack_from(data)
        if magic != cls.MAGIC_64:
            raise ValueError(f"not a thin 64-bit Mach-O image (magic 0x{magic:08x})")
        offset = cls.HEADER.size
        for _ in range(commands):
            if offset + cls.COMMAND.size > len(data):
                raise ValueError("truncated Mach-O load commands")
            command, size = cls.COMMAND.unpack_from(data, offset)
            if command == cls.BUILD_VERSION and offset + 12 <= len(data):
                return cpu, struct.unpack_from("<I", data, offset + 8)[0]
            if size < cls.COMMAND.size:
                raise ValueError("malformed Mach-O load command")
            offset += size
        return cpu, None

    @classmethod
    def check(cls, data: bytes, name: str) -> None:
        """Refuse anything but an arm64 image built for the iOS simulator platform."""

        cpu, platform_id = cls.describe(data)
        if cpu != cls.ARM64 or platform_id != cls.IOS_SIMULATOR:
            raise ValueError(
                f"{name} is not an arm64 iOS simulator image (cpu 0x{cpu & 0xFFFFFFFF:08x}, platform {platform_id})"
            )


class XcodeSupervisorBuilder:
    """Compile the supervisor for the bundle's triple with Xcode's clang, under the strict C11 flags."""

    FLAGS = ("-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2")
    TIMEOUT_S = 300

    def __call__(self, source: Path, output: Path, triple: str) -> None:
        command = [
            str(AppleEnvironment.XCRUN),
            "--sdk",
            "iphonesimulator",
            "clang",
            f"--target={triple}",
            *self.FLAGS,
            str(source),
            "-o",
            str(output),
        ]
        try:
            built = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_S,
                env=AppleEnvironment.variables(),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SimulatorError(f"the supervisor did not build: {error}") from error
        if built.returncode:
            raise SimulatorError(f"the supervisor did not build ({built.returncode}): {built.stderr.strip()[:4000]}")


class SupervisorChannel:
    """The simctl client's two pipes: supervisor events from stdout, simctl's diagnostics from stderr."""

    PREFIX = "btrc-ios-supervisor "
    EVENT = re.compile(r"btrc-ios-supervisor ([a-z]+)((?: [a-z-]+=[A-Za-z0-9._-]+)*)")
    LIMIT = 64 * 1024

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process
        self.events: queue.Queue[tuple[str, dict[str, str]]] = queue.Queue()
        self.diagnostics = bytearray()
        self.noise: list[str] = []
        self.threads = [
            threading.Thread(target=self.read_events, args=(process.stdout,), daemon=True),
            threading.Thread(target=self.read_diagnostics, args=(process.stderr,), daemon=True),
        ]
        for thread in self.threads:
            thread.start()

    def read_events(self, stream) -> None:
        received = 0
        try:
            with stream:
                for raw in iter(stream.readline, b""):
                    received += len(raw)
                    if received > self.LIMIT:
                        self.events.put(("malformed", {"reason": f"more than {self.LIMIT} bytes of events"}))
                        continue
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    if not line.startswith(self.PREFIX):
                        # simctl's own output, if any: kept for diagnostics, never an outcome.
                        if len(self.noise) < 20:
                            self.noise.append(line[:200])
                        continue
                    match = self.EVENT.fullmatch(line)
                    if match is None:
                        self.events.put(("malformed", {"line": line[:200]}))
                        continue
                    fields = dict(pair.split("=", 1) for pair in match[2].split())
                    self.events.put((match[1], fields))
        except Exception as error:
            self.events.put(("malformed", {"reason": repr(error)}))
        finally:
            self.events.put(("eof", {}))

    def read_diagnostics(self, stream) -> None:
        with suppress(Exception), stream:
            while chunk := stream.read1(65536):
                room = self.LIMIT - len(self.diagnostics)
                self.diagnostics.extend(chunk[: max(room, 0)])

    def next(self, deadline: float) -> tuple[str, dict[str, str]] | None:
        """The next event, or None once `deadline` (time.monotonic) passes."""

        try:
            return self.events.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            return None

    def describe(self) -> str:
        text = bytes(self.diagnostics).decode("utf-8", "replace").strip()
        parts = [f"simctl stderr: {text[-2000:] or '(empty)'}"]
        if self.noise:
            parts.append(f"simctl stdout: {' | '.join(self.noise)}")
        if self.process.returncode is not None:
            parts.append(f"simctl status {self.process.returncode}")
        return "; ".join(parts)

    def close(self, timeout: float = 10) -> list[str]:
        """Stop the simctl client if it still runs, reap it and join the readers; return any warning."""

        warnings = []
        if self.process.poll() is None:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(self.process.pid, process_signal.SIGKILL)
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            warnings.append(f"the simctl client {self.process.pid} did not exit after SIGKILL")
        deadline = time.monotonic() + timeout
        for thread in self.threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self.threads):
            warnings.append("a simulator process still holds the simctl client's pipes")
        return warnings


@dataclass(frozen=True)
class Outcome:
    """What the supervisor reported for one launch."""

    exit_status: int | None
    signal: int | None
    timed_out: bool
    elapsed_s: float
    launch_s: float


class IOSSimulatorExecutor:
    """Run an iOS simulator bundle's programs through simctl spawn, one supervisor per run (protocol 1)."""

    NAME = "ios-simulator"
    LABELS: ClassVar[frozenset[str]] = frozenset({"ios-aarch64-simulator"})
    CWD_POLICIES: ClassVar[frozenset[str]] = frozenset({"isolated", "bundle"})
    LAUNCH_MODES: ClassVar[frozenset[str]] = frozenset({"process"})
    # simctl prefixes the child environment itself, and dyld variables reach the supervisor too.
    RESERVED_PREFIXES: ClassVar[tuple[str, ...]] = ("SIMCTL_", "DYLD_")
    SUPERVISOR_SOURCE = Path(__file__).resolve().with_name("supervisor.c")
    NATIVE_MACHINES: ClassVar[frozenset[str]] = frozenset({"arm64", "aarch64"})
    LAUNCH_TIMEOUT_S = 60.0
    WARMUP_TIMEOUT_S = 600.0
    GRACE_S = 30.0
    SELF_TEST_STATUS = 3
    OPTIONS: ClassVar[frozenset[str]] = frozenset(
        {"device_class", "runtime", "launch_timeout_s", "warmup_timeout_s", "diagnostics"}
    )

    def __init__(
        self,
        *,
        device_class: str = "iphone",
        runtime: str | None = None,
        launch_timeout_s: float = LAUNCH_TIMEOUT_S,
        warmup_timeout_s: float = WARMUP_TIMEOUT_S,
        diagnostics: Path | None = None,
        host: Any = None,
        builder: Callable[[Path, Path, str], None] | None = None,
        image_check: Callable[[bytes, str], None] = MachOImage.check,
        machine: Callable[[], str] = platform.machine,
        staging_root: Path | None = None,
    ) -> None:
        for name, value in (("launch_timeout_s", launch_timeout_s), ("warmup_timeout_s", warmup_timeout_s)):
            if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number of seconds")
        self.launch_timeout_s = float(launch_timeout_s)
        self.warmup_timeout_s = float(warmup_timeout_s)
        self.diagnostics = Path(diagnostics) if diagnostics else None
        self.host = host if host is not None else IOSSimulatorHost(device_class, runtime=runtime)
        self.builder = builder if builder is not None else XcodeSupervisorBuilder()
        self.image_check = image_check
        self.machine = machine
        self.staging_root = staging_root
        self.label: str | None = None
        self.staging: Path | None = None
        self.supervisor: Path | None = None
        self.programs: dict[str, Path] = {}
        self.digests: dict[str, str] = {}
        self.provenance: dict[str, Any] = {}
        self.capabilities: frozenset[str] = frozenset()

    @classmethod
    def from_options(cls, options: Mapping[str, str]) -> IOSSimulatorExecutor:
        """The runner's ``--executor-option NAME=VALUE`` pairs."""

        unknown = set(options) - cls.OPTIONS
        if unknown:
            raise ValueError(f"unknown ios-simulator option(s) {sorted(unknown)}; expected {sorted(cls.OPTIONS)}")
        arguments: dict[str, Any] = {}
        for name, value in options.items():
            if name.endswith("_timeout_s"):
                try:
                    arguments[name] = float(value)
                except ValueError:
                    raise ValueError(f"{name} must be a number of seconds, not {value!r}") from None
            elif name == "diagnostics":
                arguments[name] = Path(value)
            else:
                arguments[name] = value
        return cls(**arguments)

    # Admission ---------------------------------------------------------------

    def read_bundle(self, bundle: Path, label: str) -> dict[str, Any]:
        document = json.loads((bundle / BUNDLE_MANIFEST).read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("schema") != BUNDLE_SCHEMA:
            raise ValueError(f"{bundle} holds no {BUNDLE_SCHEMA} bundle")
        target = document.get("target")
        built_for = target.get("label") if isinstance(target, dict) else None
        if built_for != label:
            raise ValueError(f"the bundle was built for {built_for!r}, not {label!r}")
        if label not in self.LABELS:
            raise ValueError(f"{label!r} is not a row this executor runs ({', '.join(sorted(self.LABELS))})")
        if not isinstance(target.get("triple"), str) or not target["triple"].endswith("-simulator"):
            raise ValueError(f"the bundle's triple {target.get('triple')!r} is not an iOS simulator triple")
        if not isinstance(document.get("programs"), dict):
            raise ValueError("the bundle's programs must be a table")
        return document

    @staticmethod
    def artifact(bundle: Path, program_id: str, entry: Mapping[str, Any]) -> Path:
        """The bundle file a built program names, refusing any other name or location."""

        if not PROGRAM_ID.fullmatch(program_id):
            raise ValueError(f"invalid bundle program {program_id!r}")
        if entry.get("artifact") != program_id:
            raise ValueError(f"{program_id}: an iOS simulator artifact is the program id itself")
        if not SHA256.fullmatch(str(entry.get("sha256") or "")):
            raise ValueError(f"{program_id}: the bundle records no SHA-256")
        path = bundle / program_id
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(bundle):
            raise ValueError(f"{program_id}: the artifact must be a regular file inside the bundle")
        return path

    def prepare(self, bundle_dir: Path | str, label: str) -> None:
        bundle = Path(bundle_dir).resolve(strict=True)
        document = self.read_bundle(bundle, label)
        machine = self.machine()
        if machine not in self.NATIVE_MACHINES:
            raise ValueError(f"{label} runs natively only on an arm64 Mac, not on {machine}; emulation is not evidence")
        staging = Path(tempfile.mkdtemp(prefix="btrc-ios-executor-", dir=self.staging_root)).resolve()
        programs: dict[str, Path] = {}
        digests: dict[str, str] = {}
        try:
            for name in ("programs", "runs"):
                (staging / name).mkdir(mode=0o700)
            for program_id, entry in sorted(document["programs"].items()):
                if not isinstance(entry, dict) or entry.get("status") != "built":
                    continue
                source = self.artifact(bundle, program_id, entry)
                staged = staging / "programs" / program_id
                shutil.copyfile(source, staged)
                os.chmod(staged, stat.S_IRUSR | stat.S_IXUSR)
                data = staged.read_bytes()
                if digest(data) != entry["sha256"]:
                    raise ValueError(f"{program_id}: the staged copy does not match the bundle's SHA-256")
                self.image_check(data, program_id)
                programs[program_id], digests[program_id] = staged, entry["sha256"]
            supervisor = staging / "supervisor"
            self.builder(self.SUPERVISOR_SOURCE, supervisor, document["target"]["triple"])
            os.chmod(supervisor, stat.S_IRUSR | stat.S_IXUSR)
            supervisor_bytes = supervisor.read_bytes()
            self.image_check(supervisor_bytes, "the supervisor")
            try:
                self.host.prepare()
                warm = self.warm(supervisor, staging)
            except BaseException as error:
                self.keep_diagnostics(error)
                raise
        except BaseException:
            with suppress(OSError):
                remove_tree(staging)
            raise
        if self.staging is not None:
            with suppress(OSError):
                remove_tree(self.staging)
        self.label, self.staging, self.supervisor = label, staging, supervisor
        self.programs, self.digests = programs, digests
        self.capabilities = frozenset({"loopback-listener"}) if warm["loopback"] == "ok" else frozenset()
        self.provenance = {
            "executor": self.NAME,
            **self.host.provenance(),
            "toolchain": document.get("toolchain", {}),
            "label": label,
            "evidence": "simulator",
            "supervisor_sha256": digest(supervisor_bytes),
            "first_spawn_s": round(warm["first_spawn_s"], 3),
            "loopback": warm["loopback"],
        }

    def keep_diagnostics(self, error: BaseException) -> None:
        if self.diagnostics is None or not hasattr(self.host, "diagnose"):
            return
        try:
            self.host.diagnose(self.diagnostics)
        except Exception as failure:
            error.add_note(f"the host diagnostics also failed: {failure!r}")

    def warm(self, supervisor: Path, staging: Path) -> dict[str, Any]:
        """Absorb the first spawn's cold start, probe loopback, and prove a spawn and a wait inside the simulator."""

        started = time.monotonic()
        process = self.host.spawn([str(supervisor), "probe"], {})
        channel = SupervisorChannel(process)
        loopback = None
        first = None
        try:
            deadline = started + self.warmup_timeout_s
            while True:
                event = channel.next(deadline)
                if event is None:
                    raise SimulatorError(
                        f"the supervisor's probe did not finish {self.warmup_timeout_s:g} s after simctl spawn; "
                        f"{channel.describe()}"
                    )
                kind, fields = event
                if kind == "ready" and first is None:
                    first = time.monotonic() - started
                elif kind == "probe":
                    loopback = fields.get("loopback")
                elif kind == "eof":
                    break
                else:
                    raise SimulatorError(f"the supervisor's probe reported {kind} {fields}; {channel.describe()}")
            process.wait(timeout=self.GRACE_S)
        except subprocess.TimeoutExpired:
            raise SimulatorError(f"the probe's simctl client did not exit; {channel.describe()}") from None
        finally:
            warnings = channel.close()
        if process.returncode != 0 or first is None or loopback is None:
            raise SimulatorError(f"the supervisor's probe failed; {channel.describe()} {' '.join(warnings)}".strip())
        outcome, stdout, _stderr, _warnings = self.launch(
            supervisor,
            staging,
            supervisor,
            ("status", str(self.SELF_TEST_STATUS)),
            b"",
            {},
            30,
            "isolated",
            self.warmup_timeout_s,
        )
        if outcome.exit_status != self.SELF_TEST_STATUS or b"btrc-ios-supervisor ready" not in stdout:
            raise SimulatorError(f"the in-simulator self-test reported {outcome}, not exit {self.SELF_TEST_STATUS}")
        return {"first_spawn_s": first, "loopback": loopback}

    def granted_capabilities(self) -> frozenset[str]:
        """The host facilities the prepared simulator proved: an IPv4 loopback listener, if its probe bound one."""

        return self.capabilities

    # Execution ---------------------------------------------------------------

    def check_request(self, request: ExecutionRequest) -> None:
        if request.program_id not in self.programs:
            raise ValueError(f"unknown program_id: {request.program_id}")
        timeout = request.timeout_s
        if isinstance(timeout, bool) or not isinstance(timeout, int | float) or not math.isfinite(timeout):
            raise ValueError("timeout_s must be a positive finite number of seconds")
        if timeout <= 0:
            raise ValueError("timeout_s must be a positive finite number of seconds")
        if request.cwd_policy not in self.CWD_POLICIES:
            raise ValueError(f"the ios-simulator executor runs in {sorted(self.CWD_POLICIES)} cwds")
        if getattr(request, "launch_mode", "process") not in self.LAUNCH_MODES or getattr(request, "app_roots", ()):
            raise ValueError("the ios-simulator executor launches processes through simctl spawn, with no app roots")
        if not isinstance(request.stdin, bytes) or any(
            not isinstance(value, str) or "\0" in value for value in request.argv
        ):
            raise ValueError("stdin must be bytes and argv NUL-free strings")
        for name, value in request.env.items():
            if not ENVIRONMENT_NAME.fullmatch(name) or not isinstance(value, str) or "\0" in value:
                raise ValueError(f"invalid environment entry {name!r}")
            if name.startswith(self.RESERVED_PREFIXES):
                raise ValueError(
                    f"{name} is reserved by the ios-simulator executor ({', '.join(self.RESERVED_PREFIXES)})"
                )

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        if self.staging is None or self.supervisor is None:
            raise RuntimeError("prepare a bundle before running")
        self.check_request(request)
        program = self.programs[request.program_id]
        if digest(program.read_bytes()) != self.digests[request.program_id]:
            raise SimulatorError(f"{request.program_id}: the staged copy changed after admission")
        outcome, stdout, stderr, warnings = self.launch(
            self.supervisor,
            self.staging,
            program,
            tuple(request.argv),
            request.stdin,
            dict(request.env),
            request.timeout_s,
            request.cwd_policy,
            self.launch_timeout_s,
        )
        return ExecutionResult(
            outcome.exit_status,
            outcome.signal,
            stdout,
            stderr,
            outcome.timed_out,
            outcome.elapsed_s,
            {**self.provenance, "launch_s": round(outcome.launch_s, 3), "cleanup_warnings": warnings},
        )

    def launch(
        self,
        supervisor: Path,
        staging: Path,
        program: Path,
        argv: Sequence[str],
        stdin: bytes,
        env: Mapping[str, str],
        timeout_s: float,
        cwd_policy: str,
        launch_timeout_s: float,
    ) -> tuple[Outcome, bytes, bytes, list[str]]:
        """Run `program` once under the supervisor; return its outcome, streams and cleanup warnings."""

        warnings: list[str] = []
        run = Path(tempfile.mkdtemp(prefix="run-", dir=staging / "runs"))
        primary: BaseException | None = None
        try:
            control, work = run / "control", run / "work"
            control.mkdir(mode=0o700)
            work.mkdir(mode=0o700)
            (control / "stdin").write_bytes(stdin)
            cwd = work if cwd_policy == "isolated" else program.parent
            deadline_ms = max(1, math.ceil(timeout_s * 1000))
            process = self.host.spawn(
                [str(supervisor), "run", str(control), str(deadline_ms), str(cwd), str(program), *argv], env
            )
            channel = SupervisorChannel(process)
            try:
                outcome = self.follow(channel, control, timeout_s, launch_timeout_s)
            finally:
                warnings += channel.close()
            streams = tuple(self.read_stream(control / name) for name in ("stdout", "stderr"))
            return outcome, streams[0], streams[1], warnings
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                remove_tree(run)
            except OSError as error:
                if primary is not None:
                    primary.add_note(f"removing {run} also failed: {error}")
                else:
                    warnings.append(f"removing {run} failed: {error}")

    def follow(self, channel: SupervisorChannel, control: Path, timeout_s: float, launch_timeout_s: float) -> Outcome:
        """Wait for the supervisor to start the program, then for its outcome, then for simctl to exit."""

        launched = time.monotonic()
        ready: int | None = None
        child: int | None = None
        started = launched
        deadline = launched + launch_timeout_s
        while child is None:
            event = channel.next(deadline)
            if event is None:
                self.withdraw(control, channel, ready)
                raise SimulatorError(
                    f"the supervisor had not started the program {launch_timeout_s:g} s after simctl spawn; "
                    f"{channel.describe()}"
                )
            kind, fields = event
            if kind == "ready":
                ready = self.pid(fields, "pid")
            elif kind == "started":
                child, started = self.pid(fields, "pid"), time.monotonic()
            else:
                channel.process.poll()
                raise SimulatorError(
                    f"the supervisor reported {kind} {fields} before starting the program; {channel.describe()}"
                )
        deadline = started + timeout_s + self.GRACE_S
        while True:
            event = channel.next(deadline)
            if event is None:
                self.stop(child, ready)
                raise SimulatorError(
                    f"the supervisor reported no outcome {timeout_s + self.GRACE_S:g} s after starting the program; "
                    f"{channel.describe()}"
                )
            kind, fields = event
            if kind in ("exit", "signal", "timeout"):
                break
            raise SimulatorError(f"the supervisor reported {kind} {fields} while the program ran; {channel.describe()}")
        elapsed = self.number(fields, "elapsed-ns") / 1e9
        try:
            channel.process.wait(timeout=self.GRACE_S)
        except subprocess.TimeoutExpired:
            raise SimulatorError(f"simctl did not exit after the supervisor's outcome; {channel.describe()}") from None
        if channel.process.returncode != 0:
            raise SimulatorError(f"the supervisor exited {channel.process.returncode}; {channel.describe()}")
        number = self.number(fields, "status" if kind == "exit" else "number")
        launch_s = started - launched
        if kind == "exit":
            if number > 255:
                raise SimulatorError(f"the supervisor reported exit status {number}")
            return Outcome(number, None, False, elapsed, launch_s)
        if not 1 <= number <= 127:
            raise SimulatorError(f"the supervisor reported signal {number}")
        return Outcome(None, number, kind == "timeout", elapsed, launch_s)

    @staticmethod
    def pid(fields: Mapping[str, str], name: str) -> int:
        value = IOSSimulatorExecutor.number(fields, name)
        if value <= 1:
            raise SimulatorError(f"the supervisor reported process {value}")
        return value

    @staticmethod
    def number(fields: Mapping[str, str], name: str) -> int:
        value = fields.get(name, "")
        if not value.isdigit():
            raise SimulatorError(f"the supervisor reported no {name}: {fields}")
        return int(value)

    def withdraw(self, control: Path, channel: SupervisorChannel, ready: int | None) -> None:
        """Stop a launch that missed its deadline: the supervisor checks `cancel` before starting the program."""

        with suppress(OSError):
            (control / "cancel").touch()
        if ready is not None:
            with suppress(ProcessLookupError, PermissionError):
                os.kill(ready, process_signal.SIGKILL)
        # A child the supervisor started just before the cancel arrived still goes with its group.
        grace = time.monotonic() + 3
        while (event := channel.next(grace)) is not None and event[0] != "eof":
            if event[0] == "started":
                with suppress(SimulatorError):
                    self.host.kill_group(self.pid(event[1], "pid"))

    def stop(self, child: int, ready: int | None) -> None:
        """Kill a program whose supervisor stopped answering, and the supervisor."""

        with suppress(SimulatorError):
            self.host.kill_group(child)
        if ready is not None:
            with suppress(ProcessLookupError, PermissionError):
                os.kill(ready, process_signal.SIGKILL)

    @staticmethod
    def read_stream(path: Path) -> bytes:
        if not path.is_file():
            raise SimulatorError(f"the supervisor left no {path.name} file")
        size = path.stat().st_size
        if size > OUTPUT_LIMIT_BYTES:
            raise SimulatorError(f"the program's {path.name} exceeded {OUTPUT_LIMIT_BYTES} bytes ({size})")
        return path.read_bytes()

    def close(self) -> None:
        errors = []
        if self.staging is not None:
            with suppress(OSError):
                remove_tree(self.staging)
        self.label, self.staging, self.supervisor, self.programs, self.digests = None, None, None, {}, {}
        try:
            self.host.close()
        except Exception as error:
            errors.append(error)
        if errors:
            raise errors[0]


TARGET_EXECUTORS = {IOSSimulatorExecutor.NAME: "IOSSimulatorExecutor"}
