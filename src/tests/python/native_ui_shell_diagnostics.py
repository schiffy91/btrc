"""Opt-in process evidence for the hosted native-shell diagnostic only."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path


class MacOSShellDiagnostic:
    """Retain child output while running, without extending its original deadline."""

    SAMPLE_AT = (30, 180, 600)

    @staticmethod
    def directory(environment=None):
        environment = os.environ if environment is None else environment
        destination = environment.get("BTRC_UI_SHELL_DIAGNOSTICS")
        if not destination:
            return None
        if sys.platform != "darwin" or environment.get("CI") != "true":
            raise RuntimeError("Native shell diagnostics require an explicit hosted macOS run")
        path = Path(destination).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def debug_flags(cls, environment):
        return ["-g"] if cls.directory(environment) is not None else []

    @staticmethod
    def record(path, **record):
        record.update(utc=datetime.now(UTC).isoformat(), monotonic_ns=time.monotonic_ns())
        path.write_text(json.dumps(record, indent=2) + "\n")

    @classmethod
    def sample(cls, process, destination, elapsed, remaining, environment):
        # The caller owns this unreaped child. No process-name search, external
        # process sampling, sudo, or permission request is involved.
        prefix = destination / f"sample-{elapsed}"
        command = ["/usr/bin/sample", str(process.pid), "3", "1", "-file", str(prefix.with_suffix(".txt"))]
        began = time.monotonic_ns()
        try:
            result = subprocess.run(command, env=environment, capture_output=True, timeout=min(15, remaining))
            stdout, stderr, code, timed_out = result.stdout, result.stderr, result.returncode, False
        except subprocess.TimeoutExpired as error:
            stdout, stderr, code, timed_out = error.stdout or b"", error.stderr or b"", None, True
        except OSError as error:
            stdout, stderr, code, timed_out = b"", str(error).encode(), None, False
        prefix.with_suffix(".stdout").write_bytes(stdout)
        prefix.with_suffix(".stderr").write_bytes(stderr)
        cls.record(
            prefix.with_suffix(".json"),
            argv=command,
            pid=process.pid,
            started_ns=began,
            returncode=code,
            timed_out=timed_out,
        )

    @staticmethod
    def echo(destination, offsets):
        for name, stream in (("stdout", sys.stdout), ("stderr", sys.stderr)):
            with (destination / name).open("rb") as source:
                source.seek(offsets[name])
                data = source.read()
                offsets[name] += len(data)
            if data:
                stream.write(data.decode(errors="replace"))
                stream.flush()

    @classmethod
    def run(cls, command, *, env=None, **kwargs):
        directory = cls.directory(env)
        if directory is None:
            return subprocess.run(command, env=env, **kwargs)
        options = dict(kwargs)
        if options.pop("capture_output", False) is not True or options.pop("text", False) is not True:
            raise ValueError("Diagnostic shell calls must request captured text output")
        timeout = options.pop("timeout", None)
        check = options.pop("check", False)
        destination = directory / (Path(command[0]).name + "-" + uuid.uuid4().hex)
        destination.mkdir()
        command = list(map(str, command))
        cls.record(
            destination / "command.json", argv=command, cwd=str(options.get("cwd", Path.cwd())), timeout_seconds=timeout
        )
        began = time.monotonic()
        deadline = began + timeout if timeout is not None else None
        timed_out = False
        sample_index = 0
        offsets = {"stdout": 0, "stderr": 0}
        # Direct files retain all output even if the CI runner kills pytest.
        # The child's original libc buffering is unchanged.
        with (
            (destination / "stdout").open("wb", buffering=0) as stdout_file,
            (destination / "stderr").open("wb", buffering=0) as stderr_file,
            subprocess.Popen(command, env=env, stdout=stdout_file, stderr=stderr_file, **options) as process,
        ):
            cls.record(destination / "started.json", argv=command, pid=process.pid, timeout_seconds=timeout)
            print(f"SHELL DIAGNOSTIC pid={process.pid} argv={command!r} evidence={destination}", flush=True)
            try:
                while process.poll() is None:
                    cls.echo(destination, offsets)
                    now = time.monotonic()
                    remaining = deadline - now if deadline is not None else float("inf")
                    if remaining <= 0:
                        timed_out = True
                        process.kill()
                        break
                    if (
                        Path(command[0]).name == "AppKitControl"
                        and sample_index < len(cls.SAMPLE_AT)
                        and now - began >= cls.SAMPLE_AT[sample_index]
                    ):
                        cls.sample(process, destination, cls.SAMPLE_AT[sample_index], remaining, env)
                        sample_index += 1
                        continue
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=min(1, remaining))
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                cls.echo(destination, offsets)
                cls.record(
                    destination / "finished.json",
                    argv=command,
                    pid=process.pid,
                    returncode=process.returncode,
                    timed_out=timed_out,
                    elapsed_seconds=time.monotonic() - began,
                )
        stdout = (destination / "stdout").read_bytes()
        stderr = (destination / "stderr").read_bytes()
        if timed_out:
            raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
        result = subprocess.CompletedProcess(
            command,
            process.returncode,
            io.TextIOWrapper(io.BytesIO(stdout)).read(),
            io.TextIOWrapper(io.BytesIO(stderr)).read(),
        )
        if check:
            result.check_returncode()
        return result

    @classmethod
    def symbols(cls, executable, environment, destination=None):
        if cls.directory(environment) is None:
            return
        result = cls.run(
            ["/usr/bin/dsymutil", str(executable), "-o", str(destination or (str(executable) + ".dSYM"))],
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
