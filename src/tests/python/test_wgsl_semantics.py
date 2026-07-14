"""Semantic contracts at the analyzed-AST to WGSL boundary."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_gpu_dispatch_failures import COMPILERS, _compile_with_gpu_stubs


def _analyze(source: str):
    program = Parser(Lexer(source, "<wgsl-semantics>").tokenize()).parse()
    return Analyzer().analyze(program)


def _errors(source: str) -> list[str]:
    return _analyze(source).errors


def _shader(source: str) -> str:
    analyzed = _analyze(source)
    assert not analyzed.errors
    [kernel] = IRGenerator(analyzed).generate().gpu_kernels
    return kernel.wgsl_source


def _has(errors: list[str], text: str) -> bool:
    return any(text.lower() in error.lower() for error in errors)


def test_ternary_lowers_to_conditional_control_flow_not_eager_select() -> None:
    shader = _shader(
        "@gpu float[] choose(float[] xs, float[] ys, bool first) { "
        "int i = gpu_id(); return first ? xs[i] : ys[i]; } "
        "int main() { return 0; }"
    )

    assert "if ((uniforms." in shader
    assert "var btrc_e_0: f32;" in shader
    assert shader.index("if ((uniforms.") < shader.index("btrc_e_0 = btrc_p_0")


def test_ternary_in_for_update_stays_inside_continuing_block() -> None:
    shader = _shader(
        "@gpu void step(int[] xs, bool fast) { int i = gpu_id(); "
        "for (int j = 0; j < 4; j = fast ? j + 2 : j + 1) { xs[i] += j; } } "
        "int main() { return 0; }"
    )

    continuing = shader.index("continuing {")
    branch = shader.index("if ((uniforms.", continuing)
    update = shader.index("btrc_v_1 = btrc_e_", branch)
    assert continuing < branch < update


def test_prefix_update_is_normalized_only_when_value_is_discarded() -> None:
    shader = _shader("@gpu void bump(int[] xs) { int i = gpu_id(); ++i; xs[i]--; } int main() { return 0; }")
    assert "++btrc_" not in shader
    assert "btrc_v_0++;" in shader
    assert "]--;" in shader

    float_shader = _shader("@gpu void bump(float[] xs) { int i = gpu_id(); ++xs[i]; } int main() { return 0; }")
    assert "] += 1.0;" in float_shader

    errors = _errors(
        "@gpu void bad(int[] xs) { int i = gpu_id(); int old = i++; xs[0] = old; } int main() { return 0; }"
    )
    assert _has(errors, "only supported as a standalone update statement")


def test_assignment_is_rejected_in_value_context() -> None:
    errors = _errors(
        "@gpu void bad(int[] xs) { int i = gpu_id(); int value = (i = 3); xs[0] = value; } int main() { return 0; }"
    )
    assert _has(errors, "assignment is only supported as a standalone update statement")


def test_mixed_numeric_arithmetic_and_shift_counts_are_explicitly_converted() -> None:
    shader = _shader(
        "@gpu float[] mixed(float[] xs, int[] weights, int shift) { "
        "int i = gpu_id(); int scaled = weights[i] << shift; return xs[i] * scaled; } "
        "int main() { return 0; }"
    )
    assert "<< u32(uniforms." in shader
    assert "f32(btrc_v_" in shader


def test_bool_numeric_casts_spell_out_source_semantics() -> None:
    shader = _shader(
        "@gpu int[] flags(float[] xs) { int i = gpu_id(); bool set = (bool)xs[i]; "
        "return (int)set; } int main() { return 0; }"
    )
    assert "!= 0.0" in shader
    assert "select(0, 1," in shader


def test_bool_xor_and_unary_domains_match_wgsl() -> None:
    shader = _shader(
        "@gpu int[] flags(int[] xs, bool left, bool right) { int i = gpu_id(); "
        "if (left ^ right) { return xs[i]; } return 0; } int main() { return 0; }"
    )
    assert " != " in shader
    assert " ^ " not in shader
    assert _has(
        _errors("@gpu void bad(int[] xs) { bool value = ~true; } int main(){return 0;}"),
        "bitwise-not operand must be int",
    )
    assert _has(
        _errors("@gpu void bad(int[] xs) { bool value = !1; } int main(){return 0;}"),
        "logical-not operand must be bool",
    )


@pytest.mark.parametrize(
    ("body", "diagnostic"),
    [
        ("float x = 4.0; x %= 2.0;", "remainder assignment target must be int"),
        (
            "bool x = true; x /= false;",
            "arithmetic compound-assignment operand must be float or int",
        ),
        (
            "float x = 1.0; x &= 1.0;",
            "bitwise compound-assignment operand must be bool or int",
        ),
        ("float x = 1.0; x <<= 1;", "shift assignment target must be int"),
        (
            "int x = 1; x += 1.0;",
            "compound assignment operands must have the same gpu scalar type",
        ),
    ],
)
def test_invalid_compound_operator_types_fail_during_analysis(
    body: str,
    diagnostic: str,
) -> None:
    assert _has(
        _errors(f"@gpu void bad(int[] xs) {{ {body} }} int main() {{ return 0; }}"),
        diagnostic,
    )


_ALL_COMPOUND_OPERATORS_SOURCE = (
    "@gpu void compound(int[] xs, int shift, bool right) { int i = gpu_id(); "
    "xs[i] += 1; xs[i] -= 1; xs[i] *= 2; xs[i] /= 2; xs[i] %= 3; "
    "xs[i] &= 7; xs[i] |= 1; xs[i] ^= 2; xs[i] <<= shift; xs[i] >>= shift; "
    "bool flag = true; flag &= right; flag |= right; flag ^= right; "
    "if (flag) { xs[i] += 1; } } int main() { return 0; }"
)


def test_all_compound_operators_have_typed_wgsl_lowering() -> None:
    shader = _shader(_ALL_COMPOUND_OPERATORS_SOURCE)

    assert "<<= u32(" in shader
    assert ">>= u32(" in shader
    assert shader.count("^=") == 1  # integer xor only
    assert re.search(r"(btrc_v_\d+) = \(\1 != \(uniforms\.", shader)


@pytest.mark.parametrize(
    ("body", "diagnostic"),
    [
        ("float x = sqrt(1);", "requires float arguments"),
        ("float x = max(1.0, 2);", "same gpu scalar type"),
        ("float x = pow(1.0);", "expects 2 argument"),
        ("int x = 2147483648;", "outside the wgsl i32 range"),
        ("float x = 1e100;", "outside the wgsl f32 range"),
        ("float x = 1e-50;", "outside the wgsl f32 range"),
        ("int[] local;", "array types not allowed"),
    ],
)
def test_invalid_wgsl_scalar_contracts_fail_during_analysis(body: str, diagnostic: str) -> None:
    errors = _errors(f"@gpu void bad(int[] xs) {{ {body} }} int main() {{ return 0; }}")
    assert _has(errors, diagnostic)


def test_user_function_cannot_shadow_a_wgsl_builtin() -> None:
    errors = _errors(
        "float sqrt(float x) { return x; } "
        "@gpu void bad(float[] xs) { int i = gpu_id(); xs[i] = sqrt(xs[i]); } "
        "int main() { return 0; }"
    )
    assert _has(errors, "resolves to a source symbol")


def test_globals_uniform_updates_and_whole_array_updates_fail_closed() -> None:
    assert _has(
        _errors("int outside = 1; @gpu void bad(int[] xs) { xs[0] = outside; } int main(){return 0;}"),
        "not a gpu parameter or local",
    )
    assert _has(
        _errors("@gpu void bad(int n, int[] xs) { n = 2; xs[0] = n; } int main(){return 0;}"),
        "read-only uniform",
    )
    assert _has(
        _errors("@gpu void bad(int[] xs, int[] ys) { xs = ys; } int main(){return 0;}"),
        "whole gpu arrays",
    )


def test_wgsl_reserved_source_names_are_mangled() -> None:
    shader = _shader(
        "@gpu void names(int[] uniforms, int offset, bool main) { "
        "int gid = gpu_id(); if (main) { uniforms[gid] = offset; } } "
        "int main() { return 0; }"
    )
    assert "var<storage, read_write> uniforms" not in shader
    assert "offset: i32" not in shader
    assert "main: u32" not in shader
    assert "var gid" not in shader


def test_returning_a_buffer_copies_the_current_element() -> None:
    shader = _shader(
        "@gpu float[] update(float[] xs) { int i = gpu_id(); xs[i] += 1.0; return xs; } int main() { return 0; }"
    )
    assert "var<storage, read_write> btrc_p_0" in shader
    assert re.search(r"_output\[btrc_gid\] = btrc_p_0\[btrc_e_\d+\];", shader)
    assert "atomicMax(&btrc_status.code, 1u)" in shader


def test_round_uses_btrc_ties_away_from_zero_contract() -> None:
    shader = _shader(
        "@gpu float[] rounded(float[] xs) { int i = gpu_id(); return round(xs[i]); } int main() { return 0; }"
    )
    assert "round(" not in shader
    assert "ceil(" in shader
    assert "floor(" in shader


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_cpu_fallback_math_matches_gpu_source_contract(tmp_path: Path, c_compiler: str) -> None:
    executable = _compile_with_gpu_stubs(
        tmp_path,
        "@gpu void rounded(float[] xs) { int i = gpu_id(); "
        "xs[i] = clamp(round(xs[i]), -2.0, 2.0); } "
        "int main() { float[] xs = {-1.5, 2.5, 0.5}; rounded(xs); "
        "return (xs[0] == -2.0 && xs[1] == 2.0 && xs[2] == 1.0) ? 0 : 1; }",
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )
    subprocess.run([str(executable)], check=True)


NAGA = shutil.which("naga")


@pytest.mark.skipif(NAGA is None, reason="naga WGSL validator is not installed")
def test_representative_generated_shader_validates_with_naga() -> None:
    shader = _shader(
        "@gpu float[] validate(float[] xs, int[] ys, bool choose) { int i = gpu_id(); "
        "for (int j = 0; j < 2; ++j) { i = choose ? i : i + j; } "
        "return round(xs[i] * ys[i]); } int main() { return 0; }"
    )
    result = subprocess.run(
        [NAGA, "--stdin-file-path", "generated.wgsl"],
        input=shader,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(NAGA is None, reason="naga WGSL validator is not installed")
def test_all_compound_operator_lowerings_validate_with_naga() -> None:
    result = subprocess.run(
        [NAGA, "--stdin-file-path", "compound.wgsl"],
        input=_shader(_ALL_COMPOUND_OPERATORS_SOURCE),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
