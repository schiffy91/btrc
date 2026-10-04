"""Standalone CL-P1-17-shaped Android shell and NativeActivity executor.

The runner core is not imported until its contract lands. A bundle's
programs.json maps program IDs to {mode, executable} or {mode, apk, package}.
All paths are relative to the bundle; every execution gets fresh writable data.
"""

from __future__ import annotations

import json
import math
import re
import shlex
import struct
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ExecutionRequest:
    program_id: str
    argv: tuple[str, ...] = ()
    stdin: bytes = b""
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 10
    cwd_policy: str = "isolated"


@dataclass(frozen=True)
class ExecutionResult:
    exit_status: int | None
    signal: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    duration_s: float
    provenance: dict


class AndroidEmulatorExecutor:
    def __init__(self, sdk, serial, *, transport=None):
        self.adb_path = Path(sdk) / "platform-tools/adb"
        if not re.fullmatch(r"emulator-[0-9]+", serial):
            raise ValueError("select one emulator serial explicitly")
        self.serial = serial
        self.transport = transport or subprocess.run
        self.bundle = None
        self.programs = {}
        self.base = f"/data/local/tmp/btrc/{uuid.uuid4().hex}"

    def adb(self, *arguments, timeout=30, check=True, input=None):
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

    def prepare(self, bundle_dir, label):
        self.bundle = Path(bundle_dir).resolve()
        self.programs = json.loads((self.bundle / "programs.json").read_text())
        if not isinstance(self.programs, dict):
            raise ValueError("programs.json must map IDs to bundle artifacts")
        for identifier, program in self.programs.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier) or program.get("mode") not in ("shell", "app"):
                raise ValueError("invalid bundle program ID or mode")
            self.artifact(program, "executable" if program["mode"] == "shell" else "apk")
            if program["mode"] == "shell":
                self.artifact(program, "supervisor")
            if program["mode"] == "app" and not re.fullmatch(
                r"dev\.btrc\.testhost(?:\.[a-z][a-z0-9_]*)+", program.get("package", "")
            ):
                raise ValueError("app package must be inside dev.btrc.testhost")
        self.adb("shell", "mkdir", "-p", self.base)
        self.provenance = {
            "executor": "android-emulator",
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
        program = self.programs[request.program_id]
        for key in ("install_s", "launch_s"):
            self.provenance.pop(key, None)
        started = time.monotonic()
        result = self.shell(request, program) if program["mode"] == "shell" else self.app(request, program)
        return ExecutionResult(*result, time.monotonic() - started, {**self.provenance, "mode": program["mode"]})

    def shell(self, request, program):
        remote = f"{self.base}/{uuid.uuid4().hex}"
        self.adb("shell", "mkdir", "-p", remote)
        try:
            self.adb("push", str(self.artifact(program, "executable")), f"{remote}/program")
            self.adb("push", str(self.artifact(program, "supervisor")), f"{remote}/supervisor")
            self.adb("shell", "chmod", "700", f"{remote}/program", f"{remote}/supervisor")
            with tempfile.TemporaryDirectory(prefix="btrc-android-") as directory:
                stdin = Path(directory) / "stdin"
                stdin.write_bytes(request.stdin)
                self.adb("push", str(stdin), f"{remote}/stdin")
                arguments = [
                    "env",
                    *(f"{key}={value}" for key, value in request.env.items()),
                    "toybox",
                    "timeout",
                    "-s",
                    "KILL",
                    str(request.timeout_s + 5),
                    "./supervisor",
                    str(request.timeout_s),
                    "./program",
                    *request.argv,
                ]
                command = f"cd {shlex.quote(remote)} && {shlex.join(arguments)} <stdin 2>stderr"
                completed = self.adb("shell", "-T", command, timeout=request.timeout_s + 15, check=False)
                stderr = self.adb("exec-out", "cat", f"{remote}/stderr").stdout
                if completed.returncode:
                    raise RuntimeError(
                        "adb transport or outer supervisor guard failed while executing the shell fixture"
                    )
                marker = self.adb("exec-out", "cat", f"{remote}/status").stdout.split()
                if len(marker) != 3:
                    raise RuntimeError("shell supervisor did not write a complete status")
                code, signal, deadline = map(int, marker)
                if not -1 <= code <= 255 or not 0 <= signal <= 64 or deadline not in (0, 1):
                    raise RuntimeError("shell supervisor wrote an invalid status")
                return (None if signal or deadline else code, signal or None, completed.stdout, stderr, bool(deadline))
        finally:
            self.adb("shell", "rm", "-rf", remote, check=False)

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
        self.adb("uninstall", package, check=False)
        installed = time.monotonic()
        self.adb("install", "-r", str(self.artifact(program, "apk")), timeout=120)
        self.provenance["install_s"] = time.monotonic() - installed
        try:
            self.adb("shell", "run-as", package, "mkdir", "-p", "files")
            for name, payload in (("request.bin", self.configuration(request)), ("stdin", request.stdin)):
                self.adb("exec-in", "run-as", package, "sh", "-c", shlex.quote(f"cat > files/{name}"), input=payload)
            launched = time.monotonic()
            self.adb("shell", "am", "start", "-W", "-n", f"{package}/android.app.NativeActivity")
            self.provenance["launch_s"] = time.monotonic() - launched
            deadline = time.monotonic() + request.timeout_s
            status = None
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    completed = self.adb(
                        "exec-out",
                        "run-as",
                        package,
                        "cat",
                        "files/exit_status",
                        timeout=min(remaining, 15),
                        check=False,
                    )
                except subprocess.TimeoutExpired as error:
                    if remaining > 15:
                        raise RuntimeError("adb app status transport stalled before the program deadline") from error
                    break
                if completed.returncode == 255:
                    raise RuntimeError("adb transport failed while polling app status")
                if completed.returncode == 0:
                    status = int(completed.stdout.strip())
                    break
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            timed_out = status is None
            if timed_out:
                self.stop_app(package)
            stdout = self.adb("exec-out", "run-as", package, "cat", "files/stdout", check=False).stdout
            stderr = self.adb("exec-out", "run-as", package, "cat", "files/stderr", check=False).stdout
            signal = self.adb("exec-out", "run-as", package, "cat", "files/signal", check=False)
            signum = int(signal.stdout.strip()) if signal.returncode == 0 else None
            return (None if timed_out or signum else status, signum, stdout, stderr, timed_out)
        finally:
            try:
                self.stop_app(package)
            finally:
                self.adb("uninstall", package)

    def stop_app(self, package):
        self.adb("shell", "am", "force-stop", package)
        if self.adb("shell", "pidof", package, check=False).stdout.strip():
            raise RuntimeError("app process survived force-stop")

    def close(self):
        if self.bundle is not None:
            self.adb("shell", "rm", "-rf", self.base, check=False)
            self.bundle = None
