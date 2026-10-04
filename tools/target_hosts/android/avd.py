"""Create, boot and stop one explicitly named KVM Android emulator."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from tools.target_hosts.android.sdk import SDKVersions


class AvdManager:
    def __init__(self, sdk, state, *, api="29", port=5554):
        self.sdk, self.state = Path(sdk).resolve(), Path(state).resolve()
        versions = SDKVersions()
        if api not in versions.apis or port % 2 or not 5554 <= port <= 5682:
            raise ValueError("choose a pinned API and an even emulator port between 5554 and 5682")
        self.api, self.port = api, port
        self.name = f"btrc-api-{api}-x86_64-{port}"
        self.serial = f"emulator-{port}"
        self.process = None
        self.log = None
        self.environment = {
            **os.environ,
            "ANDROID_AVD_HOME": str(self.state / "avd"),
            "ANDROID_USER_HOME": str(self.state / "android"),
        }
        self.commandline = self.sdk / "cmdline-tools" / versions.commandline / "bin"

    def adb(self, *arguments, **kwargs):
        return subprocess.run(
            [str(self.sdk / "platform-tools/adb"), "-s", self.serial, *arguments],
            capture_output=True,
            timeout=kwargs.pop("timeout", 15),
            **kwargs,
        )

    def create(self):
        (self.state / "avd").mkdir(parents=True, exist_ok=True)
        if (self.state / "avd" / f"{self.name}.avd/config.ini").is_file():
            return
        subprocess.run(
            [
                str(self.commandline / "avdmanager"),
                "create",
                "avd",
                "--name",
                self.name,
                "--package",
                f"system-images;android-{self.api};google_apis;x86_64",
                "--device",
                "pixel",
                "--force",
            ],
            input=b"no\n",
            env=self.environment,
            check=True,
            timeout=120,
        )

    def boot(self, timeout_s=240):
        if not os.access("/dev/kvm", os.R_OK | os.W_OK):
            raise RuntimeError("Android execution requires a KVM runner; /dev/kvm is unavailable")
        if self.process is not None:
            raise RuntimeError("this manager already owns an emulator process")
        self.state.mkdir(parents=True, exist_ok=True)
        self.log = (self.state / f"{self.name}.log").open("wb")
        started = time.monotonic()
        self.process = subprocess.Popen(
            [
                str(self.sdk / "emulator/emulator"),
                "-avd",
                self.name,
                "-port",
                str(self.port),
                "-no-window",
                "-no-audio",
                "-no-boot-anim",
                "-gpu",
                "swiftshader_indirect",
                "-accel",
                "on",
                "-no-snapshot-save",
                *(
                    ["-snapshot", "btrc-clean"]
                    if (self.state / "avd" / f"{self.name}.avd/snapshots/btrc-clean").is_dir()
                    else []
                ),
            ],
            env=self.environment,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        try:
            while time.monotonic() - started < timeout_s:
                if self.process.poll() is not None:
                    raise RuntimeError(f"emulator exited during boot; see {self.log.name}")
                ready = self.adb("shell", "getprop", "sys.boot_completed")
                if ready.returncode == 0 and ready.stdout.strip() == b"1":
                    page = self.adb("shell", "getconf", "PAGESIZE", check=True).stdout.strip()
                    if page != b"4096":
                        raise RuntimeError(f"x86_64 image unexpectedly reports page size {page!r}")
                    return {
                        "serial": self.serial,
                        "api": self.api,
                        "page_size": int(page),
                        "boot_s": time.monotonic() - started,
                    }
                time.sleep(1)
            raise TimeoutError(f"emulator did not boot within {timeout_s}s")
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process is not None:
            # Only terminate the process this manager launched; never another AVD.
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def snapshot(self):
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("boot this manager's AVD before saving a snapshot")
        self.adb("emu", "avd", "snapshot", "save", "btrc-clean", timeout=120, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "smoke"))
    parser.add_argument("--sdk", type=Path, default=os.environ.get("ANDROID_SDK_ROOT"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--api", default="29")
    parser.add_argument("--port", type=int, default=5554)
    args = parser.parse_args(argv)
    if args.sdk is None:
        parser.error("--sdk or ANDROID_SDK_ROOT is required")
    manager = AvdManager(args.sdk, args.state, api=args.api, port=args.port)
    manager.create()
    if args.action == "smoke":
        try:
            print(json.dumps(manager.boot(), sort_keys=True))
        finally:
            manager.close()


if __name__ == "__main__":
    main()
