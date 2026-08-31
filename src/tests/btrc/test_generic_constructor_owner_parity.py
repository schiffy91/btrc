"""Reference/self-host parity for generic constructor owner validation."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    REPO,
    _compile_reference_source,
    _compile_source,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _compile_pair(semantic_btrcc: Path, tmp_path: Path, source: str):
    selfhost, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = _compile_reference_source(tmp_path, source)
    return (("selfhost", selfhost, selfhost_c), ("reference", reference, reference_c))


def _strict_build_and_run(generated: Path, executable: Path, compiler: str) -> None:
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
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run(
        [str(executable)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr


VALID_PROGRAMS = (
    pytest.param(
        "import std.vector;\nint main() { return 0; }\n",
        id="imported-generic-constructor",
    ),
    pytest.param(
        """\
import std.vector;
int main() {
    Vector<int> values = [];
    values.push(1);
    return values.get(0) - 1;
}
""",
        id="runtime-generic-instance",
    ),
    pytest.param(
        """\
class Box<T> {
    public T value;
    public Box(T value) { self.value = value; }
    public T get() { return self.value; }
}
int main() {
    Box<int> box = new Box<int>(7);
    int result = box.get() - 7;
    delete box;
    return result;
}
""",
        id="user-generic-constructor",
    ),
)


@pytest.mark.parametrize("source", VALID_PROGRAMS)
def test_generic_constructor_owners_have_strict_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    compiled = _compile_pair(semantic_btrcc, tmp_path, source)
    for frontend, result, generated in compiled:
        assert result.returncode == 0, result.stderr
        for compiler in COMPILERS:
            executable = tmp_path / f"{frontend}-{Path(compiler).name}"
            _strict_build_and_run(generated, executable, compiler)


INVALID_PROGRAMS = (
    pytest.param(
        """\
import std.vector;
int main() {
    Vector values;
    return 0;
}
""",
        "Type 'Vector' expects 1 generic argument(s) but got 0",
        None,
        None,
        id="runtime-generic",
    ),
    pytest.param(
        """\
class Box<T> {
    public Box() {}
}
int main() {
    Box value;
    return 0;
}
""",
        "Type 'Box' expects 1 generic argument(s) but got 0",
        5,
        5,
        id="user-generic-class",
    ),
    pytest.param(
        """\
interface Reader<T> {
    T read();
}
int main() {
    Reader value;
    return 0;
}
""",
        "Type 'Reader' expects 1 generic argument(s) but got 0",
        5,
        5,
        id="user-generic-interface",
    ),
)


def _diagnostic_identity(stderr: str) -> tuple[str, int, int]:
    first_line = stderr.splitlines()[0]
    selfhost = re.fullmatch(r"error: (?P<message>.*) at (?P<line>\d+):(?P<col>\d+)", first_line)
    if selfhost is not None:
        return selfhost.group("message"), int(selfhost.group("line")), int(selfhost.group("col"))
    reference = re.search(
        r"error: (?P<message>[^\n]+)\n\s*--> .*:(?P<line>\d+):(?P<col>\d+)",
        stderr,
    )
    assert reference is not None, stderr
    return reference.group("message"), int(reference.group("line")), int(reference.group("col"))


@pytest.mark.parametrize(("source", "diagnostic", "line", "col"), INVALID_PROGRAMS)
def test_bare_generic_declarations_fail_with_message_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
    line: int | None,
    col: int | None,
) -> None:
    for _frontend, result, _generated in _compile_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode == 1
        identity = _diagnostic_identity(result.stderr)
        assert identity[0] == diagnostic
        if line is not None and col is not None:
            assert identity[1:] == (line, col)
