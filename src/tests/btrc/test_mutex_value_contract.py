"""Portable value, ownership, and race contracts for ``Mutex<T>``."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.dual_frontend_harness import (
    build_and_run_strict,
    compile_reference_snippet,
    compile_snippet_pair,
    strict_c11_matrix,
)
from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.selfhost_snippet_harness import compile_source
from src.tests.c_toolchains import HOST_C_COMPILERS, sanitizer_clang

FIXTURES = Path(__file__).with_name("fixtures")
ABI_RUNTIME = FIXTURES / "MutexValueAbiRuntime.btrc"
MANAGED_RUNTIME = FIXTURES / "MutexManagedOwnershipRuntime.btrc"
STRING_RUNTIME = FIXTURES / "MutexStringOwnershipRuntime.btrc"
CONCURRENT_RUNTIME = FIXTURES / "MutexConcurrentSnapshotRuntime.btrc"
MANAGED_CONCURRENT_RUNTIME = FIXTURES / "MutexManagedConcurrentRuntime.btrc"

pytestmark = pytest.mark.skipif(
    not HOST_C_COMPILERS,
    reason="requires a pthread C11 compiler",
)


@pytest.mark.parametrize(
    "fixture,name",
    [
        (ABI_RUNTIME, "mutex-value-abi"),
        (MANAGED_RUNTIME, "mutex-managed-ownership"),
        (STRING_RUNTIME, "mutex-string-ownership"),
        (CONCURRENT_RUNTIME, "mutex-concurrent-snapshot"),
        (MANAGED_CONCURRENT_RUNTIME, "mutex-managed-concurrent"),
    ],
)
def test_mutex_contracts_have_strict_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture: Path,
    name: str,
) -> None:
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        name,
    )
    for artifact in compiled:
        strict_c11_matrix(artifact, tmp_path)


def test_managed_mutex_callbacks_are_strict_aliasing_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        MANAGED_RUNTIME.read_text(),
        "mutex-managed-strict-aliasing",
    )
    for compiler_name, generated in compiled:
        for compiler in HOST_C_COMPILERS:
            output = tmp_path / f"{compiler_name}-{Path(compiler).name}-strict-aliasing"
            build_and_run_strict(
                generated,
                output,
                compiler,
                ("-O3", "-fstrict-aliasing"),
            )


@pytest.mark.parametrize(
    "fixture,name",
    [
        (ABI_RUNTIME, "mutex-value-abi-san"),
        (MANAGED_RUNTIME, "mutex-managed-ownership-san"),
        (STRING_RUNTIME, "mutex-string-ownership-san"),
        (MANAGED_CONCURRENT_RUNTIME, "mutex-managed-concurrent-san"),
    ],
)
def test_mutex_contracts_are_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture: Path,
    name: str,
) -> None:
    require_sanitizers(tmp_path)
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        name,
    )
    for compiler_name, generated in compiled:
        sanitized_build_and_run(
            generated,
            tmp_path / f"{compiler_name}-{name}",
        )


def test_mutex_concurrent_snapshots_are_thread_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    clang = sanitizer_clang()
    if clang is None:
        pytest.skip("ThreadSanitizer requires clang")
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        CONCURRENT_RUNTIME.read_text(),
        "mutex-concurrent-tsan",
    )
    try:
        for compiler_name, generated in compiled:
            build_and_run_strict(
                generated,
                tmp_path / f"{compiler_name}-tsan",
                clang,
                ("-g", "-fsanitize=thread", "-fno-omit-frame-pointer"),
            )
    except AssertionError as error:
        if "ThreadSanitizer" in str(error) or "-ltsan" in str(error):
            pytest.skip(f"ThreadSanitizer unavailable: {error}")
        raise


@pytest.mark.parametrize(
    "source,diagnostic",
    [
        ("int main() { Mutex(); return 0; }", "expects 1 argument"),
        (
            "int main() { Mutex<int> value = new Mutex<int>(); return 0; }",
            "expects exactly 1 argument",
        ),
        (
            'int main() { Mutex<int> value = new Mutex<int>("bad"); return 0; }',
            "Mutex initializer expects",
        ),
    ],
)
def test_mutex_construction_is_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    selfhost, _ = compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = compile_reference_snippet(
        tmp_path,
        source,
        "mutex-invalid-construction",
    )
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert diagnostic in result.stderr
