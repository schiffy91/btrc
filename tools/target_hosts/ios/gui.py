"""A BTRC GUI program as an iOS app: built with Xcode's own tools, run on one simulator.

The app is the program itself, linked with the shim provider's UIKit entry
(src/stdlib/GUI/IOS; ``-e _btrcUIKitMain``) and wgpu-native's static
library, in a bundle with the Info.plist a scene-based app needs and an
ad-hoc signature. Nothing is fetched.

A run launches the app with the program's arguments and environment, waits
for the result the program's thread leaves in the app's own container, and
returns it with what the program printed. Simulator results are never
physical-device evidence.
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import time
from pathlib import Path

from tools.target_hosts.ios.simhost import AppleEnvironment, IOSSimulatorHost, SimulatorError

EXECUTABLE = "BTRCProgram"
ENTRY = "_btrcUIKitMain"
ORIENTATIONS = [
    "UIInterfaceOrientationPortrait",
    "UIInterfaceOrientationPortraitUpsideDown",
    "UIInterfaceOrientationLandscapeLeft",
    "UIInterfaceOrientationLandscapeRight",
]


class GUIAppBuilder:
    """Packs one linked program into an app bundle for the simulator."""

    @staticmethod
    def link_flags(libraries):
        """What a program's link needs to be an app: the UIKit entry and wgpu-native's library directory."""
        return [f"-L{libraries}", f"-Wl,-e,{ENTRY}"]

    @staticmethod
    def package(*, program, identifier, label, output, resources=None):
        """The signed bundle of one program; `resources` maps a name in the bundle to a file or directory."""
        if not re.fullmatch(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+", identifier):
            raise ValueError("the bundle identifier must be a dotted name of letters, digits and hyphens")
        bundle = Path(output)
        shutil.rmtree(bundle, ignore_errors=True)
        bundle.mkdir(parents=True)
        shutil.copyfile(program, bundle / EXECUTABLE)
        (bundle / EXECUTABLE).chmod(0o755)
        for name, source in (resources or {}).items():
            target = bundle / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if Path(source).is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copyfile(source, target)
        (bundle / "Info.plist").write_bytes(
            plistlib.dumps(
                {
                    "CFBundleIdentifier": identifier,
                    "CFBundleExecutable": EXECUTABLE,
                    "CFBundleName": label,
                    "CFBundleDisplayName": label,
                    "CFBundlePackageType": "APPL",
                    "CFBundleVersion": "1",
                    "CFBundleShortVersionString": "1.0",
                    "MinimumOSVersion": "17.0",
                    "CFBundleSupportedPlatforms": ["iPhoneSimulator"],
                    "UIDeviceFamily": [1, 2],
                    "LSRequiresIPhoneOS": True,
                    # A launch screen is what lets the app have the whole screen.
                    "UILaunchScreen": {},
                    "UISupportedInterfaceOrientations": ORIENTATIONS[:1],
                    "UISupportedInterfaceOrientations~ipad": ORIENTATIONS,
                    "UIApplicationSceneManifest": {"UIApplicationSupportsMultipleScenes": True},
                }
            )
        )
        # What the bundle carries is signed before the bundle that seals it.
        for item in [*sorted(bundle.glob("Frameworks/*.dylib")), bundle]:
            signed = subprocess.run(
                [str(AppleEnvironment.XCRUN), "codesign", "--force", "--sign", "-", str(item)],
                capture_output=True,
                text=True,
                timeout=120,
                env=AppleEnvironment.variables(),
            )
            if signed.returncode:
                raise RuntimeError(f"codesign failed ({signed.returncode}): {signed.stderr}")
        return bundle


class GUIAppRunner:
    """Runs one installed app's program, one process at a time, on one booted simulator."""

    def __init__(self, host: IOSSimulatorHost, identifier: str):
        self.host, self.identifier = host, identifier
        self.container: Path | None = None

    def install(self, bundle):
        self.host.command("uninstall", self.host.device(), self.identifier, check=False)
        self.host.command("install", self.host.device(), str(bundle), timeout=300)
        located = self.host.command("get_app_container", self.host.device(), self.identifier, "data")
        self.container = Path(located.stdout.decode().strip())
        if not self.container.is_dir():
            raise SimulatorError(f"the app's data container {self.container} does not exist")

    def uninstall(self):
        self.host.command("terminate", self.host.device(), self.identifier, check=False)
        self.host.command("uninstall", self.host.device(), self.identifier, check=False)

    def put(self, directory, name):
        """Copy a directory into the app's container; its path there, as the app sees it."""
        target = self._container() / "Documents" / name
        shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(directory, target)
        return str(target)

    def _container(self) -> Path:
        if self.container is None:
            raise SimulatorError("the app is not installed")
        return self.container

    @staticmethod
    def _alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def run(self, arguments=(), environment=None, timeout=180):
        """(exit status or None, stdout, stderr): None when the program crashed or ran out of time."""
        output = self._container() / "tmp" / "btrc-run"
        shutil.rmtree(output, ignore_errors=True)
        output.mkdir(parents=True)
        values = {**(environment or {}), "BTRC_SHIM_OUTPUT": str(output)}
        launched = self.host.runner(
            [
                *self.host.tool(),
                "launch",
                "--terminate-running-process",
                self.host.device(),
                self.identifier,
                *arguments,
            ],
            capture_output=True,
            timeout=120,
            env=AppleEnvironment.child(values),
            check=False,
        )
        found = re.search(rb": (\d+)\s*$", launched.stdout)
        if launched.returncode or not found:
            raise SimulatorError(
                f"simctl launch failed ({launched.returncode}): {launched.stderr.decode(errors='replace').strip()}"
            )
        pid = int(found[1])
        deadline = time.monotonic() + timeout
        status = None
        result = output / "exit.txt"
        try:
            while time.monotonic() < deadline:
                if result.is_file():
                    status = int(result.read_text().strip())
                    break
                if not self._alive(pid):
                    # The result is written before the process ends: look once more.
                    if result.is_file():
                        status = int(result.read_text().strip())
                    break
                time.sleep(0.05)
        finally:
            self.host.command("terminate", self.host.device(), self.identifier, check=False)
        stdout = self._text(output / "stdout.txt")
        stderr = self._text(output / "stderr.txt")
        if status is None:
            stderr += self._crash(pid)
        return status, stdout, stderr

    @staticmethod
    def _text(path):
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""

    def _crash(self, pid):
        """What the simulator's log says of a program that left no result."""
        try:
            shown = self.host.command(
                "spawn",
                self.host.device(),
                "log",
                "show",
                "--last",
                "2m",
                "--style",
                "compact",
                "--predicate",
                f"processID == {pid} AND messageType >= 16",
                timeout=60,
                check=False,
            )
        except SimulatorError as error:
            return f"\n[no log: {error}]\n"
        lines = shown.stdout.decode(errors="replace").splitlines()
        return "\n[the program left no result; its last log lines]\n" + "\n".join(lines[-40:]) + "\n"
