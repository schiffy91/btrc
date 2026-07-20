"""Portable numeric contracts of the self-hosted compiler."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.compiler.python.numeric_literals import integer_literal_type
from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


@pytest.mark.parametrize(
    "typedef_name",
    ["int_fast16_t", "size_t", "intmax_t", "pid_t"],
)
def test_abi_dependent_integer_typedef_mixes_require_explicit_cast(
    semantic_btrcc: Path,
    tmp_path: Path,
    typedef_name: str,
) -> None:
    source = f"int main() {{ {typedef_name} value = 1; return value + 1 == 2 ? 0 : 1; }}"
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert "mixes ABI-dependent integer type" in result.stderr
    assert "cast explicitly" in result.stderr


def test_same_abi_typedef_and_explicit_cast_compile_strictly(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
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
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    _strict_build_and_run(generated, tmp_path / "abi-numeric")


def test_fixed_and_least_width_typedef_mixes_are_deterministic(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        int main() {
            int32_t exact = 20;
            uint_least16_t least = 22;
            long long result = exact + least;
            return result == 42 ? 0 : 1;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    _strict_build_and_run(generated, tmp_path / "portable-numeric")


@pytest.mark.parametrize(
    "body",
    [
        "size_t value = 1; value += 1; return 0;",
        "size_t value = 1; var out = true ? value : 1; return 0;",
    ],
)
def test_abi_dependent_compound_and_ternary_mixes_are_rejected(semantic_btrcc: Path, tmp_path: Path, body: str) -> None:
    result, _ = _compile_source(semantic_btrcc, tmp_path, f"int main() {{ {body} }}")
    assert result.returncode == 1
    assert "mixes ABI-dependent integer type" in result.stderr


def test_float_literal_suffix_controls_inferred_c_type(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        int main() {
            var wide = 1.0;
            var narrow = 1.0f;
            return wide == narrow ? 0 : 1;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert "double wide = 1.0;" in emitted
    assert "float narrow = 1.0f;" in emitted
    _strict_build_and_run(generated, tmp_path / "float-literals")


def test_sizeof_infers_its_strict_c_size_type(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = "int main() { var amount = sizeof(int); return amount == sizeof(int) ? 0 : 1; }"
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    assert "size_t amount = sizeof(int);" in generated.read_text()
    _strict_build_and_run(generated, tmp_path / "sizeof-type")


def test_integer_literal_inference_uses_c_candidate_order(semantic_btrcc: Path, tmp_path: Path) -> None:
    decimal_type = integer_literal_type("2147483648", 2147483648)
    source = """
        int main() {
            var decimal = 2147483648;
            var hexadecimal = 0xffffffff;
            var explicitLongLong = 1LL;
            var explicitUnsigned = 1U;
            return decimal > 0 && hexadecimal > 0
                && explicitLongLong == 1 && explicitUnsigned == 1 ? 0 : 1;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert f"{decimal_type} decimal = 2147483648;" in emitted
    assert "unsigned int hexadecimal = 0xffffffff;" in emitted
    assert "long long explicitLongLong = 1LL;" in emitted
    assert "unsigned int explicitUnsigned = 1U;" in emitted
    _strict_build_and_run(generated, tmp_path / "integer-candidates")


def test_integer_literal_outside_all_c_candidates_is_rejected(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = "int main() { var value = 18446744073709551616ULL; return 0; }"
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Invalid integer literal '18446744073709551616ULL'" in result.stderr


@pytest.mark.parametrize(
    ("literal", "diagnostic"),
    (
        ("1e309", "outside the finite double range"),
        ("1e-9999", "underflows to zero"),
        ("1e39f", "outside the finite float range"),
        ("1e-50f", "underflows to zero as float"),
    ),
)
def test_nonrepresentable_float_literal_is_rejected_before_emission(
    semantic_btrcc: Path,
    tmp_path: Path,
    literal: str,
    diagnostic: str,
) -> None:
    result, _ = _compile_source(
        semantic_btrcc,
        tmp_path,
        f"int main() {{ var value = {literal}; return 0; }}",
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert diagnostic in result.stderr


def test_integral_ice_casts_and_greedy_hex_character_values(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = r"""
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
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    _strict_build_and_run(generated, tmp_path / "numeric-ice-casts")
