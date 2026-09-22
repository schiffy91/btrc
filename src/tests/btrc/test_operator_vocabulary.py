"""Operator recognition follows the supplied vocabulary and source boundaries."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.syntax.grammar import GrammarRepository

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", params=["reference", "selfhost"])
def vocabulary_driver(request, selfhost_driver, immutable_btrcc: Path, tmp_path_factory) -> Path:
    source = REPO / "src/tests/btrc/fixtures/OperatorVocabularyDriver.btrc"
    if request.param == "reference":
        return selfhost_driver(source, compile_flags=("-pedantic-errors",))
    directory = tmp_path_factory.mktemp("operator-vocabulary")
    generated = directory / "Driver.c"
    binary = directory / "driver"
    transpile = subprocess.run(
        [str(immutable_btrcc), "--no-cache", str(source), "-o", str(generated)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert transpile.returncode == 0, transpile.stderr
    built = subprocess.run(
        [
            *shlex.split(os.environ.get("BTRC_CC", "cc")),
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
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
    assert built.returncode == 0, built.stderr
    return binary


def run_vocabulary(driver: Path, grammar: Path, source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(driver), str(grammar), str(source)], cwd=REPO, capture_output=True, text=True, timeout=30
    )


def test_every_operator_and_adjacent_pair_match_reference(vocabulary_driver: Path, tmp_path: Path) -> None:
    operators = GrammarRepository.canonical().load().operators
    # Comments have their own lexical priority; the diagnostic corpus covers
    # unterminated comments. Keep these pairs entirely in operator recognition.
    pairs = [left + right for left in operators for right in operators if "/*" not in left + right]
    source = tmp_path / "operators.btrc"
    source.write_text("\n".join([*operators, *pairs]))
    result = run_vocabulary(vocabulary_driver, REPO / "src/language/grammar.ebnf", source)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    expected = "".join(f"{token!r}\n" for token in Lexer(source.read_text(), str(source)).tokenize())
    assert result.stdout == expected


@pytest.mark.parametrize(
    "operators, source, values",
    [
        (["+", "+=", "+==", "+==>"], "+==>+==+=+", ["+==>", "+==", "+=", "+"]),
        ([">", ">>>>", ">>"], ">>>>>>>", [">>>>", ">>", ">"]),
        (["+==>", "+", "="], "+==+", ["+", "=", "=", "+"]),
        (["%:%:%:%", "%"], "%:%:%:%%", ["%:%:%:%", "%"]),
        (["é", "éé"], "ééé", ["éé", "é"]),
    ],
)
def test_runtime_grammar_controls_longest_match(
    vocabulary_driver: Path, tmp_path: Path, operators: list[str], source: str, values: list[str]
) -> None:
    grammar = tmp_path / "grammar.ebnf"
    grammar.write_text("@lexical { @operators { " + " ".join(f'"{op}"' for op in operators) + " } }")
    program = tmp_path / "custom.btrc"
    program.write_text(source)
    result = run_vocabulary(vocabulary_driver, grammar, program)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    column = 1
    assert len(lines) == len(values) + 1
    for line, value in zip(lines[:-1], values, strict=True):
        assert f", {value!r}, 1:{column})" in line
        column += len(value.encode("utf-8"))
    assert lines[-1] == f"Token(EOF, '', 1:{column})"


@pytest.mark.parametrize("operators, source, column", [([], "+", 1), (["+"], "++=", 3)])
def test_missing_operator_keeps_original_diagnostic(
    vocabulary_driver: Path, tmp_path: Path, operators: list[str], source: str, column: int
) -> None:
    grammar = tmp_path / "grammar.ebnf"
    grammar.write_text("@lexical { @operators { " + " ".join(f'"{op}"' for op in operators) + " } }")
    program = tmp_path / "missing.btrc"
    program.write_text(source)
    result = run_vocabulary(vocabulary_driver, grammar, program)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"error: Unexpected character '{source[column - 1]}' at 1:{column}\n"


def test_vocabulary_updates_keep_priority_and_isolation(vocabulary_driver: Path) -> None:
    result = subprocess.run([str(vocabulary_driver)], cwd=REPO, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "PASS: mutable vocabulary preserves priority and isolation\n"
