"""Owned CoreSimulator device lifecycle for the standalone CX-P1-04 spike."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path


class SimulatorError(RuntimeError):
    """Host tooling failed; this is not a successful test-program exit."""


class IOSSimulatorHost:
    """Manage a named iPhone or iPad; never erase a device implicitly."""

    def __init__(self, device_class: str = "iphone", *, runner=subprocess.run):
        if device_class not in {"iphone", "ipad"}:
            raise ValueError("device_class must be iphone or ipad")
        self.device_class = device_class
        self.runner = runner
        self.udid: str | None = None
        self.runtime: dict = {}
        self.booted_here = False

    def command(self, *args: str, timeout: float = 60, env: dict | None = None, check: bool = True):
        result = self.runner(["xcrun", "simctl", *args], capture_output=True, timeout=timeout, env=env, check=False)
        if check and result.returncode:
            raise SimulatorError(
                f"simctl {args[0]} failed ({result.returncode}): {result.stderr.decode(errors='replace')}"
            )
        return result

    @staticmethod
    def _version(runtime: dict) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in runtime["version"].split("."))
        except (KeyError, ValueError) as error:
            raise SimulatorError("simctl returned an invalid runtime version") from error

    def prepare(self, *, erase: bool = False) -> None:
        inventory = json.loads(self.command("list", "-j").stdout)
        available = [
            row
            for row in inventory["runtimes"]
            if row.get("isAvailable")
            and row["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-")
            and self._version(row) >= (17,)
        ]
        if not available:
            raise SimulatorError("No available iOS >= 17 simulator runtime; install one on the Apple host")
        self.runtime = max(available, key=self._version)
        name = f"btrc-host-{self.device_class}"
        family = "iPhone" if self.device_class == "iphone" else "iPad"
        candidates = [
            row
            for row in inventory["devices"].get(self.runtime["identifier"], [])
            if row["name"] == name and row.get("isAvailable")
        ]
        if len(candidates) > 1:
            raise SimulatorError(f"Multiple {name} devices on the selected runtime; choose a clean host inventory")
        if candidates:
            device = candidates[0]
            device_type = next(
                (row for row in inventory["devicetypes"] if row["identifier"] == device.get("deviceTypeIdentifier")),
                None,
            )
            if device_type is None or not device_type["name"].startswith(family):
                raise SimulatorError(f"Named {name} device does not match requested device class")
        else:
            supported = {row["identifier"] for row in self.runtime.get("supportedDeviceTypes", [])}
            types = [
                row
                for row in inventory["devicetypes"]
                if row["name"].startswith(family) and (not supported or row["identifier"] in supported)
            ]
            if not types:
                raise SimulatorError(f"Selected runtime has no {family} device type")
            # simctl's device type list is SDK-owned; retain its order rather than
            # guess hardware capabilities from model-number spelling.
            udid = (
                self.command("create", name, types[-1]["identifier"], self.runtime["identifier"])
                .stdout.decode()
                .strip()
            )
            if not udid:
                raise SimulatorError("simctl create returned no device identifier")
            device = {"udid": udid, "state": "Shutdown"}
        self.udid = device["udid"]
        if erase:
            if device["state"] == "Booted":
                self.command("shutdown", self.udid)
            self.command("erase", self.udid)
            device["state"] = "Shutdown"
        if device["state"] != "Booted":
            self.command("boot", self.udid)
            self.booted_here = True
        self.command("bootstatus", self.udid, "-b", timeout=300)

    def device(self) -> str:
        if not self.udid:
            raise SimulatorError("Simulator host is not prepared")
        return self.udid

    @staticmethod
    def child_environment(values: dict[str, str]) -> dict[str, str]:
        # Do not inherit old SIMCTL_CHILD_* assignments from a previous request.
        result = {key: value for key, value in os.environ.items() if not key.startswith("SIMCTL_CHILD_")}
        result.update({f"SIMCTL_CHILD_{key}": value for key, value in values.items()})
        return result

    def spawn(self, executable: Path, argv: tuple[str, ...], env: dict[str, str]):
        return subprocess.Popen(
            ["xcrun", "simctl", "spawn", self.device(), str(executable), *argv],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.child_environment(env),
            start_new_session=True,
        )

    def alive(self, pid: int) -> bool:
        if pid <= 1:
            raise SimulatorError("Refusing unsafe simulator process id")
        # CoreSimulator processes share the host kernel/PID namespace. Avoid
        # launching another simulator executable merely to send a POSIX signal.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError as error:
            raise SimulatorError("Cannot inspect the simulator child process") from error
        return True

    def send_signal(self, pid: int, number: int, *, group: bool = False) -> None:
        if pid <= 1:
            raise SimulatorError("Refusing unsafe simulator process id")
        try:
            if group:
                os.killpg(pid, number)
            else:
                os.kill(pid, number)
        except ProcessLookupError:
            pass  # The child exited between the liveness check and the signal.

    def terminate_app(self, bundle_id: str) -> None:
        self.command("terminate", self.device(), bundle_id, check=False)

    def close(self) -> None:
        if self.udid and self.booted_here:
            self.command("shutdown", self.udid)
            self.booted_here = False

    def provenance(self) -> dict:
        version = self.runner(["xcodebuild", "-version"], capture_output=True, check=True, timeout=30)
        return {
            "executor": "ios-simulator",
            "device": self.device(),
            "device_class": self.device_class,
            "runtime": self.runtime["identifier"],
            "os_build": self.runtime.get("buildversion", "unknown"),
            "toolchain": version.stdout.decode().strip(),
            "evidence": "stand-in",
        }

    def diagnose(self, output: Path) -> None:
        """Retain bounded host observations without changing simulator state."""
        output.mkdir(parents=True, exist_ok=True)
        commands = {
            "devices": ["xcrun", "simctl", "list", "devices", "-j"],
            "capacity": ["/usr/sbin/sysctl", "hw.memsize", "hw.ncpu"],
            "memory": ["/usr/bin/vm_stat"],
            "processes": ["/bin/ps", "-axo", "pid,ppid,rss,stat,comm"],
            "services": [
                "/usr/bin/log",
                "show",
                "--last",
                "5m",
                "--style",
                "compact",
                "--predicate",
                'process == "CoreSimulatorService" OR process == "launchd_sim" OR process == "SimulatorTrampoline"',
            ],
        }
        observations = {}
        for name, command in commands.items():
            started = time.monotonic()
            stdout = stderr = b""
            row = {"command": command, "timeout_s": 10}
            try:
                result = self.runner(command, capture_output=True, timeout=10, check=False)
                stdout, stderr = result.stdout, result.stderr
                row["returncode"] = result.returncode
            except subprocess.TimeoutExpired as error:
                stdout, stderr = error.stdout or b"", error.stderr or b""
                row["error"] = repr(error)
            except Exception as error:
                row["error"] = repr(error)
            row["duration_s"] = time.monotonic() - started
            (output / f"{name}.stdout").write_bytes(stdout)
            (output / f"{name}.stderr").write_bytes(stderr)
            observations[name] = row
        (output / "commands.json").write_text(json.dumps(observations, indent=2) + "\n")

    @staticmethod
    def stop_launcher(process) -> tuple[bytes, bytes]:
        """Reap the local simctl client only after stopping the simulator child."""
        try:
            return process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            try:
                return process.communicate(timeout=3)
            except subprocess.TimeoutExpired as error:
                # Descendants can retain pipe writers after the client exits.
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
                raise SimulatorError("simctl client did not drain/reap after SIGKILL") from error
