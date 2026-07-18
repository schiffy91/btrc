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


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            """
            MutexLifecyclePayload payload = new MutexLifecyclePayload(1);
            Mutex<MutexLifecyclePayload> value = Mutex(payload);
            release payload;
            assert(mutexLifecyclePayloadsAlive == 1);
            delete value;
            assert(mutexLifecyclePayloadsAlive == 0);
            assert(mutexLifecyclePayloadsDestroyed == 1);
            """,
            id="delete",
        ),
        pytest.param(
            """
            MutexLifecyclePayload payload = new MutexLifecyclePayload(2);
            Mutex<MutexLifecyclePayload> value = Mutex(payload);
            release payload;
            assert((int)btrcTestMutexRefCount(value) == 1);
            keep value;
            assert((int)btrcTestMutexRefCount(value) == 2);
            btrcTestReleaseKeptMutex(value);
            assert((int)btrcTestMutexRefCount(value) == 1);
            Mutex<MutexLifecyclePayload> alias = value;
            assert((int)btrcTestMutexRefCount(alias) == 2);
            release value;
            assert((int)btrcTestMutexRefCount(alias) == 1);
            assert(alias.get().id == 2);
            delete alias;
            assert(mutexLifecyclePayloadsAlive == 0);
            assert(mutexLifecyclePayloadsDestroyed == 1);
            """,
            id="balanced-keep-release",
        ),
    ],
)
def test_mutex_supports_arc_ownership_operations(
    semantic_btrcc: Path,
    tmp_path: Path,
    body: str,
) -> None:
    source = f"""
        #include <assert.h>
        #define btrcTestMutexRefCount(value) ((int)((value)->arc.rc))
        #define btrcTestReleaseKeptMutex(value) \
            ((void)__btrc_arc_release((value), (&__btrc_mutex_arc_descriptor)))

        int mutexLifecyclePayloadsAlive = 0;
        int mutexLifecyclePayloadsDestroyed = 0;

        class MutexLifecyclePayload {{
            public int id;
            public MutexLifecyclePayload(int id) {{
                self.id = id;
                mutexLifecyclePayloadsAlive++;
            }}
            public void __del__() {{
                mutexLifecyclePayloadsAlive--;
                mutexLifecyclePayloadsDestroyed++;
            }}
        }}

        int main() {{
            {body}
            return 0;
        }}
    """
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "mutex-arc-operation",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


def test_destroy_releases_only_the_current_mutex_alias(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int main() {
            Mutex<int> original = Mutex(7);
            Mutex<int> alias = original;
            original.destroy();
            assert(alias.get() == 7);
            alias.destroy();
            return 0;
        }
    """
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "mutex-alias-destroy",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


def test_destroy_must_be_a_standalone_expression_statement(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            Mutex<int> value = Mutex(1);
            for (int index = 0; index < 1; value.destroy()) {
                index++;
            }
            return 0;
        }
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference(
        tmp_path,
        source,
        "mutex-nested-destroy",
    )
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert "Mutex.destroy() must be a standalone expression statement" in result.stderr
