"""Reference/self-host parity for file-scope value reachability."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

DEAD_MODULE_SOURCE = """
    int abandonedState = 41;
    int abandonedFunction() { return abandonedState; }

    int main() { return 0; }
"""

ENTRYLESS_MODULE_SOURCE = """
    int orphanState = 41;
    int orphanFunction() { return orphanState; }
"""

GLOBAL_ONLY_MODULE_SOURCE = """
    int globalOnlyState = 41;
"""

LIVE_GLOBAL_SOURCE = """
    #define READ_MACRO_STATE() (macroState)

    int leafState = 42;
    int* rootState = &leafState;
    int macroState = 1;
    volatile int signalState = 0;
    extern int exportedState;
    int exportedState = 7;

    int main() {
        return *rootState == 42 && READ_MACRO_STATE() == 1 ? 0 : 1;
    }
"""


def _compile_pair(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> tuple[Path, Path]:
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return selfhost_source, reference_source


def _strict_build_and_run(
    source: Path,
    output: Path,
    c_compiler: str,
) -> None:
    build = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run(
        [str(output)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert run.returncode == 0, run.stderr


def _strict_compile(source: Path, output: Path, c_compiler: str) -> None:
    build = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-c",
            str(source),
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert build.returncode == 0, build.stderr


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_dead_module_globals_are_pruned_strictly(
    semantic_btrcc: Path,
    tmp_path: Path,
    c_compiler: str,
) -> None:
    generated = _compile_pair(
        semantic_btrcc,
        tmp_path,
        DEAD_MODULE_SOURCE,
    )

    for index, source in enumerate(generated):
        emitted = source.read_text()
        assert "abandonedState" not in emitted
        assert "abandonedFunction" not in emitted
        _strict_build_and_run(
            source,
            tmp_path / f"dead-{index}-{Path(c_compiler).name}",
            c_compiler,
        )


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize(
    ("entryless_source", "dead_symbols"),
    (
        (ENTRYLESS_MODULE_SOURCE, ("orphanState", "orphanFunction")),
        (GLOBAL_ONLY_MODULE_SOURCE, ("globalOnlyState",)),
    ),
    ids=("one-function", "zero-functions"),
)
def test_entryless_module_value_graph_is_pruned_strictly(
    semantic_btrcc: Path,
    tmp_path: Path,
    c_compiler: str,
    entryless_source: str,
    dead_symbols: tuple[str, ...],
) -> None:
    generated = _compile_pair(
        semantic_btrcc,
        tmp_path,
        entryless_source,
    )

    for index, source in enumerate(generated):
        emitted = source.read_text()
        assert all(symbol not in emitted for symbol in dead_symbols)
        _strict_compile(
            source,
            tmp_path / f"entryless-{index}-{Path(c_compiler).name}.o",
            c_compiler,
        )


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_live_global_roots_and_external_linkage_are_preserved(
    semantic_btrcc: Path,
    tmp_path: Path,
    c_compiler: str,
) -> None:
    generated = _compile_pair(
        semantic_btrcc,
        tmp_path,
        LIVE_GLOBAL_SOURCE,
    )

    for index, source in enumerate(generated):
        emitted = source.read_text()
        assert "static int leafState = 42;" in emitted
        assert "static int* rootState = (&leafState);" in emitted
        assert "static int macroState = 1;" in emitted
        assert "signalState" not in emitted
        assert "int exportedState = 7;" in emitted
        assert "static int exportedState" not in emitted
        _strict_build_and_run(
            source,
            tmp_path / f"live-{index}-{Path(c_compiler).name}",
            c_compiler,
        )
