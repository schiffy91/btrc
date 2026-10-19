"""The CoreSimulator device the iOS simulator executor runs programs on (CX-P1-04, CX-P1-08).

`IOSSimulatorHost` selects the newest available iOS runtime at or above the
row's minimum (17.0), or the runtime an option names, finds or creates one
named device of the requested class (``btrc-host-iphone``,
``btrc-host-ipad``), boots it and waits for its boot status. It shuts the
device down only when it booted it, and never erases one implicitly.

Every simctl call goes through Xcode's own ``/usr/bin/xcrun`` with its own
deadline. A Nix shell's ``DEVELOPER_DIR`` and ``SDKROOT`` name only its macOS
SDK, so they are dropped (as ``tools.native_plan.TargetToolchain`` drops them
for an Apple cross row) and the selected Xcode answers. Hosted macOS runners
have three CPUs and 7 GiB: CoreSimulator's first ``simctl list`` has outlasted
60 s there (test_native_uikit_application.py allows 180 s), so the listing
gets 180 s and one retry.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, ClassVar


class SimulatorError(RuntimeError):
    """Host tooling failed: a launch, transport or cleanup error, never a program outcome."""


class AppleEnvironment:
    """The process environment Xcode's tools run in, outside any Nix shell's SDK."""

    XCRUN = Path("/usr/bin/xcrun")
    SHELL_VARIABLES = ("DEVELOPER_DIR", "SDKROOT")
    CHILD_PREFIX = "SIMCTL_CHILD_"

    @classmethod
    def variables(cls, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """`base` (the process environment) without a Nix SDK or an earlier request's child variables."""

        source = os.environ if base is None else base
        return {
            name: value
            for name, value in source.items()
            if not name.startswith(cls.CHILD_PREFIX)
            and not (name in cls.SHELL_VARIABLES and value.startswith("/nix/store/"))
        }

    @classmethod
    def child(cls, values: Mapping[str, str], base: Mapping[str, str] | None = None) -> dict[str, str]:
        """The environment for one ``simctl spawn``: simctl hands ``SIMCTL_CHILD_<name>`` to the child as ``<name>``."""

        environment = cls.variables(base)
        environment.update({f"{cls.CHILD_PREFIX}{name}": value for name, value in values.items()})
        return environment


class IOSSimulatorHost:
    """One booted iPhone or iPad simulator, owned for the lifetime of an executor."""

    FAMILIES: ClassVar[Mapping[str, str]] = {"iphone": "iPhone", "ipad": "iPad"}
    RUNTIME_PREFIX = "com.apple.CoreSimulator.SimRuntime.iOS-"
    LIST_TIMEOUT_S = 180
    COMMAND_TIMEOUT_S = 120
    BOOT_TIMEOUT_S = 300
    BOOTSTATUS_TIMEOUT_S = 600

    def __init__(
        self,
        device_class: str = "iphone",
        *,
        minimum: tuple[int, ...] = (17, 0),
        runtime: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
        spawner: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        xcrun: Path = AppleEnvironment.XCRUN,
    ) -> None:
        if device_class not in self.FAMILIES:
            raise ValueError(f"device_class must be one of {sorted(self.FAMILIES)}, not {device_class!r}")
        self.device_class = device_class
        self.minimum = minimum
        self.requested_runtime = runtime
        self.runner = runner
        self.spawner = spawner
        self.xcrun = xcrun
        self.simctl: str | None = None
        self.udid: str | None = None
        self.runtime: dict[str, Any] = {}
        self.device_type: dict[str, Any] = {}
        self.booted_here = False

    # simctl -----------------------------------------------------------------

    def tool(self) -> list[str]:
        """simctl itself once resolved (a spawn per program skips xcrun), else ``xcrun simctl``."""

        return [self.simctl] if self.simctl else [str(self.xcrun), "simctl"]

    def command(self, *arguments: str, timeout: float = COMMAND_TIMEOUT_S, check: bool = True):
        try:
            result = self.runner(
                [*self.tool(), *arguments],
                capture_output=True,
                timeout=timeout,
                env=AppleEnvironment.variables(),
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise SimulatorError(f"simctl {arguments[0]} did not answer within {timeout:g} s") from error
        if check and result.returncode:
            raise SimulatorError(
                f"simctl {arguments[0]} failed ({result.returncode}): {result.stderr.decode(errors='replace').strip()}"
            )
        return result

    def resolve(self) -> None:
        """Find simctl through Xcode's xcrun, once."""

        try:
            found = self.runner(
                [str(self.xcrun), "--find", "simctl"],
                capture_output=True,
                timeout=self.COMMAND_TIMEOUT_S,
                env=AppleEnvironment.variables(),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SimulatorError(f"xcrun cannot find simctl: {error}") from error
        path = found.stdout.decode(errors="replace").strip()
        if found.returncode or not path:
            raise SimulatorError(f"xcrun cannot find simctl: {found.stderr.decode(errors='replace').strip()}")
        self.simctl = path

    def inventory(self) -> dict[str, Any]:
        """``simctl list -j``; CoreSimulator's first answer on a cold runner is slow, so it gets one retry."""

        try:
            listed = self.command("list", "-j", timeout=self.LIST_TIMEOUT_S)
        except SimulatorError:
            listed = self.command("list", "-j", timeout=self.LIST_TIMEOUT_S)
        try:
            return json.loads(listed.stdout)
        except ValueError as error:
            raise SimulatorError(f"simctl list returned no JSON: {error}") from error

    # Selection --------------------------------------------------------------

    @staticmethod
    def version(runtime: Mapping[str, Any]) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in str(runtime["version"]).split("."))
        except (KeyError, ValueError) as error:
            raise SimulatorError(f"simctl lists an invalid runtime version: {runtime!r}") from error

    def select_runtime(self, inventory: Mapping[str, Any]) -> dict[str, Any]:
        available = [
            row
            for row in inventory.get("runtimes", [])
            if row.get("isAvailable")
            and str(row.get("identifier", "")).startswith(self.RUNTIME_PREFIX)
            and self.version(row) >= self.minimum
        ]
        if self.requested_runtime:
            wanted = self.requested_runtime
            available = [
                row
                for row in available
                if wanted in (row["identifier"], row["version"]) or str(row["version"]).startswith(f"{wanted}.")
            ]
        if not available:
            floor = ".".join(str(part) for part in self.minimum)
            wanted = f" matching {self.requested_runtime!r}" if self.requested_runtime else ""
            raise SimulatorError(f"no available iOS >= {floor} simulator runtime{wanted}; install one with Xcode")
        return max(available, key=self.version)

    def select_device(self, inventory: Mapping[str, Any]) -> dict[str, Any]:
        name = f"btrc-host-{self.device_class}"
        family = self.FAMILIES[self.device_class]
        types = {row["identifier"]: row for row in inventory.get("devicetypes", [])}
        candidates = [
            row
            for row in inventory.get("devices", {}).get(self.runtime["identifier"], [])
            if row.get("name") == name and row.get("isAvailable")
        ]
        if len(candidates) > 1:
            raise SimulatorError(f"several {name} devices exist on {self.runtime['identifier']}; remove the extras")
        if candidates:
            device = candidates[0]
            device_type = types.get(device.get("deviceTypeIdentifier"))
            if device_type is None or not device_type["name"].startswith(family):
                raise SimulatorError(f"{name} is not an {family} device")
            self.device_type = device_type
            return device
        supported = {row["identifier"] for row in self.runtime.get("supportedDeviceTypes", [])}
        matching = [
            row
            for row in inventory.get("devicetypes", [])
            if row["name"].startswith(family) and (not supported or row["identifier"] in supported)
        ]
        if not matching:
            raise SimulatorError(f"the {self.runtime['identifier']} runtime supports no {family} device type")
        # simctl lists device types in its SDK's order, newest models last.
        self.device_type = matching[-1]
        created = self.command("create", name, self.device_type["identifier"], self.runtime["identifier"])
        udid = created.stdout.decode(errors="replace").strip()
        if not udid:
            raise SimulatorError("simctl create returned no device identifier")
        return {"udid": udid, "state": "Shutdown"}

    # Lifecycle --------------------------------------------------------------

    def prepare(self) -> None:
        """Boot the device (once per host) and wait until it is usable."""

        if self.udid is not None:
            return
        self.resolve()
        inventory = self.inventory()
        self.runtime = self.select_runtime(inventory)
        device = self.select_device(inventory)
        udid = device["udid"]
        booted_here = False
        if device.get("state") != "Booted":
            self.command("boot", udid, timeout=self.BOOT_TIMEOUT_S)
            booted_here = True
        try:
            self.command("bootstatus", udid, "-b", timeout=self.BOOTSTATUS_TIMEOUT_S)
        except BaseException:
            if booted_here:
                with suppress(SimulatorError):
                    self.command("shutdown", udid)
            raise
        self.udid, self.booted_here = udid, booted_here

    def device(self) -> str:
        if not self.udid:
            raise SimulatorError("the simulator host is not prepared")
        return self.udid

    def spawn(self, argv: Sequence[str], env: Mapping[str, str]) -> subprocess.Popen[bytes]:
        """``simctl spawn`` one program in the booted device; the client runs in a session of its own."""

        return self.spawner(
            [*self.tool(), "spawn", self.device(), *argv],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=AppleEnvironment.child(env),
            start_new_session=True,
        )

    @staticmethod
    def kill_group(pid: int) -> None:
        """SIGKILL a simulator process group. CoreSimulator processes share the host kernel, so this is direct."""

        if pid <= 1:
            raise SimulatorError(f"refusing to signal process group {pid}")
        with suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)

    def close(self) -> None:
        if self.udid and self.booted_here:
            udid, self.booted_here = self.udid, False
            self.command("shutdown", udid)
        self.udid = None

    def provenance(self) -> dict[str, Any]:
        """The device class and runtime build, never a device identifier, host or user name."""

        if not self.runtime:
            raise SimulatorError("the simulator host is not prepared")
        return {
            "device": f"{self.device_type.get('name', self.FAMILIES[self.device_class])} simulator",
            "device_class": self.device_class,
            "os_build": f"iOS {self.runtime.get('version', '?')} ({self.runtime.get('buildversion', 'unrecorded')})",
            "runtime": self.runtime.get("identifier"),
        }

    def diagnose(self, output: Path) -> None:
        """Retain bounded read-only host observations after a failure, changing no simulator state."""

        output.mkdir(parents=True, exist_ok=True)
        commands = {
            "devices": [*self.tool(), "list", "devices", "-j"],
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
            row: dict[str, Any] = {"command": command, "timeout_s": 10}
            try:
                result = self.runner(
                    command, capture_output=True, timeout=10, env=AppleEnvironment.variables(), check=False
                )
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
        (output / "commands.json").write_text(json.dumps(observations, indent=2) + "\n", encoding="utf-8")
