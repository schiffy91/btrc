"""Fail-closed diagnostics at every self-hosted lexer boundary."""

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
    "lexer": "src/compiler/btrc/lex_main.btrc",
    "parser": "src/compiler/btrc/parse_main.btrc",
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
def lexer_boundary_drivers(tmp_path_factory) -> dict[str, Path]:
    """Build the lex-only, parse, and production self-hosted drivers."""
    output = tmp_path_factory.mktemp("selfhost-lexer-diagnostics")
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


INVALID_INPUTS = [
    ("/* open", "Unterminated block comment at 1:1"),
    ('"open', "Unterminated string literal at 1:1"),
    ('"line\n"', "Unterminated string literal at 1:1"),
    ('"raw\rcarriage"', "Unterminated string literal at 1:1"),
    (r'"\q"', r"Invalid escape sequence '\q' in string literal at 1:1"),
    (r'"\8"', r"Invalid escape sequence '\8' in string literal at 1:1"),
    ('"\\é"', "Invalid non-ASCII escape in string literal at 1:1"),
    (r'"\x"', "Hex escape sequence requires digits in string literal at 1:1"),
    (r'"\x100"', "Hex escape sequence out of range in string literal at 1:1"),
    (r'"\400"', "Octal escape sequence out of range in string literal at 1:1"),
    (r'"\u123"', "Invalid universal character escape in string literal at 1:1"),
    (r'"\u0041"', "Invalid universal character escape in string literal at 1:1"),
    (r'"\ud800"', "Invalid universal character escape in string literal at 1:1"),
    (r'"\U00110000"', "Invalid universal character escape in string literal at 1:1"),
    ('"""open', "Unterminated triple-quoted string at 1:1"),
    (r'"""\q"""', r"Invalid escape sequence '\q' in string literal at 1:1"),
    ("'open", "Unterminated character literal at 1:1"),
    ("''", "Character literal must contain exactly one character at 1:1"),
    ("'ab'", "Character literal must contain exactly one character at 1:1"),
    ("'é'", "Character literal must contain exactly one character at 1:1"),
    ("'\\e'", "Character literal must contain exactly one character at 1:1"),
    ("'\\400'", "Character literal must contain exactly one character at 1:1"),
    ("'\\x123'", "Character literal must contain exactly one character at 1:1"),
    ("'\\u0041'", "Character literal must contain exactly one character at 1:1"),
    ("'a\nb'", "Unterminated character literal at 1:1"),
    ('f"open', "Unterminated f-string literal at 1:1"),
    ('f"line\n"', "Unterminated f-string literal at 1:1"),
    ('f"raw\rcarriage"', "Unterminated f-string literal at 1:1"),
    (r'f"\q"', r"Invalid escape sequence '\q' in f-string literal at 1:1"),
    ("@mystery", "Unknown annotation '@mystery' at 1:1"),
    ("$", "Unexpected character '$' at 1:1"),
    ("é", "Unexpected non-ASCII character at 1:1"),
    ("nameé", "Unexpected non-ASCII character at 1:5"),
    ("1é", "Unexpected non-ASCII character at 1:2"),
    ("@é", "Unknown annotation '@' at 1:1"),
    ("0x", "Invalid hex literal: no digits after '0x' at 1:1"),
    ("0b", "Invalid binary literal: no digits after '0b' at 1:1"),
    ("0o", "Invalid octal literal: no digits after '0o' at 1:1"),
    ("1e+", "Invalid float literal: no digits in exponent at 1:1"),
    ("123abc", "Invalid numeric literal '123abc' at 1:1"),
    ("0x1g", "Invalid numeric literal '0x1g' at 1:1"),
    ("0x1p2", "Invalid numeric literal '0x1p2' at 1:1"),
    ("0b102", "Invalid digit '2' in binary literal at 1:1"),
    ("0o78", "Invalid digit '8' in octal literal at 1:1"),
    ("09", "Invalid digit '9' in octal literal at 1:1"),
    ("1uu", "Invalid integer suffix 'uu' at 1:1"),
    ("1lll", "Invalid integer suffix 'lll' at 1:1"),
    ("1lL", "Invalid integer suffix 'lL' at 1:1"),
    ("1f", "Invalid numeric literal '1f' at 1:1"),
    ("1.0ff", "Invalid numeric literal '1.0ff' at 1:1"),
    ("1e2L", "Invalid numeric literal '1e2L' at 1:1"),
]


@pytest.mark.parametrize("source, diagnostic", INVALID_INPUTS)
def test_reference_lexer_matches_diagnostic_contract(
    source: str,
    diagnostic: str,
) -> None:
    from src.compiler.python.lexer import Lexer, LexerError

    with pytest.raises(LexerError) as exc:
        Lexer(source, "<diagnostic>").tokenize()

    assert str(exc.value) == diagnostic


@pytest.mark.parametrize("driver", DRIVER_SOURCES)
@pytest.mark.parametrize("source, diagnostic", INVALID_INPUTS)
def test_invalid_input_fails_closed_at_every_driver(
    lexer_boundary_drivers: dict[str, Path],
    tmp_path: Path,
    driver: str,
    source: str,
    diagnostic: str,
) -> None:
    program = tmp_path / "invalid.btrc"
    program.write_text(source)
    command = [str(lexer_boundary_drivers[driver])]
    if driver == "compiler":
        command.append("--no-stdlib")

    result = _run([*command, str(program)], timeout=15)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"error: {diagnostic}\n"
    assert str(program) not in result.stderr


def test_fstring_interpolation_lexing_is_deferred_to_the_parser(
    lexer_boundary_drivers: dict[str, Path],
    tmp_path: Path,
) -> None:
    program = tmp_path / "invalid_interpolation.btrc"
    program.write_text('int main() { string s = f"{$}"; return 0; }')

    result = _run(
        [str(lexer_boundary_drivers["lexer"]), str(program)],
        timeout=15,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "Token(FSTRING_LIT, '{$}'" in result.stdout


@pytest.mark.parametrize("driver", ["parser", "compiler"])
def test_invalid_fstring_interpolation_propagates_sublexer_failure(
    lexer_boundary_drivers: dict[str, Path],
    tmp_path: Path,
    driver: str,
) -> None:
    program = tmp_path / "invalid_interpolation.btrc"
    program.write_text('int main() { string s = f"{$}"; return 0; }')
    command = [str(lexer_boundary_drivers[driver])]
    if driver == "compiler":
        command.append("--no-stdlib")

    result = _run([*command, str(program)], timeout=15)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "error: Unexpected character '$' at 1:1\n"


def test_valid_literal_tokens_remain_reference_identical(
    lexer_boundary_drivers: dict[str, Path],
    tmp_path: Path,
) -> None:
    program = tmp_path / "valid_literals.btrc"
    program.write_text(
        "int main() {\n"
        "  int h = 0x1fULL; int b = 0b10; int o = 0o7;\n"
        "  unsigned long long wide = 42LLu; double d = 1.5e+2F;\n"
        "  string s = \"\\377\\x000ff\\u0024\\u03a9\"; char c = '\\n';\n"
        "  char greedy = '\\x000041';\n"
        '  string splice = "left\\\nright"; string escaped = f"\\t\\u03a9";\n'
        '  string t = """line\ntext"""; string f = f"{h}";\n'
        "  return 0;\n"
        "}\n"
    )

    selfhost = _run(
        [str(lexer_boundary_drivers["lexer"]), str(program)],
        timeout=15,
    )
    reference = _run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(program),
            "--emit-tokens",
            "--no-stdlib",
        ],
        timeout=30,
    )

    assert selfhost.returncode == reference.returncode == 0
    assert selfhost.stderr == reference.stderr == ""
    assert selfhost.stdout == reference.stdout


def test_selfhost_successful_lexer_reuse_is_idempotent(tmp_path: Path) -> None:
    source = REPO / "src/tests/btrc/fixtures/lexer_reuse_driver.btrc"
    generated = tmp_path / "lexer_reuse.c"
    binary = tmp_path / "lexer_reuse"
    transpile = _run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(source),
            "--no-cache",
            "-o",
            str(generated),
        ],
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")},
        timeout=300,
    )
    assert transpile.returncode == 0 and generated.exists(), transpile.stderr
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
    assert compile_result.returncode == 0 and binary.exists(), compile_result.stderr

    result = _run([str(binary)], timeout=15)

    assert result.returncode == 0
    assert result.stdout == "PASS: lexer reuse is idempotent\n"
    assert result.stderr == ""
