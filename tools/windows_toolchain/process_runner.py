"""Bound compiler processes and inherited pipes; reuse the canonical Windows Job owner."""

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
    job = None
    if sys.platform == "win32":
        try:
            from tools.target_hosts.windows.executor import WindowsJob
        except ImportError as error:
            raise RuntimeError(
                "Native Windows execution requires integration of CX-P1-06/PR43 WindowsJob first"
            ) from error
        job = WindowsJob()
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="btrc-toolchain-process-") as temporary:
            status = Path(temporary) / "status"
            if job:
                request = Path(temporary) / "request.json"
                # Inherit the gate environment in memory; never serialize environment secrets.
                request.write_text(
                    json.dumps({"command": command, "cwd": str(cwd), "env": None, "status": str(status)})
                )
                launch = [
                    sys.executable,
                    "-m",
                    "tools.target_hosts.windows.executor",
                    "--gate",
                    job.name,
                    "--request",
                    str(request),
                ]
            else:
                launch = command
            process = subprocess.Popen(
                launch,
                cwd=ROOT if job else cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=job is None,
            )
            if job:
                job.assign(process)
                job.release()
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                terminate(process, job)
                stdout, stderr = process.communicate(timeout=10)
            terminate(process, job)
            if job:
                job.wait_empty()
                if not timed_out and not status.is_file():
                    raise RuntimeError("Windows launch gate exited without target status")
                code = None if timed_out else int(status.read_text())
            else:
                code = None if timed_out else process.returncode
            return Result(code, stdout, stderr, timed_out)
    finally:
        try:
            if process is not None:
                terminate(process, job)
                process.communicate(timeout=10)
            if job:
                job.wait_empty()
        finally:
            if job:
                job.close()


def terminate(process: subprocess.Popen, job) -> None:
    if job:
        job.terminate()
    else:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    # Assignment failures can leave an unreleased gate outside the Job.
    if process.poll() is None:
        process.kill()


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
        }
        code = 0
    except Exception as error:
        report, code = {"error": str(error)}, 2
    args.output.write_text(json.dumps(report) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
