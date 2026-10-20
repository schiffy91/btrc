"""Temporary, branch-only diagnosis of the 93e08 Wayland NativeShell crash."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "93e08bd65ac4e60805cd7b89b2e8d7e221b60eaf"
NODE = "src/tests/python/test_native_ui_shell_linux.py::test_linux_native_shell[plain-python]"


class WaylandShellDiagnostic:
    """Retain one original shell trial and fail closed on debugger errors."""

    @staticmethod
    def enabled():
        return os.environ.get("BTRC_WAYLAND93_DIAGNOSTIC") == "1"

    @staticmethod
    def record_command(command):
        if WaylandShellDiagnostic.enabled():
            output = Path(os.environ["BTRC_WAYLAND93_OUTPUT"])
            with (output / "native-build-commands.jsonl").open("a") as stream:
                stream.write(json.dumps([str(item) for item in command]) + "\n")

    @staticmethod
    def stop_inferior(status_path, executable):
        """Signal only the still-owned Linux inferior, through a stable pidfd."""
        cleanup = {}
        descriptor = None
        try:
            status = json.loads(status_path.read_text())
            pid = status.get("pid")
            cleanup["pid"] = pid
            if type(pid) is not int or pid <= 1:
                cleanup["result"] = "no recorded inferior"
                return cleanup
            # A pidfd prevents PID reuse between identity inspection and kill.
            # The path and inode must still name this trial's NativeShell.
            descriptor = os.pidfd_open(pid)
            actual = Path(f"/proc/{pid}/exe")
            cleanup["executable"] = os.readlink(actual)
            expected_stat, actual_stat = Path(executable).stat(), actual.stat()
            if actual.resolve() != Path(executable).resolve() or (actual_stat.st_dev, actual_stat.st_ino) != (
                expected_stat.st_dev,
                expected_stat.st_ino,
            ):
                cleanup["result"] = "identity mismatch; not signalled"
                return cleanup
            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            cleanup["result"] = "owned inferior sent SIGKILL"
        except (ProcessLookupError, FileNotFoundError):
            cleanup["result"] = "inferior already gone or not recorded"
        except (OSError, ValueError) as error:
            cleanup["result"] = "cleanup failed"
            cleanup["error"] = str(error)
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return cleanup

    @staticmethod
    def shell(command, *, capture_output, text, env, timeout):
        assert capture_output and text
        assert sys.platform == "linux" and platform.machine() == "x86_64"
        assert env["SDL_VIDEODRIVER"] == "wayland" and command[1] == "100"
        output = Path(command[0]).parent
        status_path = output / "gdb-status.json"
        assert not status_path.exists(), "refusing stale debugger evidence"
        script = ROOT / "tools/ui/wayland93_gdb.py"
        debugger = [
            os.environ["BTRC_WAYLAND93_GDB"],
            "--nx",
            "--quiet",
            "--batch",
            "--return-child-result",
            "-ex",
            f"python exec(compile(open({str(script)!r}).read(), {str(script)!r}, 'exec'))",
            "--args",
            *command,
        ]
        (output / "gdb-command.json").write_text(json.dumps(debugger, indent=2) + "\n")
        environment = {**env, "BTRC_WAYLAND93_CASE": str(output)}
        began = time.monotonic()
        process = subprocess.Popen(
            debugger,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
            start_new_session=True,
        )
        timed_out = False
        cleanup = None
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Ask GDB to stop and capture the live inferior first. GDB can
            # place the inferior in another process group, so group cleanup
            # alone does not prove the native process is gone.
            process.send_signal(signal.SIGINT)
            try:
                stdout, stderr = process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                cleanup = WaylandShellDiagnostic.stop_inferior(status_path, command[0])
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired as error:
                    cleanup["pipe_drain"] = "timed out after debugger kill"
                    stdout, stderr = error.stdout or b"", error.stderr or b""
                    stdout = stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout
                    stderr = stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr
                    process.stdout.close()
                    process.stderr.close()
                    process.wait(timeout=5)
            if cleanup is None:
                cleanup = WaylandShellDiagnostic.stop_inferior(status_path, command[0])
        (output / "gdb.stdout").write_text(stdout)
        (output / "gdb.stderr").write_text(stderr)
        receipt = {
            "debugger_returncode": process.returncode,
            "timeout": timed_out,
            "elapsed_seconds": time.monotonic() - began,
            "executable_sha256": hashlib.sha256(Path(command[0]).read_bytes()).hexdigest(),
            "timeout_cleanup": cleanup,
        }
        try:
            receipt["inferior"] = json.loads(status_path.read_text())
        except (OSError, ValueError) as error:
            receipt["status_error"] = str(error)
        (output / "gdb-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        inferior = receipt.get("inferior", {})
        passed = (
            not timed_out
            and process.returncode == 0
            and inferior.get("state") == "exited"
            and inferior.get("exit_code") == 0
        )
        code = 0 if passed else (124 if timed_out else process.returncode or 125)
        return subprocess.CompletedProcess(command, code, stdout, stderr + "\n" + json.dumps(receipt))

    @staticmethod
    def command(command, output):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
        output.write_text(result.stdout + result.stderr)
        return result

    @classmethod
    def run(cls):
        output = Path(os.environ["BTRC_WAYLAND93_OUTPUT"])
        assert output.is_dir() and not (output / "provenance.json").exists()
        assert cls.enabled() and os.environ["BTRC_UI_SHELL_CYCLES"] == "100"
        assert sys.platform == "linux" and platform.machine() == "x86_64"
        assert os.environ["SDL_VIDEODRIVER"] == "wayland"
        allowed = {
            ".github/workflows/ci.yml",
            "src/tests/python/native_ui_shell_fixtures.py",
            "tools/ui/wayland93.py",
            "tools/ui/wayland93.sh",
            "tools/ui/wayland93_gdb.py",
        }
        changed = subprocess.check_output(
            ["git", "diff", "--name-only", BASE, "HEAD"], cwd=ROOT, text=True
        ).splitlines()
        assert set(changed) <= allowed, changed
        assert not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True
        ).strip(), "tracked source changed after diagnostic checkout"
        provenance = {
            "production_revision": BASE,
            "diagnostic_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "diagnostic_paths": changed,
            "node": NODE,
            "cycles": 100,
            "optimization": 2,
            "diagnostic_build_change": "debug symbols added; original O2 retained",
            "platform": platform.platform(),
            "machine": platform.machine(),
            "input": "original injected SDL shell journey in private headless Weston",
            "physical_device_latency": "not measured",
            "environment": {
                key: os.environ.get(key)
                for key in (
                    "BTRC_NATIVE_HEADER_READER",
                    "BTRC_NATIVE_SYSROOT",
                    "BTRC_NATIVE_TARGET",
                    "BTRC_WAYLAND93_GDB",
                    "SDL_VIDEODRIVER",
                    "WAYLAND_DISPLAY",
                    "VK_DRIVER_FILES",
                    "BTRC_TEST_RUNNER",
                )
            },
        }
        for name, command in (
            ("compiler", ["cc", "--version"]),
            ("gdb", [os.environ["BTRC_WAYLAND93_GDB"], "--version"]),
            ("native_packages", ["pkg-config", "--modversion", "sdl3", "libdecor-0", "wgpu-native"]),
        ):
            result = cls.command(command, output / f"{name}.txt")
            provenance[name] = {"command": command, "returncode": result.returncode}
        reader = Path(os.environ["BTRC_NATIVE_HEADER_READER"])
        provenance["reader_sha256"] = hashlib.sha256(reader.read_bytes()).hexdigest()
        (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        # Retain the full live session logs before its owner removes its temp
        # directory, including on assertion failure or debugger timeout.
        session = Path(os.environ["XDG_RUNTIME_DIR"]).parent
        try:
            collect = cls.command(
                [sys.executable, "-m", "pytest", "-q", "-n", "0", "--collect-only", NODE],
                output / "collection.txt",
            )
            assert collect.returncode == 0, collect.stderr
            nodes = [line.strip() for line in collect.stdout.splitlines() if "::test_" in line]
            assert nodes == [NODE], nodes
            arguments = [
                sys.executable,
                "-m",
                "pytest",
                "-vv",
                "-rs",
                "-n",
                "0",
                NODE,
                f"--basetemp={output / 'pytest'}",
                f"--junitxml={output / 'junit.xml'}",
                f"--skip-report={output / 'skip-report.json'}",
            ]
            (output / "pytest-command.json").write_text(json.dumps(arguments, indent=2) + "\n")
            # Stream to the job and preserve it; the workflow also tees its
            # complete container log for failures outside this Python owner.
            with (output / "pytest.log").open("w") as log:
                process = subprocess.Popen(
                    arguments, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                for line in process.stdout:
                    print(line, end="", flush=True)
                    log.write(line)
                    log.flush()
                code = process.wait()
            cases = list(ET.parse(output / "junit.xml").iter("testcase"))
            assert len(cases) == 1 and cases[0].find("skipped") is None
            assert cases[0].get("name") == "test_linux_native_shell[plain-python]"
            assert code != 0 or (cases[0].find("failure") is None and cases[0].find("error") is None)
            return code
        finally:
            for path in session.iterdir():
                if path.is_file() and path.suffix in {".log", ".out", ".ini"}:
                    (output / ("session-" + path.name)).write_bytes(path.read_bytes())


if __name__ == "__main__":
    raise SystemExit(WaylandShellDiagnostic.run())
