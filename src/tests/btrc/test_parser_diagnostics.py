"""End-to-end diagnostics for the self-hosted parser boundary."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))
DRIVER_SOURCES = {
    "parser": "src/compiler/btrc/tools/parse_main.btrc",
    "compiler": "src/compiler/btrc/btrcc_main.btrc",
}

pytestmark = pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        **kwargs,
    )


@pytest.fixture(scope="module")
def selfhost_drivers(tmp_path_factory) -> dict[str, Path]:
    """Build the real parser-stage and production self-host drivers."""
    output = tmp_path_factory.mktemp("selfhost-parser-diagnostics")
    cache = output / "cache"
    binaries: dict[str, Path] = {}
    for name, source in DRIVER_SOURCES.items():
        generated = output / f"{name}.c"
        binary = output / name
        transpile = _run(
            [
                "python3",
                "-m",
                "src.compiler.python.main",
                source,
                "--no-cache",
                "-o",
                str(generated),
            ],
            env={**os.environ, "BTRC_CACHE_DIR": str(cache)},
            timeout=300,
        )
        assert transpile.returncode == 0 and generated.exists(), (
            f"failed to transpile {source}:\n{transpile.stderr[:3000]}"
        )
        compile_result = _run(
            [
                *CC,
                "-std=c11",
                "-pedantic-errors",
                str(generated),
                "-o",
                str(binary),
                "-lm",
                "-lpthread",
            ],
            timeout=300,
        )
        assert compile_result.returncode == 0 and binary.exists(), (
            f"failed to compile {source}:\n{compile_result.stderr[:3000]}"
        )
        binaries[name] = binary
    return binaries


INVALID_PROGRAMS = [
    (
        "long long double invalid() { return 0; }",
        "error: Expected IDENT, got DOUBLE 'double' at 1:11\n",
    ),
    (
        "int grid[2][3];",
        "error: Expected one array dimension (AST/IR cannot represent another), got LBRACKET '[' at 1:12\n",
    ),
    (
        "class Box<T { public T value; }",
        "error: Expected '>', got LBRACE '{' at 1:13\n",
    ),
    (
        "int main() { return 0;",
        "error: Expected RBRACE, got EOF '' at 1:23\n",
    ),
    (
        'int main() { var s = f"{(1 + 2}"; return 0; }',
        "error: Expected RPAREN, got SEMICOLON ';' at 1:7\n",
    ),
    (
        'int main() { var s = f"{1 2}"; return 0; }',
        "error: Expected SEMICOLON, got INT_LIT '2' at 1:3\n",
    ),
    (
        "int main() { var value = 18446744073709551616ULL; }",
        "error: Invalid integer literal '18446744073709551616ULL' at 1:26\n",
    ),
    (
        "int main() { var value = 1e309; }",
        "error: Floating literal '1e309' is outside the finite double range at 1:26\n",
    ),
    (
        "int main() { var value = 1e-9999; }",
        "error: Floating literal '1e-9999' underflows to zero at 1:26\n",
    ),
    (
        "int main() { var value = 1e39f; }",
        "error: Floating literal '1e39f' is outside the finite float range at 1:26\n",
    ),
    (
        "int main() { var value = 1e-50f; }",
        "error: Floating literal '1e-50f' underflows to zero as float at 1:26\n",
    ),
]


@pytest.mark.parametrize("driver", DRIVER_SOURCES)
@pytest.mark.parametrize("source, expected", INVALID_PROGRAMS)
def test_invalid_program_stops_at_parser_boundary(
    selfhost_drivers: dict[str, Path],
    tmp_path: Path,
    driver: str,
    source: str,
    expected: str,
) -> None:
    program = tmp_path / "invalid.btrc"
    program.write_text(source)
    command = [str(selfhost_drivers[driver])]
    if driver == "compiler":
        command.append("--no-stdlib")
    result = _run([*command, str(program)], timeout=15)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == expected
    assert str(program) not in result.stderr


def test_valid_program_still_crosses_both_boundaries(selfhost_drivers: dict[str, Path], tmp_path: Path) -> None:
    program = tmp_path / "valid.btrc"
    program.write_text("class Box<T> { public T value; }\nint values[2];\nint main() { return 0; }\n")

    parsed = _run([str(selfhost_drivers["parser"]), str(program)], timeout=15)
    assert parsed.returncode == 0 and parsed.stderr == ""
    reference = _run(
        [
            "python3",
            "-m",
            "tools.compiler_codegen.main",
            "verify-ast",
            str(program),
        ],
        timeout=15,
    )
    assert reference.returncode == 0 and reference.stderr == ""
    assert parsed.stdout == reference.stdout

    compiled = _run(
        [str(selfhost_drivers["compiler"]), "--no-stdlib", str(program)],
        timeout=30,
    )
    assert compiled.returncode == 0 and compiled.stderr == ""
    assert "int main(void)" in compiled.stdout

    generated = tmp_path / "valid.c"
    binary = tmp_path / "valid"
    generated.write_text(compiled.stdout)
    c_result = _run(
        [*CC, "-std=c11", "-pedantic-errors", str(generated), "-o", str(binary), "-lm"],
        timeout=30,
    )
    assert c_result.returncode == 0, c_result.stderr
    run_result = _run([str(binary)], timeout=15)
    assert run_result.returncode == 0


@pytest.mark.skipif(not Path("/dev/full").exists(), reason="requires /dev/full")
def test_parser_driver_reports_stdout_failure(
    selfhost_drivers: dict[str, Path],
    tmp_path: Path,
) -> None:
    program = tmp_path / "valid.btrc"
    program.write_text("int main() { return 0; }\n")

    with Path("/dev/full").open("wb", buffering=0) as sink:
        result = subprocess.run(
            [str(selfhost_drivers["parser"]), str(program)],
            cwd=REPO,
            stdout=sink,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )

    assert result.returncode != 0
    assert "cannot write standard output" in result.stderr


INVALID_PREPROCESSOR_DIRECTIVES = [
    (
        "#ifdef FEATURE\nint main() { return 0; }\n",
        "error: unsupported preprocessor directive '#ifdef'\n",
    ),
    (
        "#include <stdio.h\nint main() { return 0; }\n",
        "error: malformed #include directive: #include <stdio.h\n",
    ),
    (
        "#define DUP(value, value) value\nint main() { return 0; }\n",
        "error: duplicate function-like macro parameter: #define DUP(value, value) value\n",
    ),
    (
        "#pragma once\nint main() { return 0; }\n",
        "error: unsupported #pragma directive: #pragma once\n",
    ),
    (
        "#define CONT(value) \\\nint main() { return 0; }\n",
        "error: multi-line preprocessor directives are unsupported\n",
    ),
]


@pytest.mark.parametrize("source, expected", INVALID_PREPROCESSOR_DIRECTIVES)
def test_invalid_preprocessor_directives_fail_before_c_emission(
    selfhost_drivers: dict[str, Path],
    tmp_path: Path,
    source: str,
    expected: str,
) -> None:
    program = tmp_path / "invalid_preprocessor.btrc"
    program.write_text(source)

    result = _run(
        [str(selfhost_drivers["compiler"]), "--no-stdlib", str(program)],
        timeout=15,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == expected


def test_structured_preprocessor_declarations_preserve_kind_and_order(
    selfhost_drivers: dict[str, Path],
    tmp_path: Path,
) -> None:
    program = tmp_path / "valid_preprocessor.btrc"
    program.write_text(
        '#include "project/header.h"\n'
        "#include <system/header.h>\n"
        "#define OBJECT 7\n"
        "#define CALL(left, right) ((left) + (right))\n"
        "int main() { return 0; }\n"
    )

    result = _run(
        [str(selfhost_drivers["compiler"]), "--no-stdlib", str(program)],
        timeout=15,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    declarations = [
        '#include "project/header.h"',
        "#include <system/header.h>",
        "#define OBJECT 7",
        "#define CALL(left, right) ((left) + (right))",
    ]
    positions = [result.stdout.index(declaration) for declaration in declarations]
    assert positions == sorted(positions)


def test_string_literal_does_not_root_same_named_function(
    selfhost_drivers: dict[str, Path],
    tmp_path: Path,
) -> None:
    program = tmp_path / "literal_reachability.btrc"
    program.write_text('int dead_target() { return 7; }\nint main() { print("dead_target"); return 0; }\n')

    result = _run(
        [str(selfhost_drivers["compiler"]), "--no-stdlib", str(program)],
        timeout=15,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert '"dead_target"' in result.stdout
    assert "int dead_target(void)" not in result.stdout


def test_macro_replacement_rejects_language_callable_alias(
    selfhost_drivers: dict[str, Path],
    tmp_path: Path,
) -> None:
    program = tmp_path / "macro_reachability.btrc"
    program.write_text(
        "#define CALL_TARGET retained_target\n"
        "int retained_target() { return 9; }\n"
        "int main() { return CALL_TARGET() == 9 ? 0 : 1; }\n"
    )

    result = _run(
        [str(selfhost_drivers["compiler"]), "--no-stdlib", str(program)],
        timeout=15,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "error: Language callable 'retained_target' requires semantic call "
        "analysis and cannot be referenced from macro replacement "
        "'CALL_TARGET' at 1:1\n"
    )
