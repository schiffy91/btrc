"""The Android emulator target executor, executor protocol 1 (CX-P1-09).

``src/tests/target_runner.py`` freezes the protocol and finds this class as
``android-emulator``. The module imports nothing from the runner.

Admission. ``prepare(bundle_dir, label)`` reads the bundle's ``bundle.json``
(``btrc.target-bundle/1``) for the ``targets.toml`` row ``label``, which must
be the bundle's own row and an Android row of `ROWS`, and refuses a device
whose primary ABI is not the row's: an arm64 program on an x86_64 image runs
under the image's binary translation, which is emulation, not evidence. Each
built program is copied to a host staging directory, checked against its
SHA-256, pushed once to a fresh directory under ``/data/local/tmp`` and
checked again there, by the device's own ``sha256sum``, before admission
commits. A failure removes that directory and leaves the executor as it was.

Launch. Every run is one ``adb shell -T`` command (shell protocol v2: raw
stdout and stderr streams and the remote exit status). It makes the run's
fresh cwd, re-checks the staged supervisor's and program's digests -- nothing
of an earlier run is alive by then, so the checked bytes are the launched
bytes -- and execs the supervisor (``supervisor.c``), which the executor
builds for the row with the NDK. The supervisor starts the program in its own
session from that cwd, with the staged stdin, the request's environment
overrides and arguments, enforces the deadline, and kills every descendant
before it reports.

Outcome. Only the supervisor's ``waitpid`` decides: its status line is the
last line of adb's stderr, after every byte the program wrote there, and the
adb command must exit 0. The program can write neither that line nor adb's
streams' ends (see ``supervisor.c``); a missing line, or a supervisor killed
from outside, is an infrastructure error, never an outcome. The request's
stdin is staged in a control directory beside, never inside, the run's cwd,
and nothing the program can write is read back.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from tools.target_hosts.android.avd import AvdManager

BUNDLE_SCHEMA = "btrc.target-bundle/1"
BUNDLE_MANIFEST = "bundle.json"
PROGRAM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
# The targets.toml rows this executor runs, and the primary ABI each needs.
ROWS = {"android-x86_64": "x86_64", "android-aarch64": "arm64-v8a"}
SUPERVISOR_SOURCE = Path(__file__).resolve().with_name("supervisor.c")
STATUS_PREFIX = b"BTRC-ANDROID-SUPERVISOR/1 "
STATUS_LINE = re.compile(rb"BTRC-ANDROID-SUPERVISOR/1 (exit|signal|timeout|launch-error) ([0-9]{1,10}) ([0-9]{1,20})\n")
# The supervisor's limit on -e pairs.
ENVIRONMENT_LIMIT = 256
# Retained per stream; more is an infrastructure error, never a truncated result.
OUTPUT_LIMIT_BYTES = 16 * 1024 * 1024
# Every adb call is bounded: an ordinary command, a bulk push, and the margin a
# launch gets beyond the program's own deadline for transport and cleanup.
ADB_TIMEOUT = 120
PUSH_TIMEOUT = 1800
LAUNCH_MARGIN = 30
# The NDK's prebuilt toolchain directory for each build host (as tools/native_plan.py).
NDK_HOSTS = {"darwin": "darwin-x86_64", "linux": "linux-x86_64", "win32": "windows-x86_64"}
# A launch command's own exits, before the supervisor replaces its shell.
PREFLIGHT = {
    90: "the run's cwd could not be created",
    91: "the run's cwd could not be entered",
    92: "the staged supervisor no longer matches its digest",
    93: "the staged program no longer matches its bundle digest",
}


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
    """Drain a child's stdout and stderr concurrently, failing past a fixed byte budget."""

    def __init__(self, process, limit=OUTPUT_LIMIT_BYTES):
        self.limit = limit
        self.buffers = [bytearray(), bytearray()]
        self.errors = []
        self.threads = [
            threading.Thread(target=self.read, args=(index, stream), daemon=True)
            for index, stream in enumerate((process.stdout, process.stderr))
        ]
        for thread in self.threads:
            thread.start()

    def read(self, index, stream):
        # Keep reading past the limit, so adb never blocks on a full pipe.
        try:
            with stream:
                while chunk := stream.read(65536):
                    room = self.limit - len(self.buffers[index])
                    if len(chunk) > room and not self.errors:
                        self.errors.append(
                            RuntimeError(f"the program's {('stdout', 'stderr')[index]} exceeded {self.limit} bytes")
                        )
                    self.buffers[index].extend(chunk[: max(room, 0)])
        except Exception as error:
            self.errors.append(error)

    def join(self, timeout):
        deadline = time.monotonic() + timeout
        for thread in self.threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self.threads):
            raise RuntimeError("adb's output pipes stayed open after it exited")
        if self.errors:
            raise self.errors[0]
        return bytes(self.buffers[0]), bytes(self.buffers[1])


class AdbTransport:
    """``adb -s SERIAL``: one command per call, each bounded in time and output."""

    def __init__(self, adb, serial):
        self.adb = Path(adb)
        self.serial = serial

    def command(self, *arguments):
        return [str(self.adb), "-s", self.serial, *arguments]

    def call(self, *arguments, timeout=ADB_TIMEOUT, input=b""):
        return subprocess.run(self.command(*arguments), input=input, capture_output=True, timeout=timeout, check=False)

    def stream(self, *arguments, timeout, limit=OUTPUT_LIMIT_BYTES):
        """Run one command, returning (status, stdout, stderr); TimeoutExpired after killing adb."""

        process = subprocess.Popen(
            self.command(*arguments), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        capture = BoundedOutput(process, limit)
        try:
            status = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
            with suppress(Exception):
                capture.join(10)
            raise
        stdout, stderr = capture.join(10)
        return status, stdout, stderr


class AndroidEmulatorExecutor:
    """Run an Android row's bundle on one emulator through adb's shell (executor protocol 1)."""

    NAME = "android-emulator"
    CWD_POLICIES: ClassVar[frozenset[str]] = frozenset({"isolated"})
    LAUNCH_MODES: ClassVar[frozenset[str]] = frozenset({"process"})
    OPTIONS: ClassVar[frozenset[str]] = frozenset({"sdk", "serial", "ndk", "boot", "state", "api", "port"})

    def __init__(
        self,
        sdk=None,
        serial="emulator-5554",
        *,
        ndk=None,
        avd=None,
        transport=None,
        device_root="/data/local/tmp",
        supervisor=None,
    ):
        if not re.fullmatch(r"emulator-[0-9]+", serial):
            raise ValueError("select one emulator serial explicitly")
        sdk = sdk or os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        if transport is None and not sdk:
            raise ValueError("name the Android SDK: sdk=, ANDROID_SDK_ROOT or ANDROID_HOME")
        self.serial = serial
        self.transport = transport or AdbTransport(Path(sdk) / "platform-tools" / "adb", serial)
        self.ndk = ndk
        # An AvdManager this executor boots on its first prepare and stops on close.
        self.avd = avd
        self.booted = None
        self.device_root = device_root.rstrip("/")
        # A supervisor already built for the row (the unit tests' host build); else the NDK builds one.
        self.prebuilt_supervisor = supervisor
        self.label, self.base, self.programs, self.supervisor_digest = None, None, {}, None
        self.capabilities = frozenset()
        self.provenance = {}
        self.runs = 0
        self.failed = False

    @classmethod
    def from_options(cls, options):
        """The runner's ``--executor-option`` pairs: sdk, serial, ndk; boot=true with state, api and port."""

        unknown = set(options) - cls.OPTIONS
        if unknown:
            raise ValueError(f"unknown android-emulator option(s): {', '.join(sorted(unknown))}")
        sdk = options.get("sdk") or os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        port = int(options.get("port", "5554"))
        avd = None
        if options.get("boot", "false").lower() in ("1", "true", "yes"):
            if not options.get("state"):
                raise ValueError("boot=true needs state=<AVD state directory>")
            avd = AvdManager(sdk, options["state"], api=options.get("api", "29"), port=port)
        return cls(sdk, options.get("serial", f"emulator-{port}"), ndk=options.get("ndk"), avd=avd)

    # Device commands ---------------------------------------------------------

    def device(self, command, *, timeout=ADB_TIMEOUT, check=True, input=b""):
        """One ``adb shell -T`` command (shell protocol v2: its exit status is the command's)."""

        completed = self.transport.call("shell", "-T", command, timeout=timeout, input=input)
        if check and completed.returncode != 0:
            raise RuntimeError(
                f"adb shell failed ({completed.returncode}) running {command[:200]!r}: "
                f"{completed.stderr.decode(errors='replace').strip()[-2000:]}"
            )
        return completed

    def push(self, local, remote, *, timeout=ADB_TIMEOUT):
        completed = self.transport.call("push", str(local), remote, timeout=timeout)
        if completed.returncode != 0:
            raise RuntimeError(
                f"adb push to {remote} failed ({completed.returncode}): {completed.stderr.decode(errors='replace')}"
            )

    def remove(self, *paths):
        """Remove device paths a run may have left unwritable; raise if one remains."""

        quoted = " ".join(shlex.quote(path) for path in paths)
        checks = " && ".join(f"[ ! -e {shlex.quote(path)} ]" for path in paths)
        self.device(f"chmod -R u+rwx {quoted} 2>/dev/null; rm -rf {quoted}; {checks}")

    def sweep(self):
        """Kill every device process of this executor's directory: its cwd there, or its command line naming it."""

        if self.base is None:
            return
        # A bracket keeps pkill's own shell, whose command line holds the pattern, out of the match.
        pattern = "[" + self.base[0] + "]" + re.sub(r"([.^$*+?(){}|\\\[\]])", r"\\\1", self.base[1:])
        self.device(
            "for p in /proc/[0-9]*; do "
            f'case "$(readlink "$p/cwd" 2>/dev/null)" in {shlex.quote(self.base)}/*) kill -9 "${{p#/proc/}}";; esac; '
            f"done 2>/dev/null; pkill -9 -f {shlex.quote(pattern)}; exit 0"
        )

    # Admission ---------------------------------------------------------------

    @staticmethod
    def read_bundle(bundle, label):
        document = json.loads((bundle / BUNDLE_MANIFEST).read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("schema") != BUNDLE_SCHEMA:
            raise ValueError(f"{bundle} holds no {BUNDLE_SCHEMA} bundle")
        target = document.get("target")
        built_for = target.get("label") if isinstance(target, dict) else None
        if built_for != label:
            raise ValueError(f"the bundle was built for {built_for!r}, not {label!r}")
        if label not in ROWS:
            raise ValueError(f"{label!r} is not an Android row this executor runs ({', '.join(sorted(ROWS))})")
        if not isinstance(target.get("triple"), str) or not target["triple"]:
            raise ValueError("the bundle names no target triple")
        if not isinstance(document.get("programs"), dict):
            raise ValueError("the bundle's programs must be a table")
        return document

    @staticmethod
    def artifact(bundle, program_id, entry):
        """The bundle file a built program names, refusing any other name or location."""

        if not PROGRAM_ID.fullmatch(program_id) or not isinstance(entry, dict):
            raise ValueError(f"invalid bundle program {program_id!r}")
        if entry.get("artifact") != program_id:
            raise ValueError(f"{program_id}: an Android executable's artifact is its program id")
        if not SHA256.fullmatch(str(entry.get("sha256") or "")):
            raise ValueError(f"{program_id}: the bundle records no SHA-256")
        path = bundle / entry["artifact"]
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(bundle):
            raise ValueError(f"{program_id}: the executable must be a regular file inside the bundle")
        return path

    @staticmethod
    def digest(path):
        hasher = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def acquire(self):
        """Boot this executor's own emulator once, if it owns one."""

        if self.avd is not None and self.booted is None:
            self.avd.create()
            self.booted = self.avd.boot()

    def inspect(self, label):
        """The device facts admission needs; refuse a device that would only translate the row's ABI."""

        names = {
            "abi": "ro.product.cpu.abi",
            "api": "ro.build.version.sdk",
            "fingerprint": "ro.build.fingerprint",
            "model": "ro.product.model",
            # The emulator's AVD name: ro.boot.qemu.* from API 30, ro.kernel.qemu.* before.
            "avd": "ro.boot.qemu.avd_name",
            "avd_kernel": "ro.kernel.qemu.avd_name",
        }
        listing = self.device("; ".join(f"getprop {name}" for name in names.values()) + "; getconf PAGESIZE")
        values = listing.stdout.decode(errors="replace").split("\n")
        if len(values) < len(names) + 1:
            raise RuntimeError(f"{self.serial} answered getprop with {listing.stdout!r}")
        facts = {key: values[index].strip() for index, key in enumerate(names)}
        older = facts.pop("avd_kernel")
        facts["avd"] = facts["avd"] or older
        facts["page_size"] = values[len(names)].strip()
        if facts["abi"] != ROWS[label]:
            raise ValueError(
                f"{label} needs a {ROWS[label]} device, but {self.serial}'s primary ABI is {facts['abi'] or 'unknown'}; "
                "a run there would be translated, and emulated runs are not evidence"
            )
        features = self.transport.call("features", timeout=ADB_TIMEOUT)
        listed = re.split(r"[\s,]+", features.stdout.decode(errors="replace"))
        if features.returncode != 0 or "shell_v2" not in listed:
            raise ValueError(f"{self.serial} lacks adb shell protocol v2, which carries the remote exit status")
        return facts

    def supervisor(self, triple, directory):
        """The supervisor for `triple`: the prebuilt one, else built with the NDK's clang."""

        output = directory / "supervisor"
        if self.prebuilt_supervisor is not None:
            shutil.copyfile(self.prebuilt_supervisor, output)
            return output, {"prebuilt": str(self.prebuilt_supervisor)}
        ndk = Path(self.ndk or os.environ.get("ANDROID_NDK_HOME") or "")
        clang = ndk / "toolchains" / "llvm" / "prebuilt" / NDK_HOSTS.get(sys.platform, sys.platform) / "bin" / "clang"
        if not str(ndk) or not clang.is_file():
            raise RuntimeError(f"building the supervisor needs the NDK's clang (ndk= or ANDROID_NDK_HOME): {clang}")
        flags = ["-std=c11", "-O2", "-pedantic-errors", "-Wall", "-Wextra", "-Werror"]
        completed = subprocess.run(
            [str(clang), f"--target={triple}", *flags, str(SUPERVISOR_SOURCE), "-o", str(output)],
            capture_output=True,
            text=True,
            timeout=ADB_TIMEOUT,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"the supervisor did not build for {triple}: {completed.stderr.strip()[-4000:]}")
        revision = None
        with suppress(OSError):
            found = re.search(r"^Pkg\.Revision\s*=\s*(\S+)", (ndk / "source.properties").read_text(), re.MULTILINE)
            revision = found[1] if found else None
        return output, {"ndk": revision, "target": triple, "cflags": flags}

    def staged_digests(self, base):
        """The SHA-256 of every file the device holds under ``base/programs``, by the device's sha256sum."""

        listing = self.device(
            f"cd {shlex.quote(base)}/programs && find . -type f -exec sha256sum {{}} +", timeout=PUSH_TIMEOUT
        )
        digests = {}
        for line in listing.stdout.decode(errors="replace").splitlines():
            found = re.fullmatch(r"([0-9a-f]{64})\s+\*?\./(\S+)", line.strip())
            if found is None:
                raise RuntimeError(f"sha256sum printed an unexpected line: {line!r}")
            digests[found[2]] = found[1]
        return digests

    def prepare(self, bundle_dir, label):
        bundle = Path(bundle_dir).resolve(strict=True)
        document = self.read_bundle(bundle, label)
        built = {
            program_id: (self.artifact(bundle, program_id, entry), entry["sha256"])
            for program_id, entry in sorted(document["programs"].items())
            if isinstance(entry, dict) and entry.get("status") == "built"
        }
        self.acquire()
        facts = self.inspect(label)
        base = f"{self.device_root}/btrc-{uuid.uuid4().hex}"
        staging = Path(tempfile.mkdtemp(prefix="btrc-android-executor-"))
        try:
            supervisor, supervisor_toolchain = self.supervisor(document["target"]["triple"], staging)
            supervisor_digest = self.digest(supervisor)
            programs = staging / "programs"
            programs.mkdir()
            for program_id, (source, expected) in built.items():
                shutil.copyfile(source, programs / program_id)
                if self.digest(programs / program_id) != expected:
                    raise ValueError(f"{program_id}: the staged copy does not match the bundle's SHA-256")
            quoted = shlex.quote(base)
            self.device(f"mkdir -m 700 {quoted} && mkdir -m 700 {quoted}/bin {quoted}/control {quoted}/runs")
            self.push(supervisor, f"{base}/bin/supervisor")
            if built:
                # A directory pushed to a path that does not exist yet lands as that path.
                self.push(programs, f"{base}/programs", timeout=PUSH_TIMEOUT)
            else:
                self.device(f"mkdir {quoted}/programs")
            self.device(
                f"chmod 700 {quoted}/programs && chmod 500 {quoted}/bin/supervisor && "
                f"find {quoted}/programs -type f -exec chmod 500 {{}} +",
                timeout=PUSH_TIMEOUT,
            )
            staged = self.staged_digests(base)
            expected = {program_id: digest for program_id, (_, digest) in built.items()}
            if staged != expected:
                wrong = sorted(set(staged) ^ set(expected) | {p for p in staged if staged[p] != expected.get(p)})
                raise ValueError(f"the device's staged copies differ from the bundle: {', '.join(wrong[:10])}")
            on_device = self.device(f"sha256sum < {quoted}/bin/supervisor").stdout.decode(errors="replace")
            if not on_device.startswith(supervisor_digest + " "):
                raise ValueError("the device's staged supervisor differs from the one built")
            probe = self.device(f"{quoted}/bin/supervisor --probe-loopback", check=False)
            capabilities = frozenset(
                {"loopback-listener"} if probe.returncode == 0 and probe.stdout == b"loopback-listener ok\n" else ()
            )
        except BaseException as error:
            with suppress(Exception):
                self.remove(base)
            if self.avd is not None and self.booted is not None:
                error.add_note(f"the executor's emulator stays up until close: {self.booted}")
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        self.release()
        self.label, self.base, self.supervisor_digest = label, base, supervisor_digest
        self.programs = {program_id: digest for program_id, (_, digest) in built.items()}
        self.capabilities = capabilities
        self.provenance = {
            "executor": self.NAME,
            "device": f"{facts['model'] or 'unknown model'} ({self.serial})",
            "os_build": facts["fingerprint"],
            "toolchain": document.get("toolchain", {}),
            "label": label,
            "abi": facts["abi"],
            "api": facts["api"],
            "avd": facts["avd"] or None,
            "page_size": facts["page_size"],
            "supervisor": {"sha256": supervisor_digest, **supervisor_toolchain},
        }

    def granted_capabilities(self):
        return self.capabilities

    # Execution ---------------------------------------------------------------

    def check_request(self, request):
        if request.program_id not in self.programs:
            raise ValueError(f"unknown program_id: {request.program_id}")
        timeout = request.timeout_s
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int | float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout_s must be a positive finite number of seconds")
        if request.cwd_policy not in self.CWD_POLICIES:
            raise ValueError(
                f"the Android executor runs in {sorted(self.CWD_POLICIES)} cwds, not {request.cwd_policy!r}"
            )
        if getattr(request, "launch_mode", "process") not in self.LAUNCH_MODES or getattr(request, "app_roots", ()):
            raise ValueError("the Android executor launches ordinary processes through adb's shell, with no app roots")
        if not all(isinstance(value, str) and "\0" not in value for value in request.argv):
            raise ValueError("argv must hold NUL-free strings")
        if len(request.env) > ENVIRONMENT_LIMIT or not all(
            ENVIRONMENT_NAME.fullmatch(name) and "\0" not in value for name, value in request.env.items()
        ):
            raise ValueError("env must map at most 256 names matching [A-Za-z_][A-Za-z0-9_]* to NUL-free values")

    def launch(self, request, cwd, stdin):
        """The device command for one run: fresh cwd, digest re-checks, then the supervisor."""

        supervisor = f"{self.base}/bin/supervisor"
        program = f"{self.base}/programs/{request.program_id}"
        arguments = [supervisor, "-t", repr(float(request.timeout_s)), "-i", stdin]
        for name, value in sorted(request.env.items()):
            arguments += ["-e", f"{name}={value}"]
        arguments += ["--", program, *request.argv]
        quote = shlex.quote
        return (
            f"mkdir -m 700 {quote(cwd)} || exit 90; cd {quote(cwd)} || exit 91; "
            f'case "$(sha256sum < {quote(supervisor)})" in "{self.supervisor_digest} "*) ;; *) exit 92;; esac; '
            f'case "$(sha256sum < {quote(program)})" in "{self.programs[request.program_id]} "*) ;; *) exit 93;; esac; '
            f"exec {shlex.join(arguments)}"
        )

    @staticmethod
    def outcome(status, stdout, stderr):
        """(exit_status, signal, stdout, stderr, timed_out, duration_s) from one launch, or raise."""

        start = stderr.rfind(STATUS_PREFIX)
        found = STATUS_LINE.fullmatch(stderr[start:]) if start >= 0 else None
        if status != 0 or found is None:
            if found is None and status in PREFLIGHT:
                raise RuntimeError(f"the launch failed before the supervisor ran: {PREFLIGHT[status]}")
            detail = stderr[-2000:].decode(errors="replace").strip() or "no diagnostics"
            raise RuntimeError(f"the supervisor reported no outcome (adb exited {status}): {detail}")
        kind, value, microseconds = found[1].decode(), int(found[2]), int(found[3])
        if kind == "launch-error":
            raise RuntimeError(f"the supervisor could not start the program: {os.strerror(value)} (errno {value})")
        if (kind == "exit" and value > 255) or (kind == "signal" and not 1 <= value <= 64):
            raise RuntimeError(f"the supervisor reported an impossible {kind} {value}")
        return (
            value if kind == "exit" else None,
            value if kind == "signal" else None,
            stdout,
            stderr[:start],
            kind == "timeout",
            microseconds / 1e6,
        )

    def run(self, request):
        if self.base is None:
            raise RuntimeError("prepare a bundle before running")
        self.check_request(request)
        self.runs += 1
        cwd = f"{self.base}/runs/{self.runs}"
        stdin = "/dev/null"
        staged = []
        warnings = []
        try:
            if request.stdin:
                stdin = f"{self.base}/control/{self.runs}.stdin"
                with tempfile.TemporaryDirectory(prefix="btrc-android-stdin-") as directory:
                    local = Path(directory) / "stdin"
                    local.write_bytes(request.stdin)
                    self.push(local, stdin)
                staged.append(stdin)
            try:
                status, stdout, stderr = self.transport.stream(
                    "shell", "-T", self.launch(request, cwd, stdin), timeout=request.timeout_s + LAUNCH_MARGIN
                )
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(
                    f"adb shell outlived the supervisor's {request.timeout_s:g}s deadline by {LAUNCH_MARGIN}s"
                ) from error
            result = self.outcome(status, stdout, stderr)
        except BaseException as error:
            self.failed = True
            for action, what in ((self.sweep, "process sweep"), (lambda: self.remove(cwd, *staged), "cleanup")):
                try:
                    action()
                except Exception as cleanup:
                    error.add_note(f"Android {what} also failed: {cleanup}")
            raise
        try:
            self.remove(cwd, *staged)
        except Exception as cleanup:
            warnings.append(f"removing the run's cwd failed: {cleanup}")
        return ExecutionResult(*result, {**self.provenance, "cleanup_warnings": warnings})

    # Release -----------------------------------------------------------------

    def release(self):
        """Remove the device directory of the bundle admitted last."""

        if self.base is not None:
            with suppress(Exception):
                self.sweep()
            with suppress(Exception):
                self.remove(self.base)
        self.label, self.base, self.programs, self.supervisor_digest = None, None, {}, None
        self.capabilities = frozenset()

    def close(self):
        self.release()
        if self.avd is not None and self.booted is not None:
            try:
                if self.failed:
                    self.avd.diagnostics()
            finally:
                self.avd.close()
                self.booted = None


TARGET_EXECUTORS = {AndroidEmulatorExecutor.NAME: "AndroidEmulatorExecutor"}
