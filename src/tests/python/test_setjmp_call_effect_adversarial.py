"""Adversarial C11 contracts for pointer effects across generated setjmp."""

import pytest

from src.compiler.python.ir.lowering.exceptions import ExceptionLowerer, ParameterEffect
from src.compiler.python.ir.lowering.types import CodegenError
from src.compiler.python.ir.nodes import (
    CType,
    IRFunctionDecl,
    IRFunctionDef,
    IRModule,
    IRParam,
    IRTypedefDef,
)
from src.tests.python.test_codegen import emit_c


@pytest.mark.parametrize(
    "setup, mutation",
    [
        ("", "mutate(&x + 0);"),
        ("int* p = &x; int** pp = &p;", "**pp = 7;"),
        ("int* p = identity(&x);", "*p = 7;"),
    ],
)
def test_unrepresentable_volatile_aliases_fail_closed(setup, mutation):
    identity = "int* identity(int* p) { return p; }" if "identity" in setup else ""

    with pytest.raises(CodegenError, match="requires volatile storage"):
        emit_c(f"""
            void mutate(int* p) {{ *p = 7; }}
            {identity}
            int main() {{
                int x = 0;
                {setup}
                try {{ {mutation} throw "boom"; }}
                catch (string error) {{}}
                return x;
            }}
        """)


@pytest.mark.parametrize(
    "declarations, setup, mutation",
    [
        ("int* saved;", "saved = &x;", "mutate(saved);"),
        ("struct Holder { int* p; };", "struct Holder h; h.p = &x;", "mutate(h.p);"),
        ("", "int* slots[1]; slots[0] = &x;", "*slots[0] = 7;"),
        (
            "int* saved; void mutate_saved() { *saved = 7; }",
            "saved = &x;",
            "mutate_saved();",
        ),
    ],
)
def test_memory_carried_automatic_addresses_fail_at_setjmp_boundary(
    declarations,
    setup,
    mutation,
):
    with pytest.raises(CodegenError, match="escapes into unmodelled storage"):
        emit_c(f"""
            {declarations}
            void mutate(int* p) {{ *p = 7; }}
            int main() {{
                int x = 0;
                {setup}
                try {{ {mutation} throw "boom"; }}
                catch (string error) {{}}
                return x;
            }}
        """)


def test_custom_const_extern_is_not_a_read_only_effect_contract():
    with pytest.raises(CodegenError, match="escapes into unmodelled storage"):
        emit_c("""
            void sneaky(const int* value);
            int main() {
                int value = 0;
                try { sneaky(&value); throw "boom"; }
                catch (string error) {}
                return value;
            }
        """)


@pytest.mark.parametrize(
    "carrier",
    [
        "(intptr_t)(&value)",
        "((((intptr_t)(&value)) ^ (intptr_t)7) ^ (intptr_t)7)",
        "(((intptr_t)(&value)) & ~(intptr_t)0)",
        "(true ? (intptr_t)(&value) : (intptr_t)0)",
        "labs((intptr_t)(&value))",
    ],
)
def test_custom_extern_cannot_hide_a_transformed_integer_address(carrier):
    with pytest.raises(CodegenError, match="escapes into unmodelled storage"):
        emit_c(f"""
            void sneaky(intptr_t bits);
            int main() {{
                int value = 0;
                try {{ sneaky({carrier}); throw "boom"; }}
                catch (string error) {{}}
                return value;
            }}
        """)


def test_source_scalar_return_chain_cannot_launder_an_address():
    with pytest.raises(CodegenError, match="escapes into unmodelled storage"):
        emit_c("""
            intptr_t encode(int* pointer) { return (intptr_t)pointer; }
            intptr_t forward(intptr_t bits) { return bits; }
            void mutate(intptr_t bits) {
                int* pointer = (int*)bits;
                *pointer = 7;
            }
            int main() {
                int value = 0;
                try { mutate(forward(encode(&value))); throw "boom"; }
                catch (string error) {}
                return value;
            }
        """)


@pytest.mark.parametrize(
    "declaration",
    [
        "intptr_t bits = (intptr_t)(&value);",
        "struct Holder holder = {&value};",
    ],
)
def test_declaration_initializers_cannot_hide_automatic_addresses(declaration):
    with pytest.raises(CodegenError, match="escapes into unmodelled storage"):
        emit_c(f"""
            struct Holder {{ int* pointer; }};
            int main() {{
                int value = 0;
                {declaration}
                try {{ throw "boom"; }}
                catch (string error) {{}}
                return value;
            }}
        """)


def test_unused_pointer_return_is_not_a_write_or_capture():
    emitted = emit_c("""
        int* identity(int* value) { return value; }
        int main() {
            int value = 0;
            try { identity(&value); throw "boom"; }
            catch (string error) {}
            return value;
        }
    """)

    assert "int value = 0;" in emitted
    assert "volatile int value" not in emitted


def test_pointer_logical_not_does_not_carry_address_provenance():
    emitted = emit_c("""
        int main() {
            int value = 0;
            int* pointer = &value;
            bool is_null = !pointer;
            try { throw "boom"; }
            catch (string error) {}
            return is_null ? 1 : value;
        }
    """)

    assert "volatile int value" not in emitted


def test_unconditional_pointer_rebinding_strongly_replaces_old_origin():
    emitted = emit_c("""
        int global_value = 0;
        void mutate(int* value) { *value = 7; }
        int main() {
            int value = 0;
            int* pointer = &value;
            pointer = &global_value;
            try { mutate(pointer); throw "boom"; }
            catch (string error) {}
            return value;
        }
    """)

    assert "int value = 0;" in emitted
    assert "volatile int value" not in emitted


def test_short_circuit_rebinding_keeps_the_unexecuted_path_origin():
    with pytest.raises(CodegenError, match="requires volatile storage"):
        emit_c("""
            int global_value = 0;
            void mutate(int* value) { *value = 7; }
            int main() {
                int value = 0;
                int* pointer = &value;
                bool condition = false;
                condition && ((pointer = &global_value) != null);
                try { mutate(pointer); throw "boom"; }
                catch (string error) {}
                return value;
            }
        """)


def test_out_pointer_mutation_cannot_drop_provenance_before_setjmp():
    with pytest.raises(CodegenError, match="unmodelled pointer value"):
        emit_c("""
            long strtol(const char* text, char** end, int base);
            int main() {
                char buffer[8];
                char* end = null;
                strtol(buffer, &end, 10);
                try { *end = 'x'; throw "boom"; }
                catch (string error) {}
                return buffer[0];
            }
        """)


def test_pointee_write_does_not_modify_parameter_pointer_object():
    emitted = emit_c("""
        void run(int* pointer) {
            int** pointer_slot = &pointer;
            try { *pointer = 7; throw "boom"; }
            catch (string error) {}
            if (pointer_slot == null) { return; }
        }
        int main() { int value = 0; run(&value); return value; }
    """)

    assert "void run(int* pointer)" in emitted
    assert "int* volatile pointer" not in emitted


def test_global_and_local_shadow_are_distinct_storage_objects():
    emitted = emit_c("""
        int value = 0;
        void mutate(int* pointer) { *pointer = 7; }
        int main() {
            int* global_pointer = &value;
            {
                int value = 1;
                int* local_pointer = &value;
                try { mutate(global_pointer); throw "boom"; }
                catch (string error) {}
                if (*local_pointer != 1) { return 10; }
            }
            return value;
        }
    """)

    assert "volatile int value" not in emitted


def test_typedef_read_only_closure_is_independent_of_storage_order():
    module = IRModule(
        typedef_defs=[
            IRTypedefDef(CType("const Pointer*"), "Layered"),
            IRTypedefDef(CType("int*"), "Pointer"),
        ]
    )

    facts = ExceptionLowerer.pointer_type_facts(module)

    assert facts.is_pointer(CType("Layered"))
    assert "Layered" not in facts.read_only_pointee_aliases


def test_custom_extern_and_trusted_hosted_reads_have_distinct_effects():
    probe = IRFunctionDef("probe", CType("void"))
    module = IRModule(
        function_decls=[
            IRFunctionDecl(
                "custom_read",
                CType("int"),
                [IRParam(CType("const int*"), "value")],
            )
        ],
        function_defs=[probe],
    )

    catalog = ExceptionLowerer.build_setjmp_call_effects(module)["probe"].catalog

    assert catalog.resolve("custom_read", 1).writes == frozenset({ParameterEffect(0)})
    assert catalog.resolve("memcmp", 3).writes == frozenset()
