"""Fail-closed source I/O and dependency-resolution boundaries."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _selfhost(compiler: Path, program: Path, *, timeout: int = 120):
    return subprocess.run(
        [str(compiler), "--no-stdlib", str(program)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _reference(program: Path, output: Path, *, timeout: int = 120):
    return subprocess.run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(program),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(output),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.mark.parametrize(
    "payload",
    [b"", b"\xef\xbb\xbfint main() { return 0; }\r\n"],
    ids=["empty", "bom-crlf"],
)
def test_source_text_boundary_preserves_valid_inputs(
    semantic_btrcc: Path,
    tmp_path: Path,
    payload: bytes,
) -> None:
    program = tmp_path / "valid.btrc"
    program.write_bytes(payload)

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr


@pytest.mark.parametrize(
    "payload",
    [b"int main() { return 0; }\0int hidden;\n", b"int main() { return 0; }\xff\n"],
    ids=["nul", "invalid-utf8"],
)
def test_source_text_boundary_rejects_lossy_inputs(
    semantic_btrcc: Path,
    tmp_path: Path,
    payload: bytes,
) -> None:
    program = tmp_path / "invalid.btrc"
    program.write_bytes(payload)

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode != 0
    assert reference.returncode != 0


def test_source_text_boundary_enforces_the_production_size_limit(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    program = tmp_path / "oversized.btrc"
    with program.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode != 0
    assert "67108864-byte limit" in selfhost.stderr
    assert reference.returncode != 0
    assert "67108864-byte limit" in reference.stderr


def test_dependency_read_failure_is_not_an_empty_include(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    dependency = tmp_path / "dependency.btrc"
    dependency.mkdir()
    program = tmp_path / "program.btrc"
    program.write_text('#include "dependency.btrc"\nint main() { return 0; }\n')

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode != 0
    assert "cannot read source file" in selfhost.stderr
    assert reference.returncode != 0
    assert "cannot read source file" in reference.stderr


@pytest.mark.parametrize(
    "directive",
    ['#include "missing.btrc"', "import ./missing.btrc", "import std.missing"],
)
def test_unresolved_dependency_is_fatal_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
    directive: str,
) -> None:
    program = tmp_path / "program.btrc"
    program.write_text(f"{directive}\nint main() {{ return 0; }}\n")

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode != 0
    assert reference.returncode != 0


@pytest.mark.parametrize("package", ["dep", "dep.module"])
def test_selfhost_rejects_package_names_instead_of_guessing_local_paths(
    semantic_btrcc: Path,
    tmp_path: Path,
    package: str,
) -> None:
    (tmp_path / package).write_text("int dependency() { return 1; }\n")
    program = tmp_path / "program.btrc"
    program.write_text(f"import {package}\nint main() {{ return 0; }}\n")

    result = _selfhost(semantic_btrcc, program)

    assert result.returncode != 0
    assert "package import" in result.stderr
    assert "unsupported by btrcc" in result.stderr


@pytest.mark.parametrize(
    "directive",
    ["import 'dep.btrc'", 'import "one.btrc" "two.btrc"', "import std.{vector"],
)
def test_malformed_imports_are_not_removed_before_parsing(
    semantic_btrcc: Path,
    tmp_path: Path,
    directive: str,
) -> None:
    program = tmp_path / "program.btrc"
    program.write_text(f"{directive}\nint main() {{ return 0; }}\n")

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode != 0
    assert reference.returncode != 0


@pytest.mark.parametrize("directive", ["import std . math", "import std . { math }"])
def test_spaced_std_imports_follow_the_grammar(
    semantic_btrcc: Path,
    tmp_path: Path,
    directive: str,
) -> None:
    program = tmp_path / "program.btrc"
    program.write_text(f"{directive}\nint main() {{ return 0; }}\n")

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr


def test_quoted_import_uses_the_lexer_payload(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    (tmp_path / "semi;colon.btrc").write_text("int dependency() { return 1; }\n")
    program = tmp_path / "program.btrc"
    program.write_text('import "semi;colon.btrc" // trailing comment\nint main() { return dependency() - 1; }\n')

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr


@pytest.mark.parametrize(
    "directive",
    ["import std.{\n math,\n vector\n}", "import std .\n math"],
)
def test_multiline_imports_follow_the_whitespace_insensitive_grammar(
    semantic_btrcc: Path,
    tmp_path: Path,
    directive: str,
) -> None:
    program = tmp_path / "program.btrc"
    program.write_text(f"{directive}\nint main() {{ return 0; }}\n")

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr


def test_import_depth_limit_precedes_stack_exhaustion(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    count = 258
    for index in range(count):
        path = tmp_path / f"level_{index}.btrc"
        if index + 1 < count:
            path.write_text(f'#include "level_{index + 1}.btrc"\n')
        else:
            path.write_text("int terminal() { return 0; }\n")

    root = tmp_path / "level_0.btrc"
    selfhost = _selfhost(semantic_btrcc, root)
    reference = _reference(root, tmp_path / "reference.c")

    assert selfhost.returncode != 0
    assert "maximum depth of 256" in selfhost.stderr
    assert reference.returncode != 0
    assert "maximum depth of 256" in reference.stderr


@pytest.mark.skipif(not Path("/dev/full").exists(), reason="requires /dev/full")
def test_stdout_flush_failure_returns_nonzero(semantic_btrcc: Path) -> None:
    with Path("/dev/full").open("wb", buffering=0) as sink:
        result = subprocess.run(
            [str(semantic_btrcc), "--help"],
            cwd=REPO,
            stdout=sink,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )

    assert result.returncode != 0
    assert "cannot write standard output" in result.stderr


def test_frontend_scan_limits_are_wired_before_materialization() -> None:
    frontend = (REPO / "src/compiler/btrc/frontend.btrc").read_text()
    source_io = (REPO / "src/compiler/btrc/frontend_source_io.btrc").read_text()
    filesystem = (REPO / "src/stdlib/fs.btrc").read_text()

    assert "feReadRequiredDirectory(path, budget.remainingEntries())" in frontend
    assert "directory.entriesBounded(maxEntries)" in source_io
    assert "budget.addEntries(entries.len)" in frontend
    assert "budget.addFile()" in frontend
    assert "Vector<string> pending = []" in frontend
    assert "result.len > maxEntries" in filesystem
