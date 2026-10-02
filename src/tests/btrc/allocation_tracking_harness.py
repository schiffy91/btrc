"""Build generated C with every host compiler against the allocation tracker that counts each malloc and free."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from src.tests.btrc.dual_frontend_harness import REPO
from src.tests.c_toolchains import HOST_C_COMPILERS

FIXTURES = Path(__file__).with_name("fixtures")


ALLOCATION_TRACKER = FIXTURES / "arc_boundary_alloc_tracker.c"


ALLOCATION_REDIRECTS = (
    "-Dmalloc=btrc_test_malloc",
    "-Dcalloc=btrc_test_calloc",
    "-Drealloc=btrc_test_realloc",
    "-Dfree=btrc_test_free",
)


def compiler_environment(compiler: str) -> dict[str, str] | None:
    if sys.platform != "darwin" or os.path.realpath(compiler) != "/usr/bin/clang":
        return None
    environment = {
        name: os.environ[name]
        for name in ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE")
        if name in os.environ
    }
    environment.update({"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": "/tmp"})
    return environment


def tracked_strict_matrix(
    compiled: tuple[str, Path],
    tmp_path: Path,
    *,
    expected_stdout: str | None = None,
    extra_compile_args: tuple[str, ...] = (),
    extra_sources: tuple[Path, ...] = (),
) -> None:
    for compiler in HOST_C_COMPILERS:
        output = tmp_path / f"{compiled[0]}-{Path(compiler).name}-tracked"
        environment = compiler_environment(compiler)
        build = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O2",
                *ALLOCATION_REDIRECTS,
                *extra_compile_args,
                str(compiled[1]),
                str(ALLOCATION_TRACKER),
                *(str(source) for source in extra_sources),
                "-pthread",
                "-lm",
                "-o",
                str(output),
            ],
            cwd=REPO,
            env=environment,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert build.returncode == 0, build.stderr
        run = subprocess.run(
            [str(output)],
            cwd=REPO,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stderr
        if expected_stdout is not None:
            assert run.stdout == expected_stdout
