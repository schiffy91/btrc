"""Portable Thread<T> result transport contracts for both compilers."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_semantic_validation import _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPO = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).with_name("fixtures")
ABI_RUNTIME = FIXTURES / "thread_result_abi_runtime.btrc"
MANAGED_RUNTIME = FIXTURES / "thread_managed_result_ownership_runtime.btrc"
SCOPE_RUNTIME = FIXTURES / "thread_scope_cleanup_runtime.btrc"
COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

pytestmark = pytest.mark.skipif(
    not COMPILERS,
    reason="requires a pthread C11 compiler",
)


def _compile_reference(tmp_path: Path, source: str, name: str):
    program = tmp_path / f"{name}.btrc"
    generated = tmp_path / f"{name}.reference.c"
    program.write_text(source)
    result = subprocess.run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(program),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(generated),
        ],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")},
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result, generated


def _compile_pair(semantic_btrcc, tmp_path, source, name):
    selfhost, selfhost_c = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_c = _compile_reference(tmp_path, source, name)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return ("selfhost", selfhost_c), ("reference", reference_c)


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
    for compiler in COMPILERS:
        output = tmp_path / f"{compiled[0]}-{Path(compiler).name}"
        build = _build(compiled[1], output, compiler, support=support)
        assert build.returncode == 0, build.stderr
        run = _run(output)
        assert run.returncode == 0, run.stderr


def test_value_result_abi_has_strict_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
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
    compiled = _compile_pair(
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
    compiled = _compile_pair(
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
    compiled = _compile_pair(
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
    compiled = _compile_pair(
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
    compiled = _compile_pair(
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
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference(tmp_path, source, "typed-entry")
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
    compiled = _compile_pair(
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
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "repeated-join",
    )
    compiler = COMPILERS[0]
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
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference(tmp_path, source, "thread-alias")
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert "Thread handles cannot be copied" in result.stderr
