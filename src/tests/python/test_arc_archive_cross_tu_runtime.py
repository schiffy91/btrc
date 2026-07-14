"""Cross-archive contracts for one process-wide ARC lifecycle FIFO."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python import stdlib_archive as archive
from src.compiler.python.cli_archive import build_stdlib_archive

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
AR = shutil.which("ar")
FIXTURES = Path(__file__).with_name("fixtures")
ARCHIVE_TU = FIXTURES / "arc_archive_cross_tu_archive.c"
PROGRAM_TU = FIXTURES / "arc_archive_cross_tu_program.c"
THREAD_ARCHIVE_TU = FIXTURES / "thread_archive_cross_tu_archive.c"
THREAD_PROGRAM_TU = FIXTURES / "thread_archive_cross_tu_program.c"
TLS_SYMBOLS = (
    "__btrc_arc_deferred_head",
    "__btrc_arc_deferred_tail",
    "__btrc_arc_draining",
    "__btrc_arc_topology_depth",
    "__btrc_abandon_queue",
    "__btrc_abandon_count",
    "__btrc_abandon_cap",
    "__btrc_abandon_drain_callback",
    "__btrc_tracking",
    "__btrc_destroyed",
    "__btrc_destroyed_count",
    "__btrc_destroyed_cap",
)
PROCESS_SYMBOLS = (
    "__btrc_arc_lock_flag",
    "__btrc_arc_snapshotting",
    "__btrc_arc_snapshot_pending",
    "__btrc_arc_topology_active",
    "__btrc_suspects",
    "__btrc_cycle_scratch",
    "__btrc_arc_shutdown",
)

pytestmark = pytest.mark.skipif(
    not COMPILERS or AR is None or sys.platform == "win32",
    reason="requires hosted strict C11 compilers and an archiver",
)


@pytest.fixture(scope="module")
def stdlib_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("arc-cross-tu-stdlib")
    build_stdlib_archive(str(output))
    return output


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


def _run(command: list[str], compiler: str, timeout: int = 240) -> None:
    result = subprocess.run(
        command,
        env=_compiler_environment(compiler),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stderr


def _compile_object(
    compiler: str,
    include_dir: Path,
    source: Path,
    output: Path,
) -> None:
    _run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wno-unused-function",
            "-O2",
            f"-I{include_dir}",
            "-c",
            str(source),
            "-o",
            str(output),
        ],
        compiler,
    )


def test_arc_mutable_state_is_extern_once(
    stdlib_output: Path,
) -> None:
    header = (stdlib_output / archive.HEADER_NAME).read_text()
    implementation = (stdlib_output / archive.IMPL_NAME).read_text()
    for symbol in (*TLS_SYMBOLS, *PROCESS_SYMBOLS):
        assert re.search(rf"(?m)^extern [^;]*\b{symbol}\b[^;]*;", header)
        assert not re.search(
            rf"(?m)^static (?!inline)[^();{{}}]*\b{symbol}\b[^;]*;",
            header,
        )
        definitions = re.findall(
            rf"(?m)^(?!extern\b)(?!static\b)\S[^\n();{{}};]*"
            rf"(?:\n[ \t]+[^\n();{{}};]*)?\b{symbol}\b"
            rf"[^\n();{{}};]*;$",
            implementation,
        )
        assert len(definitions) == 1, (symbol, definitions)


@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_cross_tu_hooks_share_fifo_and_first_error(
    stdlib_output: Path,
    tmp_path: Path,
    c_compiler: str,
) -> None:
    stdlib_object = tmp_path / "btrc_stdlib.o"
    archive_object = tmp_path / "archive_hook.o"
    program_object = tmp_path / "program_hook.o"
    _compile_object(
        c_compiler,
        stdlib_output,
        stdlib_output / archive.IMPL_NAME,
        stdlib_object,
    )
    _compile_object(c_compiler, stdlib_output, ARCHIVE_TU, archive_object)
    _compile_object(c_compiler, stdlib_output, PROGRAM_TU, program_object)

    library = tmp_path / "libbtrc_cross_tu.a"
    _run(
        [AR, "rcs", str(library), str(stdlib_object), str(archive_object)],
        c_compiler,
    )
    binary = tmp_path / "arc_archive_cross_tu"
    _run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(program_object),
            str(library),
            "-lm",
            "-pthread",
            "-o",
            str(binary),
        ],
        c_compiler,
    )
    executed = subprocess.run(
        [str(binary)],
        env=_compiler_environment(c_compiler),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert executed.returncode == 0, (
        executed.returncode,
        executed.stdout,
        executed.stderr,
    )


@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_cross_tu_worker_errors_finalize_and_transfer(
    stdlib_output: Path,
    tmp_path: Path,
    c_compiler: str,
) -> None:
    stdlib_object = tmp_path / "btrc_stdlib_thread.o"
    archive_object = tmp_path / "archive_thread.o"
    program_object = tmp_path / "program_thread.o"
    _compile_object(
        c_compiler,
        stdlib_output,
        stdlib_output / archive.IMPL_NAME,
        stdlib_object,
    )
    _compile_object(
        c_compiler,
        stdlib_output,
        THREAD_ARCHIVE_TU,
        archive_object,
    )
    _compile_object(
        c_compiler,
        stdlib_output,
        THREAD_PROGRAM_TU,
        program_object,
    )
    library = tmp_path / "libbtrc_thread_cross_tu.a"
    _run(
        [AR, "rcs", str(library), str(stdlib_object), str(archive_object)],
        c_compiler,
    )
    binary = tmp_path / "thread_archive_cross_tu"
    _run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(program_object),
            str(library),
            "-lm",
            "-pthread",
            "-o",
            str(binary),
        ],
        c_compiler,
    )
    executed = subprocess.run(
        [str(binary)],
        env=_compiler_environment(c_compiler),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert executed.returncode == 0, (
        executed.returncode,
        executed.stdout,
        executed.stderr,
    )
