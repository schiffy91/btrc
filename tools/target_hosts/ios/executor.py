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
    def __init__(self, *, mode: str = "spawn", device_class: str = "iphone", host=None, launch_timeout_s: float = 30):
        if mode not in {"spawn", "app"}:
            raise ValueError("mode must be spawn or app")
        if not math.isfinite(launch_timeout_s) or launch_timeout_s <= 0:
            raise ValueError("launch_timeout_s must be finite and positive")
        self.launch_timeout_s = launch_timeout_s
        self.mode = mode
        self.host = host if host is not None else IOSSimulatorHost(device_class)
        self.bundle_dir: Path | None = None
        self.programs: dict = {}
        self.host_provenance: dict = {}
        self._active_identity: tuple[int, bool] | None = None

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
        launch_deadline = launched_at + self.launch_timeout_s
        execution_deadline = None
        identity = None
        first_identity_s = None
        while True:
            observed = self._identity(directory)
            if identity is not None and observed not in (None, identity):
                raise SimulatorError("Test-host process identity changed during execution")
            identity = observed or identity
            self._active_identity = identity
            if identity and first_identity_s is None:
                first_identity_s = time.monotonic() - launched_at
                execution_deadline = time.monotonic() + timeout
                # The wrapper never invokes fixture code without this acknowledgement.
                (directory / "start").touch()
            terminal = (directory / "exit_status").exists() or (directory / "signal_status").exists()
            if terminal:
                if identity is None:
                    raise SimulatorError("Host reported a result before its process identity")
                if not self.host.alive(identity[0]):
                    return False, identity, first_identity_s
            if not terminal and launcher is not None and launcher.poll() is not None:
                if (directory / "exit_status").exists() or (directory / "signal_status").exists():
                    continue
                raise SimulatorError("simctl spawn exited without a test-host result")
            if not terminal and identity and not self.host.alive(identity[0]):
                if (directory / "exit_status").exists() or (directory / "signal_status").exists():
                    continue
                raise SimulatorError("Simulator child disappeared without a terminal result")
            if identity is None and time.monotonic() >= launch_deadline:
                raise SimulatorError("Test host never published its process identity before the launch deadline")
            if execution_deadline is not None and time.monotonic() >= execution_deadline:
                self._stop_child(identity)
                return True, identity, first_identity_s
            time.sleep(0.02)

    def _cleanup_spawn(self, directory: Path, launcher) -> tuple[bytes, bytes]:
        # Cancel before waiting: a late wrapper cannot begin executing the fixture.
        (directory / "cancel").touch()
        deadline = time.monotonic() + 3
        identity = self._active_identity
        identity_error = None
        while time.monotonic() < deadline:
            try:
                identity = identity or self._identity(directory)
            except SimulatorError as error:
                identity_error = error
                break
            if identity is not None:
                break
            if launcher.poll() is not None:
                # Read again after observing exit, covering atomic publication races.
                identity = self._identity(directory)
                break
            time.sleep(0.02)
        errors = []
        if identity_error is not None:
            errors.append(identity_error)
        try:
            if identity and self.host.alive(identity[0]):
                self._stop_child(identity)
        except Exception as error:
            errors.append(error)
        try:
            output = self.host.stop_launcher(launcher)
        except Exception as error:
            errors.append(error)
            output = (b"", b"")
        # The client can exit just as its child atomically publishes the identity.
        if identity is None and identity_error is None:
            try:
                identity = self._identity(directory)
                if identity and self.host.alive(identity[0]):
                    self._stop_child(identity)
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("Simulator spawn cleanup failed", errors)
        return output

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
        self._active_identity = None
        primary_error = None
        directory = None
        launcher_output = (b"", b"")
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
                    marker = container / "tmp" / "btrc-previous-invocation"
                    if marker.exists():
                        raise SimulatorError("App data survived reinstall; fresh container proof failed")
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text(uuid.uuid4().hex)
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
                        timeout=self.launch_timeout_s,
                        env=self.host.child_environment(values),
                    )
                launch_duration = time.monotonic() - launch_started
                timed_out, identity, cold_launch = self._wait(
                    directory, request.timeout_s, launcher, launched_at=launch_started
                )
                launcher_status = None
                if launcher is not None:
                    launcher_output = self.host.stop_launcher(launcher)
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
                    simctl_stdout=launcher_output[0].decode(errors="replace"),
                    simctl_stderr=launcher_output[1].decode(errors="replace"),
                    app_container=str(container) if self.mode == "app" else None,
                    app_container_marker_absent=self.mode == "app",
                    timeout_kill_verified=timed_out,
                    cleanup_scope="direct-process-only",
                    process_group_isolated=identity[1] if identity else False,
                )
                return ExecutionResult(
                    status, signum, stdout, stderr, timed_out, time.monotonic() - started, provenance
                )
            except BaseException as error:
                primary_error = error
                raise
            finally:
                cleanup_errors = []
                if launcher is not None and directory is not None:
                    try:
                        launcher_output = self._cleanup_spawn(directory, launcher)
                    except Exception as error:
                        cleanup_errors.append(error)
                if installed:
                    for cleanup in (
                        lambda: self.host.terminate_app(bundle_id),
                        lambda: self.host.command("uninstall", self.host.device(), bundle_id),
                    ):
                        try:
                            cleanup()
                        except Exception as error:
                            cleanup_errors.append(error)
                if primary_error is not None:
                    primary_error.add_note(
                        f"simctl stdout: {launcher_output[0].decode(errors='replace')}; "
                        f"stderr: {launcher_output[1].decode(errors='replace')}"
                    )
                    for error in cleanup_errors:
                        primary_error.add_note(f"Cleanup also failed: {error!r}")
                elif cleanup_errors:
                    raise ExceptionGroup("Simulator cleanup failed", cleanup_errors)

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
