"""Defects the Stage 16 C1 integration review found, fixed in both compilers.

docs/design/c-compatibility.md ("Stage 16 integration notes") records each
finding. Every check here runs the reference compiler and btrcc on the same
source: a refusal must carry one diagnostic -- message, line and column -- in
both, and an accepted program must build under strict C11 and print the same
output from both, whichever translation-unit layout emitted it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.diagnostic_harness import diagnostic_identity
from src.tests.btrc.production_readiness_harness import compile_diagnostic_pair
from src.tests.c_toolchains import configured_c_compiler

REPO = Path(__file__).resolve().parents[3]
CC = configured_c_compiler()

CATCH_TYPE = "Catch type '{}' is not supported — exceptions carry a string message; use 'string e' or an untyped catch"
ABI_MIX = (
    "Operator '-' mixes ABI-dependent integer type 'size_t' with 'int'; "
    "cast explicitly to a fixed-width or built-in integer type"
)
EXACT_FIT = (
    "String literal fills all 3 elements of the char array and leaves no room for its terminator; "
    "declare 4 elements or leave the bound empty"
)

REFUSALS = [
    # F8: a typed catch names an exception class btrc does not have.
    pytest.param(
        "int main() { try { int a = 1; } catch (Exception e) { int b = 2; } return 0; }",
        (CATCH_TYPE.format("Exception"), 1, 40),
        id="f8-catch-exception",
    ),
    pytest.param(
        "class MyError { public int code; public MyError() {} }\n"
        "int main() {\n"
        '\ttry { throw "x"; } catch (MyError e) { print("c"); }\n'
        "\treturn 0;\n"
        "}\n",
        (CATCH_TYPE.format("MyError"), 3, 28),
        id="f8-catch-class",
    ),
    # F12: an array bound is an expression and is validated as one first.
    pytest.param(
        'int g[sizeof("abc") - 1];\nint main() { return 0; }',
        (ABI_MIX, 1, 7),
        id="f12-global-bound",
    ),
    pytest.param(
        'char g[sizeof("abc") - 1] = "abc";\nint main() { return 0; }',
        (ABI_MIX, 1, 8),
        id="f12-global-bound-before-exact-fit",
    ),
    pytest.param(
        'int main() { int g[sizeof("abc") - 1]; g[0] = 1; return g[0]; }',
        (ABI_MIX, 1, 20),
        id="f12-local-bound",
    ),
    pytest.param(
        'int main() { char t[sizeof("abc") - 1] = "abc"; return t[0]; }',
        (EXACT_FIT, 1, 42),
        id="f12-local-initializer-before-bound",
    ),
    pytest.param(
        'struct S { int a[sizeof("abc") - 1]; };\nint main() { return 0; }',
        (ABI_MIX, 1, 18),
        id="f12-struct-field-bound",
    ),
]


@pytest.mark.parametrize(("source", "expected"), REFUSALS)
def test_refusal_is_identical_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    expected: tuple[str, int, int],
) -> None:
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source)

    assert selfhost.returncode != 0 and reference.returncode != 0
    assert diagnostic_identity(reference.stderr) == expected
    assert diagnostic_identity(selfhost.stderr) == expected


def _build_and_run(
    compiler: list[str],
    program: Path,
    directory: Path,
    layout: list[str] | None,
    flags: tuple[str, ...] = (),
) -> str:
    """Transpile ``program`` in one unit layout, link every unit strictly, run it."""
    directory.mkdir()
    primary = directory / "program.c"
    plan = directory / "program.json"
    command = [*compiler, "--no-cache", *flags, str(program), "-o", str(primary)]
    if layout is not None:
        command += ["--emit-units", str(directory / "program"), *layout]
    command += ["--emit-link-plan", str(plan)]
    transpiled = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=300)
    assert transpiled.returncode == 0, transpiled.stderr
    units = json.loads(plan.read_text()).get("emitted-units", [])
    binary = directory / "program"
    built = subprocess.run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Werror",
            str(primary),
            *units,
            "-o",
            str(binary),
            "-lm",
            "-lpthread",
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(binary)], cwd=directory, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stderr
    return ran.stdout


def _compilers(semantic_btrcc: Path) -> dict[str, list[str]]:
    return {
        "reference": [sys.executable, "-m", "src.compiler.python.main"],
        "selfhost": [str(semantic_btrcc)],
    }


SHARED_MODULE = """\
char sharedText[] = "ab" "cd";
char sharedSingle[] = "xyz";
int sharedNumbers[] = {1, 2, 3};

class Table {
	class char name[] = "ta" "ble";
}
"""

MAIN_MODULE = """\
#include <stdio.h>
import ./Shared.btrc;

int main() {
	int letters = 0;
	for c in sharedText {
		if (c != 0) { letters += 1; }
	}
	Table.name[0] = 'T';
	printf("%d %d %s %d %s\\n", (int)sizeof(sharedText), letters, sharedText, (int)sizeof(sharedSingle), sharedSingle);
	printf("%d %d %s\\n", sharedNumbers[1], (int)sizeof(Table.name), Table.name);
	return 0;
}
"""


@pytest.mark.parametrize(
    "layout",
    [
        pytest.param(None, id="single-unit"),
        pytest.param([], id="split"),
        pytest.param(["--module-units"], id="module-units"),
    ],
)
def test_string_initialized_array_has_one_complete_type_in_every_unit(
    semantic_btrcc: Path,
    tmp_path: Path,
    layout: list[str] | None,
) -> None:
    """F9 and F10: an unsized string-initialized array takes the string's extent."""
    (tmp_path / "Shared.btrc").write_text(SHARED_MODULE)
    program = tmp_path / "Main.btrc"
    program.write_text(MAIN_MODULE)
    for name, compiler in _compilers(semantic_btrcc).items():
        stdout = _build_and_run(compiler, program, tmp_path / name, layout)
        assert stdout == "5 4 abcd 4 xyz\n2 6 Table\n", name


SPLICED_LITERALS = """\
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main() {
	string s = "xy\\
zw";
	print(s);
	char t[6] = "ab\\
cd" "e";
	assert((int)sizeof(t) == 6 && (int)strlen(t) == 5);
	printf("%s\\n", t);
	return 0;
}
"""


@pytest.mark.parametrize("flags", [pytest.param((), id="plain"), pytest.param(("--debug",), id="debug")])
def test_line_splice_inside_a_literal_is_deleted(semantic_btrcc: Path, tmp_path: Path, flags: tuple[str, ...]) -> None:
    """F11: a backslash-newline in a literal is gone before the C is emitted."""
    program = tmp_path / "Spliced.btrc"
    program.write_text(SPLICED_LITERALS)
    for name, compiler in _compilers(semantic_btrcc).items():
        stdout = _build_and_run(compiler, program, tmp_path / name, None, flags)
        assert stdout == "xyzw\nabcde\n", name
