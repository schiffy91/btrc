"""Checked-capacity contracts for ARC graph scratch storage."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.ir.gen.helpers import helper_decls_for_roots
from src.compiler.python.ir.helpers.cycles import CYCLES

ROOTS = {
    "__btrc_arc_abandon",
    "__btrc_arc_reverse_proves_live",
    "__btrc_collect_cycles_once",
    "__btrc_mark_destroyed",
    "__btrc_suspect",
}
RUNTIME = "\n\n".join(helper.c_source for helper in helper_decls_for_roots(ROOTS))
FIXTURE = Path(__file__).with_name("fixtures") / "cycle_capacity_guards.c"
MARKER = "/* BTRC_RUNTIME_HELPERS */"
SELFHOST = Path("src/compiler/btrc")
COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
FAILURE_CASES = {
    "cycle-capacity": "btrc: cycle capacity boundary\n",
    "cycle-bytes": "btrc: cycle byte boundary\n",
    "reverse-capacity": "btrc: reverse capacity boundary\n",
    "reverse-bytes": "btrc: reverse byte boundary\n",
    "suspect-capacity": "btrc: suspect capacity boundary\n",
    "suspect-bytes": "btrc: suspect byte boundary\n",
    "destroyed-state": "btrc: invalid destroyed tracking capacity\n",
}


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


def test_cycle_allocations_compute_checked_bytes_before_use() -> None:
    source = "\n".join(helper.c_source for helper in CYCLES.values())
    assert re.search(r"(?<!safe_)calloc\(", source) is None
    assert re.search(r"(?<!re)malloc\(", source) is None
    assert (
        re.search(
            r"(?:__btrc_safe_realloc|memset)\([^;]*"
            r"sizeof\([^)]*\)\s*\*\s*\(size_t\)",
            source,
            re.DOTALL,
        )
        is None
    )

    checked_helpers = {
        "__btrc_arc_graph_primitives": "__btrc_cycle_capacity_bytes",
        "__btrc_arc_reverse_proves_live": "__btrc_reverse_capacity_bytes",
        "__btrc_suspect_locked": "__btrc_suspect_capacity_bytes",
    }
    for helper_name, checked_atom in checked_helpers.items():
        helper = CYCLES[helper_name]
        assert checked_atom in helper.c_source
        assert "__btrc_safe_calloc" in helper.depends_on
        assert "__btrc_safe_realloc" in helper.depends_on

    for helper_name, capacity, size_check, allocation in (
        (
            "__btrc_arc_abandon",
            "__btrc_abandon_cap > INT_MAX / 2",
            "(size_t)cap > SIZE_MAX / sizeof(void*)",
            "__btrc_safe_realloc",
        ),
        (
            "__btrc_mark_destroyed",
            "__btrc_destroyed_cap > INT_MAX / 2",
            "(size_t)new_cap > SIZE_MAX / sizeof(void*)",
            "__btrc_safe_realloc",
        ),
    ):
        helper_source = CYCLES[helper_name].c_source
        assert helper_source.index(capacity) < helper_source.index(size_check)
        assert helper_source.index(size_check) < helper_source.index(allocation)


def test_selfhost_capacity_dependencies_match_checked_allocators() -> None:
    state_dependencies = (SELFHOST / "cycle_runtime_dependencies_state.btrc").read_text()
    lifecycle_dependencies = (SELFHOST / "cycle_runtime_dependencies_lifecycle.btrc").read_text()
    for source, helper_name in (
        (lifecycle_dependencies, "__btrc_arc_graph_primitives"),
        (state_dependencies, "__btrc_arc_reverse_proves_live"),
        (state_dependencies, "__btrc_suspect_locked"),
    ):
        marker = f'if (name == "{helper_name}")'
        start = source.index(marker)
        end = source.find("if (name ==", start + len(marker))
        branch = source[start : end if end >= 0 else None]
        assert 'out.push("__btrc_safe_calloc")' in branch
        assert 'out.push("__btrc_safe_realloc")' in branch


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_cycle_capacity_boundaries_are_strict_c11(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    fixture = FIXTURE.read_text()
    assert fixture.count(MARKER) == 1
    source = tmp_path / "cycle-capacity.c"
    executable = tmp_path / f"cycle-capacity-{Path(c_compiler).name}"
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
            "-Wno-unused-function",
            "-O2",
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

    success = subprocess.run(
        [str(executable), "ok"],
        capture_output=True,
        text=True,
        timeout=20,
        env=environment,
    )
    assert success.returncode == 0, (success.returncode, success.stderr)

    for case, expected_error in FAILURE_CASES.items():
        failed = subprocess.run(
            [str(executable), case],
            capture_output=True,
            text=True,
            timeout=20,
            env=environment,
        )
        assert failed.returncode == 1, (case, failed.returncode, failed.stderr)
        assert failed.stderr == expected_error
