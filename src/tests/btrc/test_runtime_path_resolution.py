"""Native security and relocation tests for self-host runtime-data discovery."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).with_name("fixtures") / "runtime_paths_probe.btrc"
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))

pytestmark = pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    process_executable: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        executable=str(process_executable) if process_executable else None,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _environment(**values: str) -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("BTRC_HOME", None)
    environment.update(values)
    return environment


@pytest.fixture(scope="module")
def runtime_path_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("runtime-path-probe")
    generated = output / "probe.c"
    binary = output / "probe"
    transpile = subprocess.run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(SOURCE),
            "--no-cache",
            "-o",
            str(generated),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert transpile.returncode == 0, transpile.stderr
    compile_result = subprocess.run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(generated),
            "-o",
            str(binary),
            "-lm",
            "-lpthread",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    return binary


def _data_root(root: Path) -> Path:
    (root / "language").mkdir(parents=True)
    (root / "stdlib").mkdir()
    (root / "language/grammar.ebnf").write_text("@lexical\n", encoding="utf-8")
    (root / "stdlib/vector.btrc").write_text("class Vector {}\n", encoding="utf-8")
    (root / "stdlib/strings.btrc").write_text("class Strings {}\n", encoding="utf-8")
    return root


def _install(runtime_path_probe: Path, root: Path) -> tuple[Path, Path]:
    binary = root / "bin/runtime-path-probe"
    binary.parent.mkdir(parents=True)
    shutil.copy2(runtime_path_probe, binary)
    binary.chmod(0o755)
    data = _data_root(root / "share/btrc")
    return binary, data


def _expected_lines(data: Path) -> list[str]:
    canonical = data.resolve()
    return [str(canonical), str(canonical / "language/grammar.ebnf"), str(canonical / "stdlib")]


def test_executable_relative_data_works_from_unrelated_cwd(runtime_path_probe: Path, tmp_path: Path) -> None:
    binary, data = _install(runtime_path_probe, tmp_path / "install")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    result = _run([str(binary)], cwd=unrelated, env=_environment())
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == _expected_lines(data)


def test_absolute_path_lookup_and_symlink_follow_the_real_binary(runtime_path_probe: Path, tmp_path: Path) -> None:
    binary, data = _install(runtime_path_probe, tmp_path / "install")
    unrelated = tmp_path / "unrelated"
    links = tmp_path / "links"
    unrelated.mkdir()
    links.mkdir()
    symlink = links / "linked-probe"
    symlink.symlink_to(binary)

    by_path = _run(
        [binary.name],
        cwd=unrelated,
        env=_environment(PATH=str(binary.parent)),
    )
    by_symlink = _run([str(symlink)], cwd=unrelated, env=_environment())
    assert by_path.returncode == 0, by_path.stderr
    assert by_symlink.returncode == 0, by_symlink.stderr
    assert by_path.stdout.splitlines() == _expected_lines(data)
    assert by_symlink.stdout.splitlines() == _expected_lines(data)


def test_quoted_absolute_path_entry_is_resolved(runtime_path_probe: Path, tmp_path: Path) -> None:
    binary, data = _install(runtime_path_probe, tmp_path / "install")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    result = _run(
        [binary.name],
        cwd=unrelated,
        env=_environment(PATH=f'"{binary.parent}"'),
        process_executable=binary,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == _expected_lines(data)


def test_btrc_home_is_authoritative(runtime_path_probe: Path, tmp_path: Path) -> None:
    binary, _ = _install(runtime_path_probe, tmp_path / "install")
    override = _data_root(tmp_path / "override")
    valid = _run([str(binary)], cwd=tmp_path, env=_environment(BTRC_HOME=str(override)))
    assert valid.returncode == 0, valid.stderr
    assert valid.stdout.splitlines() == _expected_lines(override)

    invalid_root = tmp_path / "missing"
    invalid = _run([str(binary)], cwd=tmp_path, env=_environment(BTRC_HOME=str(invalid_root)))
    assert invalid.returncode == 2
    assert invalid.stdout == ""
    assert "BTRC_HOME data directory does not exist" in invalid.stderr

    empty = _run([str(binary)], cwd=tmp_path, env=_environment(BTRC_HOME=""))
    assert empty.returncode == 2
    assert "BTRC_HOME is set but does not name a data directory" in empty.stderr

    incomplete = tmp_path / "incomplete"
    (incomplete / "language").mkdir(parents=True)
    (incomplete / "language/grammar.ebnf").write_text("@lexical\n", encoding="utf-8")
    incomplete_result = _run(
        [str(binary)],
        cwd=tmp_path,
        env=_environment(BTRC_HOME=str(incomplete)),
    )
    assert incomplete_result.returncode == 2
    assert "BTRC_HOME is missing the stdlib directory" in incomplete_result.stderr


def test_executable_relative_source_tree_is_an_explicit_dev_layout(runtime_path_probe: Path, tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    binary = checkout / "bin/runtime-path-probe"
    binary.parent.mkdir(parents=True)
    shutil.copy2(runtime_path_probe, binary)
    binary.chmod(0o755)
    data = _data_root(checkout / "src")
    marker = checkout / "src/compiler/btrc/btrcc_main.btrc"
    marker.parent.mkdir(parents=True)
    marker.write_text("int main() { return 0; }\n", encoding="utf-8")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()

    result = _run([str(binary)], cwd=unrelated, env=_environment())
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == _expected_lines(data)


@pytest.mark.parametrize("marked", [False, True], ids=("unmarked", "marked"))
def test_temporary_build_never_uses_source_tree_cwd(
    runtime_path_probe: Path,
    tmp_path: Path,
    marked: bool,
) -> None:
    checkout = tmp_path / "checkout"
    _data_root(checkout / "src")
    if marked:
        marker = checkout / "src/compiler/btrc/btrcc_main.btrc"
        marker.parent.mkdir(parents=True)
        marker.write_text("int main() { return 0; }\n", encoding="utf-8")
    rejected = _run(
        [str(runtime_path_probe)],
        cwd=checkout,
        env=_environment(),
    )
    assert rejected.returncode == 2
    assert rejected.stdout == ""
    assert "executable-relative data directory does not exist" in rejected.stderr


@pytest.mark.parametrize("search_path", [".", ":/definitely/not/a/btrc/path", "/definitely/not/a/btrc/path:"])
def test_relative_or_empty_path_entry_is_not_a_cwd_fallback(
    runtime_path_probe: Path,
    tmp_path: Path,
    search_path: str,
) -> None:
    executable, _ = _install(runtime_path_probe, tmp_path / "install")
    result = _run(
        [executable.name],
        cwd=executable.parent,
        env=_environment(PATH=search_path),
        process_executable=executable,
    )
    assert result.returncode == 2
    assert "cannot securely resolve compiler executable" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX execute permissions")
def test_non_executable_path_candidate_is_rejected(runtime_path_probe: Path, tmp_path: Path) -> None:
    candidate_directory = tmp_path / "candidate"
    candidate_directory.mkdir()
    candidate = candidate_directory / "runtime-path-probe"
    shutil.copy2(runtime_path_probe, candidate)
    candidate.chmod(0o644)
    _data_root(tmp_path / "share/btrc")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    result = _run(
        [candidate.name],
        cwd=unrelated,
        env=_environment(PATH=str(candidate_directory)),
        process_executable=runtime_path_probe,
    )
    assert result.returncode == 2
    assert "cannot securely resolve compiler executable" in result.stderr
