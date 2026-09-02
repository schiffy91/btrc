"""Native contract tests for std.ApplicationDirectories policy."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
C_COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
PROGRAM = """
    import std.ApplicationDirectories;

    int main() {
        ApplicationDirectoryRootsOutcome outcome = ApplicationDirectories.resolve(ApplicationDirectoryLimits(128));
        if (!outcome.ok()) {
            print(f"ERR|{(int)outcome.error().kind()}|{outcome.error().nativeCode()}|{outcome.error().message()}");
            return 0;
        }
        ApplicationDirectoryRoots roots = outcome.roots();
        print(f"OK|{roots.stateRoot()}|{roots.cacheRoot()}|{roots.configRoot()}");
        return 0;
    }
"""


@pytest.fixture(scope="module")
def generated_application_directories(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("application-directories")
    source = directory / "application-directories.btrc"
    generated = directory / "application-directories.c"
    source.write_text(textwrap.dedent(PROGRAM))
    environment = {
        **os.environ,
        "BTRC_HOME": str(ROOT / "src"),
        "BTRC_CACHE_DIR": str(directory / "cache"),
        "PYTHONPATH": str(ROOT),
    }
    transpile = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            str(source),
            "-o",
            str(generated),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert transpile.returncode == 0, transpile.stderr
    return generated


def _build(
    generated: Path,
    tmp_path: Path,
    compiler: str,
    platform: int,
) -> Path:
    executable = tmp_path / f"application-directories-{Path(compiler).name}-{platform}"
    build = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            f"-DBTRC_APPLICATION_DIRECTORIES_PLATFORM_OVERRIDE={platform}",
            f"-I{ROOT / 'src' / 'stdlib'}",
            str(generated),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert build.returncode == 0, build.stderr
    return executable


def _run(executable: Path, **environment: str) -> str:
    inherited = {name: os.environ[name] for name in ("PATH", "TMPDIR") if name in os.environ}
    run = subprocess.run(
        [str(executable)],
        env={**inherited, **environment},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr
    return run.stdout.strip()


@pytest.mark.skipif(not C_COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", C_COMPILERS, ids=lambda path: Path(path).name)
def test_application_directory_platform_policies_are_bounded_and_normalized(
    generated_application_directories: Path,
    tmp_path: Path,
    c_compiler: str,
) -> None:
    macos = _build(generated_application_directories, tmp_path, c_compiler, 1)
    assert _run(macos, HOME="/Users/example//./person/..") == (
        "OK|/Users/example/Library/Application Support|"
        "/Users/example/Library/Caches|/Users/example/Library/Application Support"
    )

    linux = _build(generated_application_directories, tmp_path, c_compiler, 2)
    assert (
        _run(
            linux,
            XDG_STATE_HOME="/srv//state/./app",
            XDG_CACHE_HOME="/srv/cache/old/../app/",
            XDG_CONFIG_HOME="/srv/config//app",
        )
        == "OK|/srv/state/app|/srv/cache/app|/srv/config/app"
    )
    assert (
        _run(
            linux,
            HOME="/home/example///workspace/..",
            XDG_STATE_HOME="relative-state",
            XDG_CACHE_HOME="relative-cache",
            XDG_CONFIG_HOME="relative-config",
        )
        == "OK|/home/example/.local/state|/home/example/.cache|/home/example/.config"
    )
    assert _run(linux, XDG_STATE_HOME="relative").startswith("ERR|1|0|")
    assert _run(linux, HOME="/" + "x" * 128).startswith("ERR|2|0|")

    unsupported = _build(generated_application_directories, tmp_path, c_compiler, 3)
    assert _run(unsupported, HOME="/ignored").startswith("ERR|3|0|")
