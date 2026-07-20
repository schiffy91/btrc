"""Shared strict/sanitizer harness for ownership runtime contracts."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import CC, REPO

SANITIZER_FLAGS = (
    "-fsanitize=address,undefined",
    "-fno-omit-frame-pointer",
)


@dataclass(frozen=True)
class SanitizerToolchain:
    """Compiler command and the environment needed by its runtime."""

    command: tuple[str, ...]
    environment: dict[str, str] | None = None


def _host_clang_environment() -> dict[str, str]:
    """Keep Apple clang isolated from an enclosing Nix build shell."""
    environment = {
        name: os.environ[name]
        for name in (
            "HOME",
            "USER",
            "LOGNAME",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
        )
        if name in os.environ
    }
    environment.update(
        {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "TMPDIR": "/tmp",
        }
    )
    return environment


def _sanitizer_candidates() -> tuple[SanitizerToolchain, ...]:
    """Return override, host, and discovered fallback candidates in order."""
    candidates: list[SanitizerToolchain] = []
    configured = tuple(CC)
    explicit_override = bool(os.environ.get("BTRC_CC"))
    if explicit_override and configured:
        candidates.append(SanitizerToolchain(configured))
    if sys.platform == "darwin" and os.access("/usr/bin/clang", os.X_OK):
        candidates.append(
            SanitizerToolchain(
                ("/usr/bin/clang",),
                _host_clang_environment(),
            )
        )
    if not explicit_override and configured:
        candidates.append(SanitizerToolchain(configured))
    for name in ("clang", "gcc"):
        if path := shutil.which(name):
            candidates.append(SanitizerToolchain((path,)))

    unique: list[SanitizerToolchain] = []
    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        executable = shutil.which(
            candidate.command[0],
            path=(candidate.environment or os.environ).get("PATH"),
        )
        identity = (
            os.path.realpath(executable or candidate.command[0]),
            *candidate.command[1:],
        )
        if identity not in seen:
            seen.add(identity)
            unique.append(candidate)
    return tuple(unique)


def _probe_sanitizer_candidate(
    candidate: SanitizerToolchain,
    tmp_path: Path,
    index: int,
) -> str | None:
    """Return a failure description, or ``None`` after a clean runtime probe."""
    source = tmp_path / f"sanitizer-probe-{index}.c"
    executable = tmp_path / f"sanitizer-probe-{index}"
    source.write_text("int main(void) { return 0; }\n")
    label = " ".join(candidate.command)
    try:
        build = subprocess.run(
            [
                *candidate.command,
                "-std=c11",
                *SANITIZER_FLAGS,
                str(source),
                "-o",
                str(executable),
            ],
            cwd=REPO,
            env=candidate.environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return f"{label}: compile probe failed ({error})"
    if build.returncode != 0:
        return f"{label}: compile probe exited {build.returncode}: {build.stderr[:160]}"
    try:
        run = subprocess.run(
            [str(executable)],
            cwd=REPO,
            env=sanitizer_environment(candidate),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return f"{label}: sanitizer runtime probe timed out"
    if run.returncode != 0:
        return f"{label}: sanitizer runtime probe exited {run.returncode}: {run.stderr[:160]}"
    return None


def _select_sanitizer_toolchain(tmp_path: Path) -> SanitizerToolchain:
    failures = []
    for index, candidate in enumerate(_sanitizer_candidates()):
        failure = _probe_sanitizer_candidate(candidate, tmp_path, index)
        if failure is None:
            return candidate
        failures.append(failure)
    reason = "; ".join(failures) if failures else "no C compiler candidates"
    pytest.skip(f"C sanitizers unavailable: {reason}")


def compile_reference_source(tmp_path: Path, source: str, stem: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    program = tmp_path / f"reference-{stem}.btrc"
    generated = tmp_path / f"reference-{stem}.c"
    program.write_text(source)
    result = subprocess.run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(program),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(generated),
        ],
        cwd=REPO,
        env={
            **os.environ,
            "BTRC_CACHE_DIR": str(tmp_path / f"cache-{stem}"),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result, generated


def sanitizer_environment(
    toolchain: SanitizerToolchain | None = None,
) -> dict[str, str]:
    environment = dict(os.environ if toolchain is None or toolchain.environment is None else toolchain.environment)
    environment.update(
        {
            "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=1",
            "UBSAN_OPTIONS": "halt_on_error=1",
        }
    )
    return environment


def require_sanitizers(tmp_path: Path) -> SanitizerToolchain:
    return _select_sanitizer_toolchain(tmp_path)


def sanitized_build_and_run(
    generated: Path,
    executable: Path,
    toolchain: SanitizerToolchain | None = None,
) -> None:
    selected = toolchain or _select_sanitizer_toolchain(executable.parent)
    build = subprocess.run(
        [
            *selected.command,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O1",
            "-g",
            *SANITIZER_FLAGS,
            str(generated),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        cwd=REPO,
        env=selected.environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run(
        [str(executable)],
        cwd=REPO,
        env=sanitizer_environment(selected),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr


__all__ = [
    "SanitizerToolchain",
    "compile_reference_source",
    "require_sanitizers",
    "sanitized_build_and_run",
    "sanitizer_environment",
]
