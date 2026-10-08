"""Capture toolchain evidence using the shared build and Windows Job owners."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from tools.target_hosts.windows.bundle import run_build_command
from tools.target_hosts.windows.executor import WindowsJob

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Result:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    error: str | None = None


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None, timeout: float) -> Result:
    if not command or not 0 < timeout < float("inf"):
        raise ValueError("a command and finite positive timeout are required")
    if sys.platform == "win32":
        return run_windows(command, cwd=cwd, env=env, timeout=timeout)
    with tempfile.TemporaryDirectory(prefix="btrc-toolchain-") as temporary:
        output, diagnostic = Path(temporary) / "stdout", Path(temporary) / "stderr"
        code, timed_out, launch_error = 0, False, b""
        with output.open("wb") as stdout, diagnostic.open("wb") as stderr:
            try:
                run_build_command(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr, timeout_s=timeout)
            except subprocess.TimeoutExpired:
                code, timed_out = None, True
            except subprocess.CalledProcessError as error:
                code = error.returncode
            except OSError as error:
                code, launch_error = 127, f"could not launch {command[0]}: {error}".encode()
        return Result(code, output.read_bytes(), diagnostic.read_bytes() + launch_error, timed_out)


def run_windows(command: list[str], *, cwd: Path, env: dict[str, str] | None, timeout: float) -> Result:
    if not command or not 0 < timeout < float("inf"):
        raise ValueError("a command and finite positive timeout are required")
    directory = Path(tempfile.mkdtemp(prefix="btrc-toolchain-"))
    try:
        result = _run_windows_captured(command, cwd=cwd, env=env, timeout=timeout, directory=directory)
    except BaseException as error:
        try:
            _remove_capture(directory)
        except OSError as cleanup_error:
            error.add_note(f"Capture cleanup failed; retained at {directory}: {cleanup_error}")
        raise
    try:
        _remove_capture(directory)
    except OSError as error:
        message = f"Capture cleanup failed; retained at {directory}: {error}"
        result.error = f"{result.error}\n{message}" if result.error else message
        result.stderr += message.encode()
    return result


def _remove_capture(directory: Path) -> None:
    # An empty Job does not prove every capture-file handle is closed. Retry
    # only Windows sharing violations, under a separate cleanup deadline; a
    # persistent lock remains a failure and retains the command's evidence.
    deadline = time.monotonic() + 5
    while True:
        try:
            shutil.rmtree(directory)
            return
        except OSError as error:
            if getattr(error, "winerror", None) != 32 or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _run_windows_captured(
    command: list[str], *, cwd: Path, env: dict[str, str] | None, timeout: float, directory: Path
) -> Result:
    # The assigned launch gate cannot create a target before Job membership.
    deadline = time.monotonic() + timeout
    output, diagnostic = directory / "stdout", directory / "stderr"
    status, launch_error = directory / "status", directory / "launch-error.json"
    request = directory / "request.json"
    request.write_text(
        json.dumps(
            {
                "command": command,
                "cwd": str(cwd),
                "env": {},
                "status": str(status),
                "launch_error": str(launch_error),
            }
        ),
        encoding="utf-8",
    )
    job, process, timed_out = WindowsJob(), None, False
    primary = None
    try:
        with output.open("wb") as stdout, diagnostic.open("wb") as stderr:
            process = subprocess.Popen(
                [
                    getattr(sys, "_base_executable", sys.executable),
                    str(ROOT / "tools/target_hosts/windows/executor.py"),
                    "--gate",
                    job.name,
                    "--request",
                    str(request),
                ],
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=0x00000008 | 0x00000200,
            )
            job.assign(process)
            job.release()
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                else:
                    process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                timed_out = True
    except BaseException as error:
        primary = error
    finally:

        def reap_gate():
            if process is not None:
                if process.poll() is None:
                    process.kill()  # Includes a gate whose assignment failed.
                process.wait(timeout=10)

        # Attempt every cleanup even when termination fails. In particular,
        # an unassigned gate still needs explicit kill/reap; closing the Job
        # cannot own it. Also reap descendants after ordinary parent exit.
        for cleanup in (job.terminate, reap_gate, job.wait_empty, job.close):
            try:
                cleanup()
            except BaseException as cleanup_error:
                if primary is None:
                    primary = cleanup_error
                else:
                    primary.add_note(f"Windows Job cleanup failed: {cleanup_error}")
    stdout = output.read_bytes() if output.exists() else b""
    stderr = diagnostic.read_bytes() if diagnostic.exists() else b""
    if primary is not None:
        if not isinstance(primary, Exception):
            raise primary
        message = "\n".join([str(primary), *getattr(primary, "__notes__", [])])
        return Result(None, stdout, stderr + message.encode(), timed_out, message)
    if timed_out:
        return Result(None, stdout, stderr, True)
    if launch_error.exists():
        failure = json.loads(launch_error.read_text(encoding="utf-8"))
        message = f"could not launch {command[0]}: {json.dumps(failure)}"
        return Result(127, stdout, stderr + message.encode(), False)
    if not status.exists():
        return Result(None, stdout, stderr, False, "Windows launch gate exited without target status")
    return Result(int(status.read_text(encoding="ascii")), stdout, stderr, False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", required=True, type=float)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command.pop(0)
    if not args.command or not 0 < args.timeout < float("inf"):
        parser.error("a command and finite positive timeout are required")
    try:
        result = run(args.command, cwd=ROOT, env=None, timeout=args.timeout)
        report = {
            "returncode": result.returncode,
            "stdout": result.stdout.decode("utf-8", errors="replace"),
            "stderr": result.stderr.decode("utf-8", errors="replace"),
            "timed_out": result.timed_out,
            "error": result.error,
            "containment": "windows-job" if sys.platform == "win32" else "process-group",
        }
        code = 0
    except Exception as error:
        report, code = {"error": str(error)}, 2
    args.output.write_text(json.dumps(report) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
