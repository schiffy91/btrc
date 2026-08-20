"""Semantic managed ownership carried by physically raw local storage."""

import re
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import _tracked_strict_matrix
from src.tests.btrc.test_mutex_value_contract import COMPILERS
from src.tests.python.test_codegen import emit_c

RAW_MANAGED_SLOT_SOURCE = r"""
    #include <assert.h>

    extern void arc_test_allocation_checkpoint();
    extern long arc_test_allocation_delta();

    typedef char* RawText;

    int rhsCalls = 0;

    int nextSize() {
        rhsCalls += 1;
        return 1;
    }

    char* nextRaw() {
        nextSize();
        return null;
    }

    void exerciseFreshSlot() {
        char* raw = __btrc_string_alloc(1);
        raw[0] = 'a';

        raw = raw;
        assert(raw[0] == 'a');

        raw = null;
        assert(raw == null);
    }

    void exerciseBorrowedSlot() {
        string borrowed = f"borrowed={2}";
        string slot = borrowed;
        assert(slot[0] == 'b');

        slot = slot;
        assert(slot == borrowed);
        slot = null;
    }

    void exerciseEffectfulSlot() {
        char* raw = __btrc_string_alloc(1);
        raw[0] = 'c';
        raw = nextRaw();
        assert(rhsCalls == 1 && raw == null);
    }

    void exerciseQualifiedAliasSlot() {
        volatile RawText raw = __btrc_string_alloc(1);
        raw[0] = 'q';
        raw = null;
        assert(raw == null);
    }

    int main() {
        arc_test_allocation_checkpoint();
        exerciseFreshSlot();
        assert(arc_test_allocation_delta() == 0);
        exerciseBorrowedSlot();
        assert(arc_test_allocation_delta() == 0);
        exerciseEffectfulSlot();
        assert(arc_test_allocation_delta() == 0);
        exerciseQualifiedAliasSlot();
        assert(arc_test_allocation_delta() == 0);
        assert(rhsCalls == 1);
        assert(arc_test_allocation_delta() == 0);
        return 0;
    }
"""

RAW_MANAGED_SLOT_UNWIND_SOURCE = r"""
    #include <assert.h>

    extern void arc_test_allocation_checkpoint();
    extern long arc_test_allocation_delta();

    void unwindRawSlot() {
        try {
            char* raw = __btrc_string_alloc(1);
            raw[0] = 'u';
            raw = raw;
            throw "raw slot unwind";
        } catch (string error) {
            assert(error.equals("raw slot unwind"));
        }
    }

    int main() {
        unwindRawSlot();
        arc_test_allocation_checkpoint();
        unwindRawSlot();
        assert(arc_test_allocation_delta() == 0);
        return 0;
    }
"""

EXTERN_MANAGED_GLOBAL_SOURCE = r"""
    #include <assert.h>

    extern string shared;

    void resetExternal() {
        shared = null;
    }

    int main() {
        assert(shared != null);
        resetExternal();
        assert(shared == null);
        return 0;
    }
"""

DEFINED_MANAGED_GLOBAL_SOURCE = r"""
    #include <assert.h>

    extern void arc_test_allocation_checkpoint();
    extern long arc_test_allocation_delta();

    string shared;

    void exerciseDefinedGlobal() {
        shared = f"defined={7}";
        assert(shared[0] == 'd');
        shared = shared;
        shared = null;
    }

    int main() {
        arc_test_allocation_checkpoint();
        exerciseDefinedGlobal();
        assert(arc_test_allocation_delta() == 0);
        return 0;
    }
"""


def _function_body(generated: str, signature: str) -> str:
    start = generated.index(signature)
    depth = 0
    for index in range(generated.index("{", start), len(generated)):
        if generated[index] == "{":
            depth += 1
        elif generated[index] == "}":
            depth -= 1
            if depth == 0:
                return generated[start : index + 1]
    raise AssertionError(f"unterminated generated function: {signature}")


def _analyze(source: str):
    program = Parser(Lexer(source, "<test>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def test_raw_managed_slot_preserves_physical_type_and_typed_replacement() -> None:
    generated = emit_c(RAW_MANAGED_SLOT_SOURCE)
    body = _function_body(generated, "void exerciseFreshSlot(void) {")

    assert re.search(r"char\* (?:volatile )?raw = __btrc_string_alloc\(1\);", body)
    assert re.search(r"char\* (?:volatile )?__btrc_slot_new_\d+ = NULL;", body)
    assert re.search(r"char\* __btrc_slot_old_\d+ = NULL;", body)
    assert "__btrc_string_retain(" in body
    assert "__btrc_string_release(" in body
    assert "(void)((raw = NULL));" not in body
    effectful = _function_body(generated, "void exerciseEffectfulSlot(void) {")
    assert effectful.count("nextRaw()") == 1
    assert "__btrc_string_release(" in effectful

    qualified = _function_body(generated, "void exerciseQualifiedAliasSlot(void) {")
    assert re.search(r"volatile RawText raw = __btrc_string_alloc\(1\);", qualified)
    assert "__btrc_string_release(" in qualified

    unwind = _function_body(emit_c(RAW_MANAGED_SLOT_UNWIND_SOURCE), "void unwindRawSlot(void) {")
    assert "__btrc_register_direct_cleanup(" in unwind
    assert "__btrc_string_release(" in unwind


def test_defined_global_fact_excludes_extern_only_declarations() -> None:
    analyzed = _analyze(
        """
        extern string external;
        extern string laterDefined;
        string laterDefined;
        string definedFirst;
        extern string definedFirst;
        string owned;
        """
    )

    assert not analyzed.errors
    assert set(analyzed.global_var_types) == {
        "external",
        "laterDefined",
        "definedFirst",
        "owned",
    }
    assert analyzed.defined_global_names == frozenset({"laterDefined", "definedFirst", "owned"})


def test_extern_global_store_is_raw_but_defined_global_is_transactional() -> None:
    external = _function_body(emit_c(EXTERN_MANAGED_GLOBAL_SOURCE), "void resetExternal(void) {")
    assert "(void)((shared = NULL));" in external
    assert "__btrc_slot_" not in external
    assert "__btrc_string_retain(" not in external
    assert "__btrc_string_release(" not in external

    defined = _function_body(
        emit_c(DEFINED_MANAGED_GLOBAL_SOURCE),
        "void exerciseDefinedGlobal(void) {",
    )
    assert re.search(r"char\* __btrc_slot_new_\d+ = NULL;", defined)
    assert re.search(r"char\* __btrc_slot_old_\d+ = NULL;", defined)
    assert "__btrc_string_retain(" in defined
    assert "__btrc_string_release(" in defined


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
def test_raw_managed_slot_matrix_is_tracked_strict_c11_clean(tmp_path: Path) -> None:
    generated = tmp_path / "raw-managed-slot.c"
    generated.write_text(emit_c(RAW_MANAGED_SLOT_SOURCE))
    _tracked_strict_matrix(("python-raw-managed-slot", generated), tmp_path)

    unwind = tmp_path / "raw-managed-slot-unwind.c"
    unwind.write_text(emit_c(RAW_MANAGED_SLOT_UNWIND_SOURCE))
    _tracked_strict_matrix(("python-raw-managed-slot-unwind", unwind), tmp_path)

    external = tmp_path / "extern-managed-global.c"
    external.write_text(emit_c(EXTERN_MANAGED_GLOBAL_SOURCE))
    external_definition = tmp_path / "extern-managed-global-definition.c"
    external_definition.write_text('char *shared = "external";\n')
    _tracked_strict_matrix(
        ("python-extern-managed-global", external),
        tmp_path,
        extra_sources=(external_definition,),
    )

    defined = tmp_path / "defined-managed-global.c"
    defined.write_text(emit_c(DEFINED_MANAGED_GLOBAL_SOURCE))
    _tracked_strict_matrix(("python-defined-managed-global", defined), tmp_path)
