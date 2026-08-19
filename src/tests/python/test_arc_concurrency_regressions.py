"""Adversarial concurrent contracts for terminal ARC state transitions."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

ROOTS = {
    "__btrc_safe_calloc",
    "__btrc_arc_retain",
    "__btrc_arc_release",
    "__btrc_arc_replace_edge",
    "__btrc_arc_destroy_slot",
    "__btrc_arc_destroy_edge",
    "__btrc_arc_topology_begin",
    "__btrc_arc_topology_complete",
    "__btrc_destroyed_tracking_scope",
    "__btrc_mark_destroyed",
    "__btrc_is_destroyed",
    "__btrc_collect_cycles",
    "__btrc_flush_cycles",
    "__btrc_arc_thread_state_cleanup",
    "__btrc_cycle_state_cleanup",
}
RUNTIME = "\n\n".join(helper.c_source for helper in RuntimeHelperCatalog().definitions_for(ROOTS))
FIXTURE = Path(__file__).with_name("fixtures") / "arc_concurrency_regressions.c"
MARKER = "/* BTRC_RUNTIME_HELPERS */"
COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _compiler_environment(compiler: str) -> dict[str, str] | None:
    if sys.platform != "darwin" or os.path.realpath(compiler) != "/usr/bin/clang":
        return None
    environment = {
        name: os.environ[name]
        for name in ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE")
        if name in os.environ
    }
    environment.update({"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": "/tmp"})
    return environment


def _build_and_run(
    tmp_path: Path,
    compiler: str,
    *,
    extra_flags: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "arc_concurrency_regressions.c"
    output = tmp_path / f"arc-concurrency-{Path(compiler).name}"
    fixture = FIXTURE.read_text()
    assert fixture.count(MARKER) == 1
    source.write_text(fixture.replace(MARKER, RUNTIME))
    environment = _compiler_environment(compiler)
    build = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O1" if extra_flags else "-O2",
            *extra_flags,
            str(source),
            "-pthread",
            "-o",
            str(output),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert build.returncode == 0, build.stderr
    run_environment = dict(os.environ if environment is None else environment)
    run_environment["TSAN_OPTIONS"] = "halt_on_error=1"
    return subprocess.run(
        [str(output)],
        env=run_environment,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.skipif(not COMPILERS, reason="requires a pthread C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda value: Path(value).name)
def test_arc_concurrency_regressions_are_strict_c11_clean(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    run = _build_and_run(tmp_path, c_compiler)
    assert run.returncode == 0, run.stderr


def _tsan_unavailable(detail: str) -> bool:
    unavailable = (
        "cannot find -ltsan",
        "unsupported option '-fsanitize=thread'",
        "unexpected memory mapping",
        "failed to mmap",
        "Library not loaded: @rpath/libclang_rt.tsan",
        "undefined symbol: _dispatch_",
    )
    return any(message in detail for message in unavailable)


def test_arc_concurrency_regressions_are_thread_sanitizer_clean(
    tmp_path: Path,
) -> None:
    compiler = (
        "/usr/bin/clang" if sys.platform == "darwin" and os.access("/usr/bin/clang", os.X_OK) else shutil.which("clang")
    )
    if compiler is None:
        pytest.skip("ThreadSanitizer requires clang")
    try:
        run = _build_and_run(
            tmp_path,
            compiler,
            extra_flags=(
                "-g",
                "-fsanitize=thread",
                "-fno-omit-frame-pointer",
            ),
        )
    except AssertionError as error:
        if _tsan_unavailable(str(error)):
            pytest.skip(f"ThreadSanitizer unavailable: {error}")
        raise
    if run.returncode != 0 and _tsan_unavailable(run.stderr):
        pytest.skip(f"ThreadSanitizer runtime unavailable: {run.stderr[:200]}")
    assert run.returncode == 0, run.stderr
