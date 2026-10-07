"""The selected target row's data model in both analyzers (Stage 24 commit 1c).

platform-target-contract.md §1.8: literal typing and the constant cast
ranges of ``long`` and ``unsigned long`` follow the row's ``sizeof_long``,
never the host or the C compiler that built btrcc. Every case runs through
both compilers for an LP64 row and the two LLP64 Windows rows, so the
answers differ by row whatever host runs the test.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from src.compiler.python import Compiler
from src.compiler.python.abi.generated import TARGET_ROWS
from src.compiler.python.analyzer.types import CIntegerWidths, NumericLiteralSemantics
from src.compiler.python.application.results import CompilerOptions

REPO = Path(__file__).resolve().parents[3]
TIMEOUT = 300
TARGETS = ("linux-x86_64", "windows-x86_64", "windows-aarch64-msvc")
ROWS = {row.label: row for row in TARGET_ROWS}

# 3000000000 is past a 32-bit long, so its type is the row's; 0xffffffffff
# skips both 32-bit long candidates; the UL suffix keeps unsigned long first.
TYPING = """\
int main() {
    var decimal = 3000000000;
    var hexadecimal = 0xffffffffff;
    var suffixed = 4294967296UL;
    return decimal > 0 && hexadecimal > 0 && suffixed > 0 ? 0 : 1;
}
"""
# A signed cast outside long's range is no constant (C11 6.3.1.3p3).
SIGNED_CAST = "enum Pick { CHOSEN = (long)3000000000 > 0 ? 2 : 3 };\nint main() { return CHOSEN; }\n"
# An unsigned cast reduces modulo long's width: 1 on a 32-bit long.
UNSIGNED_CAST = (
    "int pick(int value) {\n"
    "    switch (value) { case (unsigned long)4294967297 == 1 ? 1 : 3: return 1; case 1: return 2; }\n"
    "    return 0;\n"
    "}\n"
    "int main() { return pick(1); }\n"
)
# C11 6.3.1.3p3 makes narrowing a constant initializer implementation-defined,
# not an error, so neither compiler refuses it on any row; the C compiler
# narrows it for the target.
NARROWING = "int main() { long narrowed = 3000000000; return narrowed != 0 ? 0 : 1; }\n"
SIGNED_CAST_ERROR = "Enum value 'CHOSEN' requires an integral constant expression using only earlier members"
# btrcc's duplicate-case message omits the value; both share this prefix.
UNSIGNED_CAST_ERROR = "Duplicate switch case value"


def long_bits(target: str) -> int:
    return ROWS[target].sizeof_long * 8


def reference(tmp_path: Path, source: str, target: str):
    path = tmp_path / "Main.btrc"
    path.write_text(source)
    return Compiler().compile(source, str(path), CompilerOptions(include_stdlib=False, use_cache=False, target=target))


def reference_errors(result) -> list[str]:
    return [diagnostic.message for diagnostic in result.diagnostics if diagnostic.severity == "error"]


def selfhost(btrcc: Path, tmp_path: Path, source: str, target: str) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "Main.btrc"
    path.write_text(source)
    return subprocess.run(
        [str(btrcc), "--no-stdlib", "--no-cache", "--target", target, str(path)],
        cwd=tmp_path,
        env={**os.environ, "BTRC_HOME": str(REPO / "src")},
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


def declarations(c_source: str) -> list[str]:
    names = ("decimal", "hexadecimal", "suffixed")
    pattern = re.compile(rf"^\s*((?:unsigned )?long(?: long)?) ({'|'.join(names)}) = ")
    return [f"{match[1]} {match[2]}" for line in c_source.splitlines() if (match := pattern.match(line))]


def expected_declarations(target: str) -> list[str]:
    if long_bits(target) == 64:
        return ["long decimal", "long hexadecimal", "unsigned long suffixed"]
    return ["long long decimal", "long long hexadecimal", "unsigned long long suffixed"]


# -- The reference analyzer ---------------------------------------------------


@pytest.mark.parametrize("row", TARGET_ROWS, ids=lambda row: row.label)
def test_widths_follow_every_row(row) -> None:
    widths = CIntegerWidths.for_target(row)
    assert (widths.char, widths.short, widths.int_, widths.long_long) == (8, 16, 32, 64)
    assert widths.long == row.sizeof_long * 8
    expected = "long" if row.sizeof_long == 8 else "long long"
    assert NumericLiteralSemantics.for_target(row).integer_type("3000000000", 3000000000) == expected


@pytest.mark.parametrize("target", TARGETS)
def test_reference_literal_typing_follows_the_row(target: str, tmp_path: Path) -> None:
    result = reference(tmp_path, TYPING, target)
    assert result.successful, reference_errors(result)
    assert declarations(result.c_source) == expected_declarations(target)


@pytest.mark.parametrize("target", TARGETS)
def test_reference_cast_ranges_follow_the_row(target: str, tmp_path: Path) -> None:
    narrow = long_bits(target) == 32
    for source, error in ((SIGNED_CAST, SIGNED_CAST_ERROR), (UNSIGNED_CAST, UNSIGNED_CAST_ERROR)):
        result = reference(tmp_path, source, target)
        assert result.successful != narrow, reference_errors(result)
        assert [message.startswith(error) for message in reference_errors(result)] == ([True] if narrow else [])


@pytest.mark.parametrize("target", TARGETS)
def test_narrowing_initialization_compiles_in_both_compilers(
    target: str, immutable_btrcc: Path, tmp_path: Path
) -> None:
    result = reference(tmp_path, NARROWING, target)
    assert result.successful, reference_errors(result)
    compiled = selfhost(immutable_btrcc, tmp_path, NARROWING, target)
    assert compiled.returncode == 0, compiled.stderr
    for c_source in (result.c_source, compiled.stdout):
        assert "long narrowed = 3000000000;" in c_source


# -- Both compilers -------------------------------------------------------------


@pytest.mark.parametrize("target", TARGETS)
def test_selfhost_literal_typing_matches_the_reference(target: str, immutable_btrcc: Path, tmp_path: Path) -> None:
    result = selfhost(immutable_btrcc, tmp_path, TYPING, target)
    assert result.returncode == 0, result.stderr
    assert declarations(result.stdout) == expected_declarations(target)
    assert declarations(result.stdout) == declarations(reference(tmp_path, TYPING, target).c_source)


@pytest.mark.parametrize("target", TARGETS)
def test_selfhost_cast_ranges_match_the_reference(target: str, immutable_btrcc: Path, tmp_path: Path) -> None:
    narrow = long_bits(target) == 32
    for source, error in ((SIGNED_CAST, SIGNED_CAST_ERROR), (UNSIGNED_CAST, UNSIGNED_CAST_ERROR)):
        result = selfhost(immutable_btrcc, tmp_path, source, target)
        assert (result.returncode != 0) == narrow, result.stderr
        assert (error in result.stderr) == narrow, result.stderr
        reference_messages = reference_errors(reference(tmp_path, source, target))
        assert [message.startswith(error) for message in reference_messages] == ([True] if narrow else [])


def test_selfhost_long_ranges_come_from_the_row_not_limits_h() -> None:
    """btrcc's own <limits.h> describes its host; no analysis may read long's limits there."""

    for relative in ("syntax/Literals.btrc", "analyzer/validation/Constants.btrc"):
        text = (REPO / "src/compiler/btrc" / relative).read_text()
        assert re.search(r"\b(?:LONG_MIN|LONG_MAX|ULONG_MAX)\b", text) is None, relative
