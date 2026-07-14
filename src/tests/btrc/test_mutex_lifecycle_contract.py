"""Consumption and repeated-operation contracts for ``Mutex<T>`` handles."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import (
    COMPILERS,
    REPO,
    _compile_pair,
    _compile_reference,
    _strict_matrix,
)
from src.tests.btrc.test_semantic_validation import _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

pytestmark = pytest.mark.skipif(
    not COMPILERS,
    reason="requires a pthread C11 compiler",
)


def test_direct_repeated_destroy_is_idempotent(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            Mutex<int> value = Mutex(1);
            value.destroy();
            value.destroy();
            return 0;
        }
    """
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "mutex-repeated-destroy",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


def test_consumed_mutex_access_fails_deterministically(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            Mutex<int> value = Mutex(1);
            value.destroy();
            return value.get();
        }
    """
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "mutex-consumed-get",
    )
    compiler = COMPILERS[0]
    for name, generated in compiled:
        output = tmp_path / f"{name}-consumed-get"
        build = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O2",
                str(generated),
                "-pthread",
                "-lm",
                "-o",
                str(output),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert build.returncode == 0, build.stderr
        run = subprocess.run(
            [str(output)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert run.returncode != 0
        assert "cannot get a null Mutex" in run.stderr


@pytest.mark.parametrize("operation", ["delete", "keep", "release"])
def test_mutex_arc_ownership_operations_are_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
    operation: str,
) -> None:
    source = f"""
        int main() {{
            Mutex<int> value = Mutex(1);
            {operation} value;
            return 0;
        }}
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference(
        tmp_path,
        source,
        "mutex-invalid-ownership",
    )
    diagnostic = f"{operation} is not valid for type 'Mutex<int>'"
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert diagnostic in result.stderr
