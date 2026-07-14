"""Validation and normalization for DAP ``launch`` arguments."""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class LaunchConfig:
    program: str
    btrcpy_command: list[str]
    compiler_cwd: str
    runtime_cwd: str
    argv: list[str]
    cc: str
    cflags: list[str]
    stop_on_entry: bool


def parse_launch_config(arguments: dict) -> LaunchConfig:
    """Return a validated config with paths resolved at request time."""
    program = _required_string(arguments, "program")
    requested_cwd = _optional_string(arguments, "cwd")
    runtime_cwd = _absolute_path(requested_cwd or os.getcwd())
    if not os.path.isabs(os.path.expanduser(program)):
        program = os.path.join(runtime_cwd, program)
    program = _absolute_path(program)
    if requested_cwd is None:
        runtime_cwd = os.path.dirname(program)

    compiler_cwd = _optional_string(arguments, "btrcpyCwd")
    compiler_cwd = _absolute_path(compiler_cwd or runtime_cwd)
    compiler = arguments.get("btrcpy")
    if compiler is None:
        compiler = [sys.executable, "-m", "src.compiler.python.main"]

    stop_on_entry = arguments.get("stopOnEntry", False)
    if not isinstance(stop_on_entry, bool):
        raise ValueError("launch: 'stopOnEntry' must be a boolean")
    return LaunchConfig(
        program=program,
        btrcpy_command=_command_argv(compiler, "btrcpy"),
        compiler_cwd=compiler_cwd,
        runtime_cwd=runtime_cwd,
        argv=_string_list(arguments.get("args", []), "args"),
        cc=_optional_string(arguments, "cc") or "cc",
        cflags=_command_argv(arguments.get("cflags", []), "cflags", allow_empty=True),
        stop_on_entry=stop_on_entry,
    )


def _required_string(arguments, name):
    value = _optional_string(arguments, name)
    if value is None:
        raise ValueError(f"launch: missing '{name}' (.btrc file)")
    return value


def _optional_string(arguments, name):
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"launch: '{name}' must be a non-empty string")
    return value


def _absolute_path(path):
    return os.path.abspath(os.path.expanduser(path))


def _command_argv(value, name, *, allow_empty=False):
    if isinstance(value, str):
        try:
            value = shlex.split(value)
        except ValueError as error:
            raise ValueError(f"launch: invalid '{name}' command: {error}") from error
    result = _string_list(value, name)
    if not result and not allow_empty:
        raise ValueError(f"launch: '{name}' command cannot be empty")
    return result


def _string_list(value, name):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"launch: '{name}' must be a list of strings")
    return list(value)
