"""Truth-sweep tests: builtin-name hijacking, string-method spec, type compat.

Covers three audit findings:
  CMP-22: user-defined functions named like builtins (len/print/printf/str)
          must be called as normal functions; builtin lowering applies only
          when no user definition exists. for-in `range(...)` stays a
          structural counting-loop form, while a user `range` function works
          in expression position.
  CMP-23: the string-method API lives in ONE shared spec
          (src/compiler/python/analyzer/types.py); analyzer and IR-gen views
          must not drift, and every named helper must exist in the registry.
  CMP-24: unrelated pointer types are incompatible. C interop crosses the
          boundary explicitly through casts or void*, never an unknown-type
          wildcard that also hides ordinary program errors.
"""

import shutil
import subprocess
import tempfile

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.optimizer import IROptimizer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import TypeExpr


def emit_c(source: str) -> str:
    """Full pipeline on a self-contained snippet (no stdlib), return C text."""
    tokens = Lexer(source, "<test>").tokenize()
    program = Parser(tokens).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors, f"analyzer errors: {analyzed.errors}"
    ir_module = IRLowerer(analyzed).lower()
    ir_module = IROptimizer(ir_module).optimize()
    return CEmitter().emit(ir_module)


def analyze(source: str):
    tokens = Lexer(source, "<test>").tokenize()
    program = Parser(tokens).parse()
    return SemanticAnalyzer().analyze(program)


def compile_and_run(source: str) -> str:
    """Compile snippet to C, build with gcc -std=c11, run, return stdout."""
    if shutil.which("gcc") is None:
        pytest.skip("gcc not available")
    c_code = emit_c(source)
    with tempfile.TemporaryDirectory() as td:
        c_path = f"{td}/prog.c"
        exe = f"{td}/prog"
        with open(c_path, "w") as f:
            f.write(c_code)
        build = subprocess.run(
            ["gcc", "-std=c11", "-pedantic-errors", c_path, "-o", exe, "-lm"], capture_output=True, text=True
        )
        assert build.returncode == 0, f"gcc failed:\n{build.stderr}\n{c_code}"
        run = subprocess.run([exe], capture_output=True, text=True, timeout=10)
        assert run.returncode == 0, f"program failed: {run.stderr}"
        return run.stdout


# ---------------------------------------------------------------------------
# CMP-22: user definitions beat builtin lowering
# ---------------------------------------------------------------------------


def test_user_len_function_beats_builtin_end_to_end():
    out = compile_and_run("int len(int x) { return x + 40; }\nint main() { print(len(2)); return 0; }\n")
    assert out.strip() == "42"


def test_user_len_emits_call_not_field_access():
    c = emit_c("int len(int x) { return x + 40; }\nint main() { print(len(2)); return 0; }\n")
    assert "len(2)" in c
    assert "->len" not in c  # the old hijack lowered len(2) to `2->len`


def test_builtin_len_still_applies_when_user_does_not_define_it():
    c = emit_c('int main() { string s = "abc"; print(len(s)); return 0; }')
    assert "strlen" in c


def test_user_print_function_beats_builtin_printf_lowering():
    c = emit_c('void print(int x) { printf("custom %d\\n", x); }\nint main() { print(7); return 0; }\n')
    assert "print(7)" in c
    assert 'printf("%d\\n", 7)' not in c


def test_builtin_print_still_lowers_to_printf_when_undefined():
    c = emit_c("int main() { print(7); return 0; }")
    assert 'printf("%d\\n", 7)' in c


def test_user_printf_function_lowered_as_normal_call_with_defaults():
    c = emit_c("int printf(int x, int y = 5) { return x + y; }\nint main() { return printf(1); }\n")
    main = c.split("int main(void)", 1)[1]
    assert main.count(" = 1)") == 1
    assert main.count("__btrc_default___btrc_source_printf_2(") == 1
    assert main.count("__btrc_source_printf(") == 1


def test_user_str_function_keeps_working():
    out = compile_and_run(
        'string str(int x) { if (x > 0) { return "pos"; } return "neg"; }\nint main() { print(str(5)); return 0; }\n'
    )
    assert out.strip() == "pos"


def test_user_range_works_in_expression_position():
    out = compile_and_run("int range(int x) { return x * 2; }\nint main() { int y = range(21); print(y); return 0; }\n")
    assert out.strip() == "42"


def test_for_in_range_stays_structural_even_with_user_range_defined():
    # Documented semantics: `for x in range(...)` is a structural counting
    # loop form of the language; a user `range` function does not change it
    # (and its arity is NOT imposed on the loop form).
    out = compile_and_run(
        "int range(int x) { return x * 2; }\n"
        "int main() {\n"
        "    for i in range(1, 4) { print(i); }\n"
        "    print(range(5));\n"
        "    return 0;\n"
        "}\n"
    )
    assert out.split() == ["1", "2", "3", "10"]


def test_for_in_range_unaffected_when_no_user_range():
    out = compile_and_run("int main() { for i in range(3) { print(i); } return 0; }\n")
    assert out.split() == ["0", "1", "2"]


# ---------------------------------------------------------------------------
# CMP-23: one shared string-method spec, no drift
# ---------------------------------------------------------------------------


def test_string_method_spec_is_single_source_of_truth():
    import src.compiler.python.ir.lowering.calls as irm
    from src.compiler.python.analyzer.types import STRING_METHODS

    expected_helpers = {n: s.helper for n, s in STRING_METHODS.items() if s.helper}
    expected_tracked = {n for n, s in STRING_METHODS.items() if s.tracked}
    assert expected_helpers == irm._STRING_METHODS
    assert expected_tracked == irm._STRING_TRACK_METHODS


def test_analyzer_type_table_matches_spec():
    from src.compiler.python.analyzer.types import STRING_METHODS

    types = SemanticAnalyzer().types
    for name, spec in STRING_METHODS.items():
        t = types.string_method_return_type(name)
        assert t is not None, f"no analyzer return type for {name!r}"
        expected_base = spec.return_type.rstrip("*")
        assert t.base == expected_base, f"{name}: {t.base} != {expected_base}"
        assert t.pointer_depth == spec.return_type.count("*"), name
    assert types.string_method_return_type("notAMethod") is None


def test_every_spec_helper_exists_in_runtime_registry():
    from src.compiler.python.analyzer.types import STRING_CONVERSIONS, STRING_METHODS
    from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

    known = {definition.name for definition in RuntimeHelperCatalog().definitions}
    for name, spec in STRING_METHODS.items():
        if spec.helper:
            assert spec.helper in known, f"{name}: helper {spec.helper} missing"
    # Conversion callees are either hosted C functions or registered runtime
    # helpers when deterministic range handling needs a small wrapper.
    for name, (c_func, _cast) in STRING_CONVERSIONS.items():
        assert name in STRING_METHODS
        if c_func.startswith("__btrc"):
            assert c_func in known, f"{name}: helper {c_func} missing"


def test_string_methods_lower_through_spec_helpers():
    c = emit_c(
        "int main() {\n"
        '    string s = "  Hi  ";\n'
        "    print(s.trim().toUpper());\n"
        "    print(s.charLen());\n"
        "    return 0;\n"
        "}\n"
    )
    assert "__btrc_trim" in c
    assert "__btrc_toUpper" in c
    assert "__btrc_charLen" in c
    assert "__btrc_str_track" in c  # trim/toUpper results are tracked


def test_string_to_bool_lowers_to_the_documented_runtime_helper():
    c = emit_c('int main() { return "false".toBool() ? 1 : "yes".toBool() ? 0 : 2; }\n')
    assert "__btrc_parseBool" in c
    assert "string_toBool" not in c


# ---------------------------------------------------------------------------
# CMP-24: unrelated pointers rejected; explicit void* interop retained
# ---------------------------------------------------------------------------


def _compat(target: TypeExpr, source: TypeExpr) -> bool:
    return SemanticAnalyzer().types.types_compatible(target, source)


def test_string_pointer_not_compatible_with_generic_collection():
    list_str = TypeExpr(base="List", generic_args=[TypeExpr(base="string")], pointer_depth=1)
    str_ptr = TypeExpr(base="string", pointer_depth=1)
    assert not _compat(list_str, str_ptr)
    assert not _compat(str_ptr, list_str)  # reverse direction too


def test_split_assigned_to_list_of_string_is_an_analyzer_error():
    analyzed = analyze(
        'int main() {\n    string s = "a b c";\n    List<string> words = s.split(" ");\n    return 0;\n}\n'
    )
    assert any("words" in e for e in analyzed.errors), analyzed.errors


def test_var_inferred_split_keeps_compiling():
    analyzed = analyze('int main() { var parts = "a,b".split(","); return 0; }')
    assert not analyzed.errors, analyzed.errors


def test_unrelated_unknown_pointer_types_require_an_explicit_cast():
    a = TypeExpr(base="FILE", pointer_depth=1)
    b = TypeExpr(base="MyHandle", pointer_depth=1)
    assert not _compat(a, b)


def test_void_pointer_stays_assignable_both_ways():
    void_ptr = TypeExpr(base="void", pointer_depth=1)
    list_str = TypeExpr(base="List", generic_args=[TypeExpr(base="string")], pointer_depth=1)
    assert _compat(list_str, void_ptr)  # NULL/void* into a collection var
    assert _compat(void_ptr, list_str)  # collection into a void* (C interop)
