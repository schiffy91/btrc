"""Portable Thread<T> result transport contracts for both compilers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.dual_frontend_harness import REPO, compile_reference_snippet, compile_snippet_pair
from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.selfhost_snippet_harness import compile_source
from src.tests.c_toolchains import HOST_C_COMPILERS

FIXTURES = Path(__file__).with_name("fixtures")
ABI_RUNTIME = FIXTURES / "ThreadResultAbiRuntime.btrc"
MANAGED_RUNTIME = FIXTURES / "ThreadManagedResultOwnershipRuntime.btrc"
SCOPE_RUNTIME = FIXTURES / "ThreadScopeCleanupRuntime.btrc"

pytestmark = pytest.mark.skipif(
    not HOST_C_COMPILERS,
    reason="requires a pthread C11 compiler",
)


def _build(
    generated: Path,
    output: Path,
    compiler: str,
    *,
    support: Path | None = None,
):
    command = [
        compiler,
        "-std=c11",
        "-pedantic-errors",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-O2",
    ]
    command.append(str(generated))
    if support is not None:
        command.append(str(support))
    command.extend(["-pthread", "-lm", "-o", str(output)])
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _run(output: Path):
    return subprocess.run(
        [str(output)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _strict_matrix(compiled, tmp_path, support=None):
    for compiler in HOST_C_COMPILERS:
        output = tmp_path / f"{compiled[0]}-{Path(compiler).name}"
        build = _build(compiled[1], output, compiler, support=support)
        assert build.returncode == 0, build.stderr
        run = _run(output)
        assert run.returncode == 0, run.stderr


def test_value_result_abi_has_strict_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        ABI_RUNTIME.read_text(),
        "thread-result-abi",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


def test_value_result_abi_is_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    require_sanitizers(tmp_path)
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        ABI_RUNTIME.read_text(),
        "thread-result-abi-sanitized",
    )
    for name, generated in compiled:
        sanitized_build_and_run(generated, tmp_path / f"{name}-abi-san")


def test_managed_result_transfers_one_owned_reference(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        MANAGED_RUNTIME.read_text(),
        "thread-managed-result",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


def test_managed_result_is_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    require_sanitizers(tmp_path)
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        MANAGED_RUNTIME.read_text(),
        "thread-managed-result-sanitized",
    )
    for name, generated in compiled:
        sanitized_build_and_run(generated, tmp_path / f"{name}-managed-san")


def test_unjoined_handles_have_strict_structured_cleanup(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        SCOPE_RUNTIME.read_text(),
        "thread-scope-cleanup",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


def test_unjoined_handle_cleanup_is_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    require_sanitizers(tmp_path)
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        SCOPE_RUNTIME.read_text(),
        "thread-scope-cleanup-sanitized",
    )
    for name, generated in compiled:
        sanitized_build_and_run(
            generated,
            tmp_path / f"{name}-scope-cleanup-san",
        )


def test_non_lambda_spawn_is_fail_closed_for_non_pthread_signatures(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int compute() { return 7; }
        int main() {
            __fn_ptr<int> entry = compute;
            var worker = spawn(entry);
            return 0;
        }
    """
    selfhost, _ = compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = compile_reference_snippet(tmp_path, source, "typed-entry")
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert "Non-lambda spawn requires __fn_ptr<void*, void*>" in result.stderr


def test_exact_pthread_entry_signature_remains_portable(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        extern void* echo(void* value);
        typedef __fn_ptr<void*, void*> ThreadEntry;
        int main() {
            ThreadEntry entry = echo;
            var worker = spawn(entry);
            assert(worker.join() == null);
            return 0;
        }
    """
    support = tmp_path / "pthread-entry.c"
    support.write_text("void* echo(void* value) { return value; }\n")
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "pthread-entry",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path, support=support)


def test_direct_repeated_join_fails_deterministically(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            Thread<int> worker = spawn(() => 7);
            int first = worker.join();
            int second = worker.join();
            return first + second;
        }
    """
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "repeated-join",
    )
    compiler = HOST_C_COMPILERS[0]
    for name, generated in compiled:
        output = tmp_path / f"{name}-repeated-join"
        build = _build(generated, output, compiler)
        assert build.returncode == 0, build.stderr
        run = _run(output)
        assert run.returncode != 0
        assert "cannot join a consumed thread handle" in run.stderr


def test_thread_handle_alias_copy_is_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            Thread<int> worker = spawn(() => 7);
            Thread<int> alias = worker;
            return alias.join();
        }
    """
    selfhost, _ = compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = compile_reference_snippet(tmp_path, source, "thread-alias")
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert "Thread handles cannot be copied" in result.stderr
