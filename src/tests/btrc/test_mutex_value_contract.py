"""Portable value, ownership, and race contracts for ``Mutex<T>``."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
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
ABI_RUNTIME = FIXTURES / "mutex_value_abi_runtime.btrc"
MANAGED_RUNTIME = FIXTURES / "mutex_managed_ownership_runtime.btrc"
STRING_RUNTIME = FIXTURES / "mutex_string_ownership_runtime.btrc"
CONCURRENT_RUNTIME = FIXTURES / "mutex_concurrent_snapshot_runtime.btrc"
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
    reference, reference_c = _compile_reference(
        tmp_path,
        source,
        name,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return ("selfhost", selfhost_c), ("reference", reference_c)


def _build_and_run(generated, output, compiler, extra_flags=()):
    environment = None
    if sys.platform == "darwin" and os.path.realpath(compiler) == "/usr/bin/clang":
        environment = {
            name: os.environ[name]
            for name in (
                "HOME",
                "USER",
                "LOGNAME",
                "LANG",
                "LC_ALL",
                "LC_CTYPE",
            )
            if name in os.environ
        }
        environment.update(
            {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "TMPDIR": "/tmp",
            }
        )
    build = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O1" if extra_flags else "-O2",
            *extra_flags,
            str(generated),
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
    run_environment = dict(os.environ if environment is None else environment)
    run_environment["TSAN_OPTIONS"] = "halt_on_error=1"
    run = subprocess.run(
        [str(output)],
        cwd=REPO,
        env=run_environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr


def _strict_matrix(compiled, tmp_path):
    for compiler in COMPILERS:
        output = tmp_path / f"{compiled[0]}-{Path(compiler).name}"
        _build_and_run(compiled[1], output, compiler)


@pytest.mark.parametrize(
    "fixture,name",
    [
        (ABI_RUNTIME, "mutex-value-abi"),
        (MANAGED_RUNTIME, "mutex-managed-ownership"),
        (STRING_RUNTIME, "mutex-string-ownership"),
        (CONCURRENT_RUNTIME, "mutex-concurrent-snapshot"),
    ],
)
def test_mutex_contracts_have_strict_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture: Path,
    name: str,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        name,
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


def test_managed_mutex_callbacks_are_strict_aliasing_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        MANAGED_RUNTIME.read_text(),
        "mutex-managed-strict-aliasing",
    )
    for compiler_name, generated in compiled:
        for compiler in COMPILERS:
            output = tmp_path / f"{compiler_name}-{Path(compiler).name}-strict-aliasing"
            _build_and_run(
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
    ],
)
def test_mutex_contracts_are_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture: Path,
    name: str,
) -> None:
    require_sanitizers(tmp_path)
    compiled = _compile_pair(
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
    clang = (
        "/usr/bin/clang" if sys.platform == "darwin" and os.access("/usr/bin/clang", os.X_OK) else shutil.which("clang")
    )
    if clang is None:
        pytest.skip("ThreadSanitizer requires clang")
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        CONCURRENT_RUNTIME.read_text(),
        "mutex-concurrent-tsan",
    )
    try:
        for compiler_name, generated in compiled:
            _build_and_run(
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
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference(
        tmp_path,
        source,
        "mutex-invalid-construction",
    )
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert diagnostic in result.stderr
