"""Standalone CL-P1-17-shaped executor; no import of the pending runner core.

prepare(bundle_dir, label); run(ExecutionRequest) -> ExecutionResult; close().
The dataclasses mirror the documented protocol until CL-P1-17 freezes it.
Only ios-aarch64-simulator is admitted. Host failures raise SimulatorError;
they never masquerade as a program exit or an unavailable-but-passed fixture.
"""

from __future__ import annotations

import json
import math
import re
import signal
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from tools.target_hosts.ios.simhost import IOSSimulatorHost, SimulatorError


@dataclass(frozen=True)
class ExecutionRequest:
    program_id: str
    argv: tuple[str, ...] = ()
    stdin: bytes = b""
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 10
    cwd_policy: str = "temp"


@dataclass(frozen=True)
class ExecutionResult:
    exit_status: int | None
    signal: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    duration_s: float
    provenance: dict


class IOSSimulatorExecutor:
    def __init__(self, *, mode: str = "spawn", device_class: str = "iphone", host=None):
        if mode not in {"spawn", "app"}:
            raise ValueError("mode must be spawn or app")
        self.mode = mode
        self.host = host if host is not None else IOSSimulatorHost(device_class)
        self.bundle_dir: Path | None = None
        self.programs: dict = {}
        self.host_provenance: dict = {}

    def prepare(self, bundle_dir: str | Path, label: str) -> None:
        if label != "ios-aarch64-simulator":
            raise ValueError("The simulator executor requires ios-aarch64-simulator")
        root = Path(bundle_dir).resolve(strict=True)
        manifest = json.loads((root / "programs.json").read_text())
        if manifest.get("schema") != "btrc.ios-testhost/1" or manifest.get("target") != label:
            raise ValueError("Invalid simulator test bundle manifest")
        self.bundle_dir = root
        self.programs = manifest["programs"]
        for program_id, row in self.programs.items():
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", program_id):
                raise ValueError("Unsafe program id")
            if not re.fullmatch(r"dev\.btrc\.testhost\.[A-Za-z0-9-]+", row["bundle_id"]):
                raise ValueError("Bundle id must be inside dev.btrc.testhost")
            for key in ("spawn", "app"):
                self._artifact(row[key])
        self.host.prepare()
        self.host_provenance = self.host.provenance()

    def _artifact(self, relative: str) -> Path:
        assert self.bundle_dir is not None
        path = (self.bundle_dir / relative).resolve(strict=True)
        if not path.is_relative_to(self.bundle_dir) or path == self.bundle_dir:
            raise ValueError("Program artifact escapes its bundle")
        return path

    @staticmethod
    def _validate(request: ExecutionRequest) -> None:
        if not math.isfinite(request.timeout_s) or request.timeout_s <= 0:
            raise ValueError("timeout_s must be finite and positive")
        if request.cwd_policy not in {"temp", "bundle"}:
            raise ValueError("cwd_policy must be temp or bundle")
        if not isinstance(request.stdin, bytes):
            raise ValueError("stdin must be bytes")
        for arg in request.argv:
            if not isinstance(arg, str) or "\0" in arg:
                raise ValueError("argv must contain NUL-free strings")
        for key, value in request.env.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key.startswith("BTRC_TESTHOST_"):
                raise ValueError("Invalid or reserved environment name")
            if not isinstance(value, str) or "\0" in value:
                raise ValueError("Environment values must be NUL-free strings")

    @staticmethod
    def _identity(directory: Path) -> tuple[int, bool] | None:
        path = directory / "process"
        if not path.exists():
            return None
        fields = path.read_text().split()
        if len(fields) != 2 or not all(value.isdecimal() for value in fields):
            raise SimulatorError("Invalid test-host process identity")
        pid, pgid = (int(value) for value in fields)
        if pid <= 1:
            raise SimulatorError("Refusing unsafe simulator process id")
        return pid, pgid == pid

    def _stop_child(self, identity: tuple[int, bool]) -> None:
        pid, own_group = identity
        self.host.send_signal(pid, signal.SIGTERM, group=own_group)
        deadline = time.monotonic() + 0.5
        while self.host.alive(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        if self.host.alive(pid):
            self.host.send_signal(pid, signal.SIGKILL, group=own_group)
        deadline = time.monotonic() + 3
        while self.host.alive(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        if self.host.alive(pid):
            raise SimulatorError("Timed-out simulator child is still alive after SIGKILL")

    def _wait(self, directory: Path, timeout: float, launcher=None, *, launched_at: float):
        deadline = time.monotonic() + timeout
        identity = None
        first_identity_s = None
        while True:
            identity = self._identity(directory) or identity
            if identity and first_identity_s is None:
                first_identity_s = time.monotonic() - launched_at
            terminal = (directory / "exit_status").exists() or (directory / "signal_status").exists()
            if terminal:
                if identity is None:
                    raise SimulatorError("Host reported a result before its process identity")
                if not self.host.alive(identity[0]):
                    return False, identity, first_identity_s
            if not terminal and launcher is not None and launcher.poll() is not None:
                raise SimulatorError("simctl spawn exited without a test-host result")
            if not terminal and identity and not self.host.alive(identity[0]):
                if (directory / "exit_status").exists() or (directory / "signal_status").exists():
                    continue
                raise SimulatorError("Simulator child disappeared without a terminal result")
            if time.monotonic() >= deadline:
                if identity is None:
                    raise SimulatorError("Test host never published its process identity; launch failed")
                self._stop_child(identity)
                return True, identity, first_identity_s
            time.sleep(0.02)

    @staticmethod
    def _collect(directory: Path, timed_out: bool) -> tuple[int | None, int | None, bytes, bytes]:
        exit_path, signal_path = directory / "exit_status", directory / "signal_status"
        if not timed_out and exit_path.exists() == signal_path.exists():
            raise SimulatorError("Expected exactly one terminal test-host status")
        exit_status = int(exit_path.read_text()) if exit_path.exists() and not timed_out else None
        signal_status = int(signal_path.read_text()) if signal_path.exists() else None
        if exit_status is not None and not 0 <= exit_status <= 255:
            raise SimulatorError("Invalid program exit status")
        if signal_status is not None and not 1 <= signal_status <= 127:
            raise SimulatorError("Invalid program signal")
        return exit_status, signal_status, (directory / "stdout").read_bytes(), (directory / "stderr").read_bytes()

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        self._validate(request)
        if self.bundle_dir is None or request.program_id not in self.programs:
            raise ValueError("Unknown program or executor not prepared")
        row = self.programs[request.program_id]
        artifact = self._artifact(row[self.mode])
        started = time.monotonic()
        launcher = None
        installed = False
        bundle_id = row["bundle_id"]
        with tempfile.TemporaryDirectory(prefix="btrc-ios-") as temporary:
            staging = Path(temporary)
            try:
                if self.mode == "app":
                    # Uninstall first: each invocation must use a fresh container.
                    previous = self.host.command(
                        "get_app_container", self.host.device(), bundle_id, "data", check=False
                    )
                    if previous.returncode == 0:
                        self.host.command("uninstall", self.host.device(), bundle_id)
                    self.host.command("install", self.host.device(), str(artifact), timeout=120)
                    installed = True
                    container = Path(
                        self.host.command("get_app_container", self.host.device(), bundle_id, "data")
                        .stdout.decode()
                        .strip()
                    )
                    if not container.is_absolute() or not container.is_dir():
                        raise SimulatorError("simctl returned no accessible app data container")
                    directory = container / "tmp" / f"btrc-run-{uuid.uuid4().hex}"
                else:
                    directory = staging / "result"
                directory.mkdir(parents=True)
                work = directory / "work"
                work.mkdir()
                (directory / "stdin").write_bytes(request.stdin)
                values = dict(request.env)
                bundle_cwd = artifact.parent
                if self.mode == "app" and request.cwd_policy == "bundle":
                    bundle_cwd = Path(
                        self.host.command("get_app_container", self.host.device(), bundle_id, "app")
                        .stdout.decode()
                        .strip()
                    )
                    if not bundle_cwd.is_absolute() or not bundle_cwd.is_dir():
                        raise SimulatorError("simctl returned no accessible installed app bundle")
                values.update(
                    BTRC_TESTHOST_DIR=str(directory),
                    BTRC_TESTHOST_CWD=str(work if request.cwd_policy == "temp" else bundle_cwd),
                )
                launch_started = time.monotonic()
                if self.mode == "spawn":
                    launcher = self.host.spawn(artifact, tuple(request.argv), values)
                else:
                    self.host.command(
                        "launch",
                        "--terminate-running-process",
                        self.host.device(),
                        bundle_id,
                        *request.argv,
                        timeout=min(request.timeout_s + 5, 120),
                        env=self.host.child_environment(values),
                    )
                launch_duration = time.monotonic() - launch_started
                timed_out, identity, cold_launch = self._wait(
                    directory, request.timeout_s, launcher, launched_at=launch_started
                )
                launcher_status = None
                if launcher is not None:
                    self.host.stop_launcher(launcher)
                    launcher_status = launcher.returncode
                    launcher = None
                status, signum, stdout, stderr = self._collect(directory, timed_out)
                provenance = dict(self.host_provenance)
                provenance.update(
                    mode=self.mode,
                    program_id=request.program_id,
                    cold_launch_s=cold_launch,
                    launch_command_s=launch_duration,
                    simctl_spawn_status=launcher_status,
                    timeout_kill_verified=timed_out,
                    process_group_isolated=identity[1] if identity else False,
                )
                return ExecutionResult(
                    status, signum, stdout, stderr, timed_out, time.monotonic() - started, provenance
                )
            finally:
                if installed:
                    self.host.terminate_app(bundle_id)
                    self.host.command("uninstall", self.host.device(), bundle_id)
                if launcher is not None:
                    # A failed poll or malformed result also has to stop a live child.
                    try:
                        identity = self._identity(directory)
                        if identity and self.host.alive(identity[0]):
                            self._stop_child(identity)
                    finally:
                        self.host.stop_launcher(launcher)

    def close(self) -> None:
        self.host.close()

    @staticmethod
    def write_result(result: ExecutionResult, output: Path) -> None:
        output.mkdir(parents=True, exist_ok=True)
        (output / "stdout").write_bytes(result.stdout)
        (output / "stderr").write_bytes(result.stderr)
        metadata = {
            "exit_status": result.exit_status,
            "signal": result.signal,
            "timed_out": result.timed_out,
            "duration_s": result.duration_s,
            "provenance": result.provenance,
        }
        (output / "result.json").write_text(json.dumps(metadata, indent=2) + "\n")
