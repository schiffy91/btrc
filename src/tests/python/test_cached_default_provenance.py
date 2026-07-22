"""Cached CLI source provenance for declaration-scoped defaults."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.frontend.dependencies import ResolvedSource

REPO = Path(__file__).resolve().parents[3]
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))


def _run(command: list[str], *, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_declaration_line_map_disambiguates_split_user_and_stdlib_coordinates(tmp_path: Path) -> None:
    stdlib = tmp_path / "stdlib.btrc"
    user = tmp_path / "user.btrc"
    source = ResolvedSource(
        user_source="user one\nuser two",
        source="stdlib one\nstdlib two\nuser one\nuser two",
        stdlib_source="stdlib one\nstdlib two",
        source_positions=(
            (str(stdlib), 10),
            (str(stdlib), 11),
            (str(user), 20),
            (str(user), 21),
        ),
    )

    assert source.map_declaration_line(1, str(stdlib), split_spaces=True) == (str(stdlib), 10)
    assert source.map_declaration_line(1, str(user), split_spaces=True) == (str(user), 20)
    assert source.map_declaration_line(3, str(user), split_spaces=False) == (str(user), 20)


def test_cache_identity_covers_root_import_path_and_native_line(tmp_path: Path) -> None:
    root = tmp_path / "program.btrc"
    first_import = tmp_path / "first" / "defaults.btrc"
    second_import = tmp_path / "second" / "defaults.btrc"

    def identity(source_root: Path, imported: Path, native_line: int) -> str:
        return ResolvedSource(
            user_source="int value = 1;",
            source="int value = 1;",
            source_positions=((str(imported), native_line),),
            root_source_path=str(source_root.resolve()),
        ).cache_identity()

    baseline = identity(root, first_import, 7)
    assert identity(tmp_path / "other.btrc", first_import, 7) != baseline
    assert identity(root, second_import, 7) != baseline
    assert identity(root, first_import, 8) != baseline


@pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)
def test_cached_cli_preserves_local_and_imported_default_source_coordinates(tmp_path: Path) -> None:
    first_root = tmp_path / "first-project"
    second_root = tmp_path / "second-project"
    first_root.mkdir()
    second_root.mkdir()
    dependency_source = (
        "const char* importedFile(const char* value = __FILE__) { return value; }\n"
        "int importedLine(int value = __LINE__) { return value; }\n"
    )
    program_source = (
        "import ./imported_defaults.btrc\n"
        "const char* localFile(const char* value = __FILE__) { return value; }\n"
        "int localLine(int value = __LINE__) { return value; }\n"
        "int main() {\n"
        '    printf("%s\\n%d\\n%s\\n%d\\n", localFile(), localLine(), importedFile(), importedLine());\n'
        "    return 0;\n"
        "}\n"
    )
    for root in (first_root, second_root):
        (root / "imported_defaults.btrc").write_text(dependency_source, encoding="utf-8")
        (root / "program.btrc").write_text(program_source, encoding="utf-8")

    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")}
    compilations = []
    for index, root in enumerate((first_root, first_root, second_root, second_root)):
        source = root / "program.btrc"
        output = tmp_path / f"program-{index}.c"
        result = _run(
            [
                "python3",
                "-m",
                "src.compiler.python.main",
                str(source),
                "--no-stdlib",
                "-o",
                str(output),
            ],
            environment=environment,
        )
        assert result.returncode == 0, result.stderr
        compilations.append((root, output, result))

    first_fresh, first_cached, second_fresh, second_cached = compilations
    assert "(cached)" not in first_fresh[2].stdout
    assert "(cached)" in first_cached[2].stdout
    assert "(cached)" not in second_fresh[2].stdout
    assert "(cached)" in second_cached[2].stdout
    assert first_fresh[1].read_bytes() == first_cached[1].read_bytes()
    assert second_fresh[1].read_bytes() == second_cached[1].read_bytes()
    assert first_fresh[1].read_bytes() != second_fresh[1].read_bytes()

    executable = tmp_path / "program"
    build = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(second_cached[1]),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        environment=environment,
    )
    assert build.returncode == 0, build.stderr
    executed = _run([str(executable)], environment=environment)
    assert executed.returncode == 0, executed.stderr
    source = second_root / "program.btrc"
    dependency = second_root / "imported_defaults.btrc"
    assert executed.stdout.splitlines() == [
        str(source.resolve()),
        "3",
        str(dependency.resolve()),
        "2",
    ]
