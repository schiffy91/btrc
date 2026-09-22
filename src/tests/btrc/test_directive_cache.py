"""Cached source fragments keep scanner semantics and fail safely."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", params=["reference", "selfhost"])
def directive_driver(request, selfhost_driver, immutable_btrcc, tmp_path_factory):
    source = ROOT / "src/tests/btrc/fixtures/DirectiveCacheDriver.btrc"
    if request.param == "reference":
        return selfhost_driver(source, compile_flags=("-pedantic-errors",))
    directory = tmp_path_factory.mktemp("directive-driver")
    generated = directory / "Driver.c"
    binary = directory / "driver"
    result = subprocess.run(
        [str(immutable_btrcc), "--no-cache", str(source), "-o", str(generated)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
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
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize(
    "source,mode,expected",
    [
        ("import ./Helper.btrc;\nint main() { return 0; }\n", "warm", "import:1:1:./Helper.btrc\n"),
        ("import Library.{\n Math, Vector\n};\n", "warm", "import:1:3:Library.{Math,Vector}\n"),
        ('#include "Helper.btrc"\n#include <stdio.h>\n', "warm", "btrc_include:1:1:Helper.btrc\n"),
        ('// import ./Missing.btrc;\nstring text = "import ./Missing.btrc;";\n', "warm", ""),
        ("", "warm", ""),
        ("/* comment\n*/ import ./Helper.btrc;\n", "context", "import:2:2:./Helper.btrc\n"),
        ("import ./Helper.btrc; /* comment\n*/\n", "context", "import:1:1:./Helper.btrc\n"),
        ("import ./Helper.btrc;\n", "bad-range", "import:1:1:./Helper.btrc\n"),
        ("import ./Helper.btrc;\n", "grammar", "import:1:1:./Helper.btrc\n"),
        ("import ./Helper.btrc;\n", "grammar-keyword-replace", "import:1:1:./Helper.btrc\n"),
        ("import ./Helper.btrc;\n", "grammar-operator", "import:1:1:./Helper.btrc\n"),
        ("import ./Helper.btrc;\n", "grammar-operator-replace", "import:1:1:./Helper.btrc\n"),
        ("import ./Helper.btrc;\n", "grammar-annotation", "import:1:1:./Helper.btrc\n"),
        ("/*\nimport }\n*/\nimport ./Helper.btrc;\n", "bad-fragment", "import:4:4:./Helper.btrc\n"),
        ('import ./Helper.btrc;\n"unfinished', "malformed", ""),
    ],
)
def test_cached_fragments(directive_driver, tmp_path, source, mode, expected):
    program = tmp_path / "Input.btrc"
    program.write_text(source)
    result = subprocess.run(
        [str(directive_driver), str(ROOT / "src/language/grammar.ebnf"), str(program), mode],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    ending = "uncached lexical failure\n" if mode == "malformed" else f"loads=2 stores={1 if mode == 'warm' else 2}\n"
    assert result.stdout == expected + ending
