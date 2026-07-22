"""Portable numeric inference, conversion, and strict-C emission contracts."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.numeric_literals import integer_literal_type
from src.compiler.python.parser.core import ParseError
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _analyze(source: str):
    program = Parser(Lexer(source, "<numeric-contract>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def _errors(source: str) -> str:
    return "\n".join(_analyze(source).errors)


def _strict_build_and_run(
    c_source: str,
    tmp_path: Path,
    compiler: str,
) -> None:
    source = tmp_path / f"numeric-{Path(compiler).name}.c"
    executable = source.with_suffix("")
    source.write_text(c_source)
    result = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    subprocess.run([str(executable)], check=True, timeout=10)


def test_float_suffix_and_sizeof_control_inferred_c_types():
    c_source = emit_c("""
        int main() {
            var wide = 1.0;
            var narrow = 1.0f;
            var amount = sizeof(int);
            return wide == narrow && amount == sizeof(int) ? 0 : 1;
        }
    """)

    assert "double wide = 1.0;" in c_source
    assert "float narrow = 1.0f;" in c_source
    assert "size_t amount = sizeof(int);" in c_source


@pytest.mark.parametrize(
    "typedef_name",
    ("int_fast16_t", "size_t", "intmax_t", "intptr_t", "tcflag_t"),
)
def test_abi_dependent_integer_typedef_mixes_require_explicit_cast(
    typedef_name: str,
):
    errors = _errors(f"int main() {{ {typedef_name} value = 1; return value + 1; }}")
    assert "mixes ABI-dependent integer type" in errors
    assert "cast explicitly" in errors


@pytest.mark.parametrize(
    "body",
    (
        "size_t value = 1; value += 1; return 0;",
        "size_t value = 1; var out = true ? value : 1; return 0;",
        "size_t value = 1; return value < 2 ? 0 : 1;",
    ),
)
def test_abi_dependent_mix_is_rejected_in_every_conversion_context(body: str):
    assert "mixes ABI-dependent integer type" in _errors(f"int main() {{ {body} }}")


def test_same_abi_typedef_explicit_cast_and_floating_mix_remain_valid():
    analyzed = _analyze("""
        int main() {
            size_t first = 20;
            size_t second = 22;
            size_t same = first + second;
            size_t expected = 42;
            long widened = (long)first + 22;
            double floating = first + 2.0;
            return same == expected && widened == 42
                && floating == 22.0 ? 0 : 1;
        }
    """)

    assert analyzed.errors == []


def test_fixed_and_least_width_typedef_mix_is_deterministic():
    analyzed = _analyze("""
        int main() {
            int32_t exact = 20;
            uint_least16_t least = 22;
            long long result = exact + least;
            return result == 42 ? 0 : 1;
        }
    """)

    assert analyzed.errors == []


def test_integer_literal_inference_uses_value_radix_and_suffix():
    decimal = integer_literal_type("2147483648", 2147483648)
    c_source = emit_c("""
        int main() {
            var decimal = 2147483648;
            var hexadecimal = 0xffffffff;
            var explicitLongLong = 1LL;
            var explicitUnsigned = 1U;
            return decimal > 0 && hexadecimal > 0
                && explicitLongLong == 1 && explicitUnsigned == 1 ? 0 : 1;
        }
    """)

    assert f"{decimal} decimal = 2147483648;" in c_source
    assert "unsigned int hexadecimal = 0xffffffff;" in c_source
    assert "long long explicitLongLong = 1LL;" in c_source
    assert "unsigned int explicitUnsigned = 1U;" in c_source


def test_integer_literal_outside_all_suffix_candidates_is_rejected():
    with pytest.raises(ParseError, match="Invalid integer literal"):
        Parser(
            Lexer(
                "int main() { var value = 18446744073709551616ULL; }",
                "<integer-range>",
            ).tokenize()
        ).parse()


@pytest.mark.parametrize(
    ("literal", "fragment"),
    (
        ("1e309", "finite double range"),
        ("1e-9999", "underflows to zero"),
        ("1e39f", "finite float range"),
        ("1e-50f", "underflows to zero as float"),
    ),
)
def test_nonrepresentable_floating_literals_are_rejected(
    literal: str,
    fragment: str,
):
    with pytest.raises(ParseError, match=fragment):
        Parser(Lexer(f"int main() {{ var value = {literal}; }}", "<float-range>").tokenize()).parse()


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_constant_casts_and_greedy_hex_character_values_compile_strictly(
    tmp_path: Path,
    c_compiler: str,
):
    c_source = emit_c(r"""
        enum Values {
            Wrapped = (unsigned char)300,
            AfterWrapped,
            Truncated = (int)3.2,
            AfterTruncated,
            HexCharacter = '\x000041',
            AfterHexCharacter
        };
        int main() {
            return Wrapped == 44 && AfterWrapped == 45
                && Truncated == 3 && AfterTruncated == 4
                && HexCharacter == 65 && AfterHexCharacter == 66 ? 0 : 1;
        }
    """)

    _strict_build_and_run(c_source, tmp_path, c_compiler)


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_numeric_inference_program_compiles_strictly(
    tmp_path: Path,
    c_compiler: str,
):
    c_source = emit_c("""
        int main() {
            var wide = 1.0;
            var narrow = 1.0f;
            var amount = sizeof(int);
            int32_t exact = 20;
            uint_least16_t least = 22;
            long long result = exact + least;
            return wide == narrow && amount == sizeof(int)
                && result == 42 ? 0 : 1;
        }
    """)

    _strict_build_and_run(c_source, tmp_path, c_compiler)
