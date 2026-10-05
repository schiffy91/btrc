"""Bound compiler processes and inherited pipes; Windows containment belongs to an explicitly configured ephemeral runner."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Result:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None, timeout: float) -> Result:
    if sys.platform == "win32":
        return run_windows(command, cwd=cwd, env=env, timeout=timeout)
    process = None
    try:
        process = subprocess.Popen(
            command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate(process)
            stdout, stderr = process.communicate(timeout=10)
        return Result(None if timed_out else process.returncode, stdout, stderr, timed_out)
    except OSError as error:
        return Result(127, b"", f"could not launch {command[0]}: {error}".encode(), False)
    finally:
        if process is not None:
            terminate(process)
            process.communicate(timeout=10)


def terminate(process: subprocess.Popen) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        process.kill()


def run_windows(command: list[str], *, cwd: Path, env: dict[str, str] | None, timeout: float) -> Result:
    environment = os.environ if env is None else env
    if environment.get("BTRC_WINDOWS_EXTERNAL_CONTAINMENT") != "ephemeral-runner":
        raise RuntimeError(
            "Windows commands require BTRC_WINDOWS_EXTERNAL_CONTAINMENT=ephemeral-runner: "
            "an enclosing runner deadline and guaranteed runner disposal; this helper is not Job isolation"
        )
    # File snapshots cannot hang on inherited pipes. Descendants that outlive their
    # parent are the enclosing disposable runner's responsibility, not a claimed
    # local process-tree guarantee. Temporary files may remain until runner disposal.
    with (
        tempfile.TemporaryDirectory(prefix="btrc-toolchain-", ignore_cleanup_errors=True) as temporary,
        (Path(temporary) / "stdout").open("wb") as stdout,
        (Path(temporary) / "stderr").open("wb") as stderr,
    ):
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr)
        except OSError as error:
            return Result(127, b"", f"could not launch {command[0]}: {error}".encode(), False)
        timed_out = False
        cleanup_note = b""
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                cleanup = subprocess.run(
                    ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                cleanup_note = cleanup.stdout + cleanup.stderr
            except (OSError, subprocess.TimeoutExpired) as error:
                cleanup_note = str(error).encode()
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired) as error:
                cleanup_note += b"; direct child cleanup failed: " + str(error).encode()
        # Independent handles leave any surviving writer's file position intact.
        # Fixed lengths prevent a surviving writer from extending these reads.
        with (Path(temporary) / "stdout").open("rb") as capture:
            output = capture.read(os.fstat(capture.fileno()).st_size)
        with (Path(temporary) / "stderr").open("rb") as capture:
            diagnostic = capture.read(os.fstat(capture.fileno()).st_size)
        if timed_out:
            diagnostic += b"\nBest-effort taskkill (runner disposal remains required): " + cleanup_note
        return Result(None if timed_out else process.returncode, output, diagnostic, timed_out)


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
            "containment": "external-ephemeral-runner" if sys.platform == "win32" else "process-group",
        }
        code = 0
    except Exception as error:
        report, code = {"error": str(error)}, 2
    args.output.write_text(json.dumps(report) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
