"""Strict-C regression coverage for managed compound-update temporaries."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src/tests/classes/test_class_compound_assignment.btrc"
COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


@pytest.fixture(scope="module")
def compound_fixture_c(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("managed-compound") / "fixture.c"
    transpiled = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(FIXTURE),
            "--no-cache",
            "-o",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert transpiled.returncode == 0, transpiled.stderr
    return output


def _function_body(source: str, signature: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(signature)} \{{\n(?P<body>.*?)^\}}$",
        source,
    )
    assert match is not None, f"missing generated function: {signature}"
    return match.group("body")


def test_class_edge_update_only_captures_a_consumed_current_value(
    compound_fixture_c: Path,
) -> None:
    source = compound_fixture_c.read_text()
    regular = _function_body(
        source,
        "void ScalarCounterHolder_add(ScalarCounterHolder* self, int amount)",
    )
    generic = _function_body(
        source,
        "static void btrc_GenericScalarCounterHolder_int_add(btrc_GenericScalarCounterHolder_int* self, int amount)",
    )
    declaration = re.compile(r"ScalarCounter\* __btrc_update_current_\d+ = 0;")

    assert declaration.findall(regular) == []
    # The generic method still needs one snapshot for its local `local += amount`.
    assert len(declaration.findall(generic)) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="requires a Unix C runtime")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_class_compound_fixture_is_strict_c11_warning_clean(
    tmp_path: Path,
    compound_fixture_c: Path,
    c_compiler: str,
) -> None:
    executable = tmp_path / "class-compound"
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(compound_fixture_c),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr

    executed = subprocess.run([executable], capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.strip() == "PASS: test_class_compound_assignment"
