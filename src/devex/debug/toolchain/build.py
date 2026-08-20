"""Debug launch configuration and native executable build ownership.

``ProgramBuilder`` owns one configured btrc-to-native toolchain. It transpiles
with ``--debug`` so generated C carries source locations, then compiles with
debug information so LLDB can resolve btrc breakpoints and stack frames.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LaunchConfig:
    """Validated, normalized state for one DAP ``launch`` request."""

    program: str
    btrcpy_command: tuple[str, ...]
    compiler_cwd: str
    runtime_cwd: str
    argv: tuple[str, ...]
    cc: str
    cflags: tuple[str, ...]
    stop_on_entry: bool

    @classmethod
    def from_arguments(
        cls,
        arguments: dict,
        *,
        current_directory=None,
        python_executable=None,
    ) -> LaunchConfig:
        """Validate and normalize request arguments at launch time."""
        if not isinstance(arguments, dict):
            raise ValueError("launch: 'arguments' must be an object")

        program = cls._required_string(arguments, "program")
        requested_cwd = cls._optional_string(arguments, "cwd")
        if current_directory is None:
            current_directory = os.getcwd()
        runtime_cwd = cls._absolute_path(requested_cwd or current_directory)
        if not os.path.isabs(os.path.expanduser(program)):
            program = os.path.join(runtime_cwd, program)
        program = cls._absolute_path(program)
        if requested_cwd is None:
            runtime_cwd = os.path.dirname(program)

        compiler_cwd = cls._optional_string(arguments, "btrcpyCwd")
        compiler_cwd = cls._absolute_path(compiler_cwd or runtime_cwd)
        compiler = arguments.get("btrcpy")
        if compiler is None:
            compiler = [python_executable or sys.executable, "-m", "src.compiler.python.main"]

        stop_on_entry = arguments.get("stopOnEntry", False)
        if not isinstance(stop_on_entry, bool):
            raise ValueError("launch: 'stopOnEntry' must be a boolean")

        return cls(
            program=program,
            btrcpy_command=cls._command_argv(compiler, "btrcpy"),
            compiler_cwd=compiler_cwd,
            runtime_cwd=runtime_cwd,
            argv=cls._string_tuple(arguments.get("args", []), "args"),
            cc=cls._optional_string(arguments, "cc") or "cc",
            cflags=cls._command_argv(arguments.get("cflags", []), "cflags", allow_empty=True),
            stop_on_entry=stop_on_entry,
        )

    @classmethod
    def _required_string(cls, arguments, name) -> str:
        value = cls._optional_string(arguments, name)
        if value is None:
            raise ValueError(f"launch: missing '{name}' (.btrc file)")
        return value

    @staticmethod
    def _optional_string(arguments, name):
        value = arguments.get(name)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"launch: '{name}' must be a non-empty string")
        return value

    @staticmethod
    def _absolute_path(path) -> str:
        return os.path.abspath(os.path.expanduser(path))

    @classmethod
    def _command_argv(cls, value, name, *, allow_empty=False) -> tuple[str, ...]:
        if isinstance(value, str):
            try:
                value = shlex.split(value)
            except ValueError as error:
                raise ValueError(f"launch: invalid '{name}' command: {error}") from error
        result = cls._string_tuple(value, name)
        if not result and not allow_empty:
            raise ValueError(f"launch: '{name}' command cannot be empty")
        if any(not item for item in result):
            raise ValueError(f"launch: '{name}' command must contain only non-empty strings")
        return result

    @staticmethod
    def _string_tuple(value, name) -> tuple[str, ...]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"launch: '{name}' must be a list of strings")
        return tuple(value)


class BuildError(RuntimeError):
    pass


@dataclass
class BuildArtifact:
    """One debug executable and the directory that owns its generated files."""

    executable: str
    directory: str
    _temporary_directory: tempfile.TemporaryDirectory | None = field(default=None, repr=False)

    def cleanup(self) -> None:
        """Remove owned temporary files; caller-provided output dirs are kept."""
        if self._temporary_directory is None:
            return
        self._temporary_directory.cleanup()
        self._temporary_directory = None


class ProgramBuilder:
    """Own the toolchain and process lifecycle for debug builds."""

    DEFAULT_BUILD_TIMEOUT_SECONDS = 300
    DEFAULT_TERMINATION_TIMEOUT_SECONDS = 2

    def __init__(
        self,
        btrcpy_command,
        *,
        c_compiler="cc",
        c_flags=(),
        output_directory=None,
        cwd=None,
        build_timeout_seconds=DEFAULT_BUILD_TIMEOUT_SECONDS,
        termination_timeout_seconds=DEFAULT_TERMINATION_TIMEOUT_SECONDS,
        process_factory=subprocess.Popen,
        command_runner=subprocess.run,
        temporary_directory_factory=tempfile.TemporaryDirectory,
        process_group_killer=None,
        platform_name=os.name,
    ):
        self.btrcpy_command = self._command_tuple(btrcpy_command, "btrcpy_command")
        self.c_compiler = self._required_string(c_compiler, "c_compiler")
        self.c_flags = self._command_tuple(c_flags, "c_flags", allow_empty=True)
        self.output_directory = self._absolute_path(output_directory) if output_directory is not None else None
        self.cwd = self._absolute_path(cwd) if cwd is not None else None
        self.build_timeout_seconds = self._positive_timeout(build_timeout_seconds, "build_timeout_seconds")
        self.termination_timeout_seconds = self._positive_timeout(
            termination_timeout_seconds,
            "termination_timeout_seconds",
        )
        self._process_factory = process_factory
        self._command_runner = command_runner
        self._temporary_directory_factory = temporary_directory_factory
        self._process_group_killer = (
            getattr(os, "killpg", None) if process_group_killer is None else process_group_killer
        )
        self._platform_name = platform_name

    def build(self, program) -> BuildArtifact:
        """Build *program* and return the artifact that owns generated files."""
        program = self._absolute_path(program)
        if not os.path.isfile(program):
            raise BuildError(f"program not found: {program}")

        temporary_directory = None
        artifact = None
        try:
            output_directory = self.output_directory
            if output_directory is None:
                temporary_directory = self._temporary_directory_factory(prefix="btrc-debug-")
                output_directory = temporary_directory.name
            os.makedirs(output_directory, exist_ok=True)

            stem = os.path.splitext(os.path.basename(program))[0]
            c_path = os.path.join(output_directory, stem + ".c")
            executable_path = os.path.join(output_directory, stem)
            artifact = BuildArtifact(executable_path, output_directory, temporary_directory)

            self._run(
                [*self.btrcpy_command, program, "--debug", "--no-cache", "-o", c_path],
                "transpile",
            )
            self._run(
                [
                    self.c_compiler,
                    "-g",
                    "-O0",
                    "-std=c11",
                    c_path,
                    "-o",
                    executable_path,
                    "-lm",
                    "-lpthread",
                    *self.c_flags,
                ],
                "C compile",
            )
            return artifact
        except Exception:
            if artifact is not None:
                artifact.cleanup()
            elif temporary_directory is not None:
                temporary_directory.cleanup()
            raise

    def _run(self, command, phase) -> None:
        process = None
        try:
            process = self._process_factory(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                cwd=self.cwd,
                **self._process_group_options(),
            )
            stdout, stderr = process.communicate(timeout=self.build_timeout_seconds)
        except subprocess.TimeoutExpired as error:
            if process is not None:
                self._terminate_process_group(process)
                self._reap_process(process)
            raise BuildError(f"{phase} timed out after {self.build_timeout_seconds} seconds") from error
        except OSError as error:
            if process is not None:
                self._terminate_process_group(process)
                self._reap_process(process)
            raise BuildError(f"{phase} failed: {error}") from error
        if process.returncode != 0:
            output = (stderr or "") + (stdout or "")
            raise BuildError(f"{phase} failed:\n{output.strip()}")

    def _process_group_options(self) -> dict:
        if self._platform_name == "nt":
            return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
        return {"start_new_session": True}

    def _terminate_process_group(self, process) -> None:
        if self._platform_name == "nt":
            with suppress(OSError, subprocess.SubprocessError):
                self._command_runner(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=self.termination_timeout_seconds,
                )
        else:
            if self._process_group_killer is not None:
                with suppress(OSError):
                    self._process_group_killer(process.pid, signal.SIGKILL)
        if process.poll() is None:
            with suppress(OSError):
                process.kill()

    def _reap_process(self, process) -> None:
        try:
            process.communicate(timeout=self.termination_timeout_seconds)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                with suppress(OSError):
                    stream.close()
        with suppress(OSError, subprocess.TimeoutExpired):
            process.wait(timeout=self.termination_timeout_seconds)

    @staticmethod
    def _absolute_path(path) -> str:
        return os.path.abspath(os.path.expanduser(os.fspath(path)))

    @staticmethod
    def _required_string(value, name) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        return value

    @classmethod
    def _command_tuple(cls, value, name, *, allow_empty=False) -> tuple[str, ...]:
        if isinstance(value, str) or not isinstance(value, (list, tuple)):
            raise ValueError(f"{name} must be a sequence of strings")
        if any(not isinstance(item, str) or not item for item in value):
            raise ValueError(f"{name} must contain only non-empty strings")
        result = tuple(value)
        if not result and not allow_empty:
            raise ValueError(f"{name} cannot be empty")
        return result

    @staticmethod
    def _positive_timeout(value, name):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{name} must be a positive number")
        return value
