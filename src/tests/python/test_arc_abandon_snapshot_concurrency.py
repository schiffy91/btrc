"""Lock-order and queued-forest regressions for constructor abandon."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.ir.gen.helpers import helper_decls_for_roots

ROOTS = {
    "__btrc_safe_calloc",
    "__btrc_arc_abandon",
    "__btrc_arc_release",
    "__btrc_arc_replace_edge",
    "__btrc_arc_retain",
    "__btrc_arc_topology_begin",
    "__btrc_arc_topology_complete",
    "__btrc_mutex_val_create",
    "__btrc_mutex_arc_retain",
    "__btrc_mutex_arc_release",
    "__btrc_mutex_arc_finalize",
    "__btrc_cycle_state_cleanup",
}
RUNTIME = "\n\n".join(helper.c_source for helper in helper_decls_for_roots(ROOTS))
FIXTURE = Path(__file__).with_name("fixtures") / "arc_abandon_snapshot_concurrency.c"
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
    c_compiler: str,
    *,
    extra_flags: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    fixture = FIXTURE.read_text()
    assert fixture.count(MARKER) == 1
    source = tmp_path / "arc-abandon-snapshot.c"
    executable = tmp_path / f"arc-abandon-{Path(c_compiler).name}"
    source.write_text(fixture.replace(MARKER, RUNTIME))
    environment = _compiler_environment(c_compiler)
    build = subprocess.run(
        [
            c_compiler,
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
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        env=environment,
    )
    assert build.returncode == 0, build.stderr
    run_environment = dict(os.environ if environment is None else environment)
    run_environment["TSAN_OPTIONS"] = "halt_on_error=1"
    return subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=20,
        env=run_environment,
    )


@pytest.mark.skipif(not COMPILERS, reason="requires a pthread C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_abandon_snapshots_are_lock_order_safe_and_strict_c11(
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


def test_abandon_snapshots_are_thread_sanitizer_clean(tmp_path: Path) -> None:
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
