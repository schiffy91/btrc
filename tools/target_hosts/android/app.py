"""The NativeActivity app-mode spike (CX-P1-05): one fixture APK per program on a fresh sandbox.

A bundle's ``programs.json`` maps program IDs to ``{mode: "app", apk,
package}``, with paths relative to the bundle. Every execution reinstalls the
package, so it starts from fresh app data. The corpus runs through the
protocol-1 shell executor (``executor.py``); this mode stays a spike for C
fixtures until the mobile host contract (CX-P2-41) defines app roots.
"""

from __future__ import annotations

import json
import math
import re
import shlex
import struct
import subprocess
import time
from pathlib import Path

from tools.target_hosts.android.executor import ExecutionResult


class NativeActivityExecutor:
    def __init__(self, sdk, serial, *, transport=None):
        self.adb_path = Path(sdk) / "platform-tools/adb"
        if not re.fullmatch(r"emulator-[0-9]+", serial):
            raise ValueError("select one emulator serial explicitly")
        self.serial = serial
        self.transport = transport or subprocess.run
        self.bundle = None
        self.programs = {}

    def adb(self, *arguments, timeout=30, check=True, input=b""):
        completed = self.transport(
            [str(self.adb_path), "-s", self.serial, *arguments],
            input=input,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if check and completed.returncode:
            raise RuntimeError(
                f"adb {' '.join(arguments[:3])} failed ({completed.returncode}): {completed.stderr.decode(errors='replace')}"
            )
        return completed

    def remote(self, *arguments, **options):
        # shell -T uses shell-v2: binary streams, separate stderr and remote status.
        # Unlike exec-in/out, shell joins its arguments without escaping them.
        return self.adb("shell", "-T", shlex.join(arguments), **options)

    def app_file(self, package, name, *, optional=False, timeout=30):
        # A dedicated missing-file status distinguishes pending from a failed cat
        # or run-as. Raw exec-out cannot make that distinction (it returns 0).
        path = shlex.quote(f"files/{name}")
        completed = self.remote(
            "run-as",
            package,
            "sh",
            "-c",
            f"if [ ! -e {path} ]; then exit 42; fi; cat {path}",
            timeout=timeout,
            check=False,
        )
        if optional and completed.returncode == 42:
            return None
        if completed.returncode:
            raise RuntimeError(
                f"adb app file transport failed for {name} ({completed.returncode}): "
                f"{completed.stderr.decode(errors='replace')}"
            )
        return completed.stdout

    @staticmethod
    def status_number(payload, name, maximum):
        if not re.fullmatch(rb"[0-9]{1,3}\n?", payload) or int(payload) > maximum:
            raise RuntimeError(f"app wrote an invalid {name}")
        return int(payload)

    def prepare(self, bundle_dir, label):
        self.bundle = Path(bundle_dir).resolve()
        self.programs = json.loads((self.bundle / "programs.json").read_text())
        if not isinstance(self.programs, dict):
            raise ValueError("programs.json must map IDs to bundle artifacts")
        for identifier, program in self.programs.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier) or program.get("mode") != "app":
                raise ValueError("invalid bundle program ID or mode")
            self.artifact(program, "apk")
            if not re.fullmatch(r"dev\.btrc\.testhost(?:\.[a-z][a-z0-9_]*)+", program.get("package", "")):
                raise ValueError("app package must be inside dev.btrc.testhost")
        self.provenance = {
            "executor": "android-native-activity",
            "device": self.serial,
            "label": label,
            "os_build": self.adb("shell", "getprop", "ro.build.fingerprint").stdout.decode().strip(),
            "toolchain": json.loads((self.bundle / "toolchain.json").read_text())
            if (self.bundle / "toolchain.json").is_file()
            else {},
        }

    def artifact(self, program, key):
        path = (self.bundle / program[key]).resolve()
        if not path.is_relative_to(self.bundle) or not path.is_file():
            raise ValueError(f"bundle {key} must name an existing file inside the bundle")
        return path

    @staticmethod
    def validate(request):
        if request.cwd_policy != "isolated":
            raise ValueError("the spike supports only cwd_policy='isolated'; other policies need the runner contract")
        if not math.isfinite(request.timeout_s) or request.timeout_s <= 0:
            raise ValueError("timeout_s must be positive and finite")
        if not all(isinstance(value, str) and "\0" not in value for value in request.argv):
            raise ValueError("argv must contain NUL-free strings")
        for key, value in request.env.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or "\0" in value:
                raise ValueError("invalid environment key or NUL in value")

    def run(self, request):
        self.validate(request)
        if self.bundle is None:
            raise RuntimeError("prepare a bundle before running")
        if request.program_id not in self.programs:
            raise ValueError(f"unknown program_id: {request.program_id}")
        program = self.programs[request.program_id]
        for key in ("install_s", "launch_s", "launch_command_s"):
            self.provenance.pop(key, None)
        started = time.monotonic()
        result = self.app(request, program)
        return ExecutionResult(*result, time.monotonic() - started, {**self.provenance, "mode": "app"})

    @staticmethod
    def configuration(request):
        values = bytearray()

        def number(value):
            values.extend(struct.pack("<I", value))

        def string(value):
            encoded = value.encode()
            number(len(encoded))
            values.extend(encoded)

        number(len(request.argv) + 1)
        for value in (request.program_id, *request.argv):
            string(value)
        number(len(request.env))
        for key, value in request.env.items():
            string(key)
            string(value)
        return bytes(values)

    def app(self, request, program):
        package = program["package"]
        # A unique package per fixture and uninstall/install guarantee a clean sandbox.
        self.uninstall_app(package)
        primary_error = None
        try:
            installed = time.monotonic()
            self.adb("install", "-r", str(self.artifact(program, "apk")), timeout=120)
            self.provenance["install_s"] = time.monotonic() - installed
            self.adb("shell", "run-as", package, "mkdir", "-p", "files")
            for name, payload in (("request.bin", self.configuration(request)), ("stdin", request.stdin)):
                self.remote("run-as", package, "sh", "-c", f"cat > files/{name}", input=payload)
            launched = time.monotonic()
            # -W waits for a displayed activity. A fixture can publish its
            # terminal status and finish before the first frame, leaving that
            # display wait pending even though the program has completed.
            # Wait on the native host's result protocol below instead.
            self.adb("shell", "am", "start", "-n", f"{package}/android.app.NativeActivity")
            self.provenance["launch_command_s"] = time.monotonic() - launched
            launch_deadline = launched + 30
            while (remaining := launch_deadline - time.monotonic()) > 0:
                ready = self.app_file(package, "ready", optional=True, timeout=min(remaining, 15))
                if ready is not None:
                    if ready != b"1\n":
                        raise RuntimeError("app wrote an invalid ready marker")
                    break
                time.sleep(min(0.05, max(0, launch_deadline - time.monotonic())))
            else:
                raise RuntimeError("app did not become ready before the launch deadline")
            self.provenance["launch_s"] = time.monotonic() - launched
            deadline = time.monotonic() + request.timeout_s
            self.remote(
                "run-as", package, "sh", "-c", "cat > files/start", input=b"1\n", timeout=min(request.timeout_s, 15)
            )
            status = None
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    payload = self.app_file(package, "exit_status", optional=True, timeout=min(remaining, 15))
                except subprocess.TimeoutExpired as error:
                    if remaining > 15:
                        raise RuntimeError("adb app status transport stalled before the program deadline") from error
                    break
                if payload is not None:
                    status = self.status_number(payload, "exit status", 255)
                    break
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            timed_out = status is None
            if timed_out:
                self.stop_app(package)
            stdout = self.app_file(package, "stdout", optional=timed_out) or b""
            stderr = self.app_file(package, "stderr", optional=timed_out) or b""
            signal = self.app_file(package, "signal", optional=timed_out)
            signum = self.status_number(signal, "signal", 64) if signal is not None else 0
            return (None if timed_out or signum else status, signum or None, stdout, stderr, timed_out)
        except BaseException as error:
            primary_error = error
            raise
        finally:
            errors = []
            for cleanup in (self.stop_app, self.uninstall_app):
                try:
                    cleanup(package)
                except Exception as error:
                    errors.append(error)
            if primary_error is not None:
                for error in errors:
                    primary_error.add_note(f"Android cleanup also failed: {error!r}")
            elif errors:
                raise ExceptionGroup("Android app cleanup failed", errors)

    def uninstall_app(self, package):
        result = self.adb("uninstall", package, check=False)
        if result.returncode == 0:
            return
        # "Not installed" and a genuine uninstall failure may have the same adb
        # status. Only a successful package query proving absence permits reuse.
        inventory = self.adb("shell", "pm", "list", "packages", package).stdout.decode(errors="replace").splitlines()
        if any(not re.fullmatch(r"package:[A-Za-z0-9_.]+", line) for line in inventory):
            raise RuntimeError("adb returned an invalid package inventory after uninstall failure")
        if f"package:{package}" in inventory:
            raise RuntimeError(f"adb uninstall failed and {package} is still installed")

    def stop_app(self, package):
        self.adb("shell", "am", "force-stop", package)
        deadline = time.monotonic() + 2
        while True:
            # The poll budget bounds retries while a process is still present.
            # adb keeps its transport timeout: a slow reply can prove absence,
            # but a timed-out or failed query cannot prove shutdown.
            result = self.adb("shell", "pidof", package, check=False)
            if result.returncode not in (0, 1) or result.stderr:
                raise RuntimeError("adb transport failed while verifying app shutdown")
            if not result.stdout.strip():
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("app process survived force-stop")
            time.sleep(min(0.05, remaining))

    def close(self):
        self.bundle = None
