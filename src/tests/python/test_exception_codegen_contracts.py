"""White-box contracts for the setjmp/cleanup lowering boundary."""

import re

import pytest

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ir.gen.errors import CodegenError
from src.compiler.python.ir.gen.setjmp_volatility import apply_setjmp_volatility
from src.compiler.python.ir.nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFor,
    IRFunctionDef,
    IRIf,
    IRLiteral,
    IRModule,
    IRParam,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c


def analyze_source(source):
    program = Parser(Lexer(source, "<test>").tokenize()).parse()
    return Analyzer().analyze(program)


def test_setjmp_functions_qualify_params_loops_and_capture_locals():
    emitted = emit_c("""
        int mutate(int value) {
            try { value = 2; throw "x"; }
            catch (string message) { value++; }
            return value;
        }
        int main() {
            for (int i = 0; i < 1; i++) {
                try { i = 3; throw "loop"; }
                catch (string message) {}
            }
            int captured = 4;
            var closure = () => {
                try { captured = 5; throw "lambda"; }
                catch (string message) {}
                return captured;
            };
            int threaded = 6;
            Thread<int> worker = spawn(() => {
                try { threaded = 7; throw "thread"; }
                catch (string message) {}
                return threaded;
            });
            return mutate(closure()) + worker.join();
        }
    """)

    assert "int mutate(volatile int value)" in emitted
    assert "volatile int i = 0;" in emitted
    assert "for (; (i < 1); (i++))" in emitted
    assert re.search(r"static int __btrc_lambda_\d+\(void\* __btrc_env\)", emitted)
    assert re.search(r"static void\* __btrc_spawn_wrapper_\d+\(void\* __arg\)", emitted)
    assert "volatile int captured = __env->captured;" in emitted
    assert "volatile int threaded = __env->threaded;" in emitted


def test_setjmp_volatility_follows_lexical_visibility():
    outer = IRVarDecl(CType("int"), "outer")
    completed_sibling = IRVarDecl(CType("int"), "completed_sibling")
    loop_index = IRVarDecl(CType("int"), "index", IRLiteral("0"))
    capture = IRVarDecl(CType("int"), "capture")
    nested_visible = IRVarDecl(CType("int"), "nested_visible")
    inner_aggregate = IRVarDecl(CType("struct stat"), "inner_aggregate")
    after_loop = IRVarDecl(CType("int"), "after_loop")
    static_local = IRVarDecl(CType("int"), "static_local", is_static=True)

    def setjmp():
        return IRBinOp(
            IRCall("setjmp", [IRVar("frame")]),
            "==",
            IRLiteral("0"),
        )

    body = IRBlock(
        stmts=[
            outer,
            IRIf(
                condition=IRLiteral("1"),
                then_block=IRBlock(stmts=[completed_sibling]),
            ),
            IRExprStmt(expr=IRStmtExpr(stmts=[capture], result=IRLiteral("capture"))),
            IRFor(
                init=loop_index,
                condition=IRLiteral("1"),
                body=IRBlock(
                    stmts=[
                        IRIf(
                            condition=setjmp(),
                            then_block=IRBlock(
                                stmts=[
                                    IRAssign(IRVar("outer"), IRLiteral("1")),
                                    IRAssign(IRVar("parameter"), IRLiteral("1")),
                                    IRAssign(IRVar("index"), IRLiteral("1")),
                                    IRAssign(IRVar("capture"), IRLiteral("1")),
                                    nested_visible,
                                    IRIf(
                                        condition=setjmp(),
                                        then_block=IRBlock(
                                            stmts=[
                                                IRAssign(IRVar("nested_visible"), IRLiteral("1")),
                                                inner_aggregate,
                                            ]
                                        ),
                                    ),
                                ]
                            ),
                        ),
                    ]
                ),
            ),
            after_loop,
            static_local,
        ]
    )
    parameter = IRParam(CType("int"), "parameter")
    module = IRModule(
        function_defs=[
            IRFunctionDef(
                name="probe",
                return_type=CType("void"),
                params=[parameter],
                body=body,
            )
        ]
    )

    apply_setjmp_volatility(module)

    assert parameter.is_volatile
    assert outer.is_volatile
    assert loop_index.is_volatile
    assert capture.is_volatile
    assert nested_visible.is_volatile
    assert not completed_sibling.is_volatile
    assert not inner_aggregate.is_volatile
    assert not after_loop.is_volatile
    assert not static_local.is_volatile


def test_try_local_c_aggregate_is_not_volatile():
    emitted = emit_c("""
        struct Probe { int value; };
        void fill(struct Probe* probe) { probe->value = 42; }
        int run(int outer) {
            try {
                struct Probe probe;
                fill(&probe);
                outer = probe.value;
            } catch (string message) {}
            return outer;
        }
        int main() { return run(0); }
    """)

    assert "int run(volatile int outer)" in emitted
    assert "struct Probe probe;" in emitted
    assert "volatile struct Probe probe;" not in emitted


def test_unmodified_aggregate_parameter_is_not_volatile():
    emitted = emit_c("""
        struct Probe { int value; };
        int readValue(int* value) { return *value; }
        int readProbe(struct Probe* probe) { return readValue(&probe->value); }
        int run(struct Probe probe) {
            int result = 0;
            int* alias = &probe.value;
            try {
                result = readProbe(&probe) + readValue(alias);
                throw "done";
            }
            catch (string message) {}
            return result;
        }
        int main() { struct Probe probe = {21}; return run(probe) == 42 ? 0 : 1; }
    """)

    assert "int run(struct Probe probe)" in emitted
    assert "volatile struct Probe" not in emitted


@pytest.mark.parametrize(
    "source",
    (
        """
        volatile int globalValue = 0;
        int* globalAlias = &globalValue;
        int main() { return *globalAlias; }
        """,
        """
        volatile int globalValues[1] = {0};
        void take(int* values) {}
        int main() { take(globalValues); return 0; }
        """,
        """
        void mutate(int* value) { *value = 1; }
        int main() {
            int value = 0;
            try { mutate(&value); throw "done"; } catch (string error) {}
            return value;
        }
        """,
        """
        void mutate(int* value) { *value = 1; }
        int main() {
            int value = 0; int* alias = &value;
            try { mutate(alias); throw "done"; } catch (string error) {}
            return value;
        }
        """,
        """
        void mutate(int* values) { values[0] = 1; }
        int main() {
            int values[1] = {0};
            try { mutate(values); throw "done"; } catch (string error) {}
            return values[0];
        }
        """,
        """
        int main() {
            int value = 0; int* alias = &value;
            try { value = 1; throw "done"; } catch (string error) {}
            return *alias;
        }
        """,
        """
        void take(int* values) {}
        struct Probe { int values[2]; };
        int main() {
            struct Probe probe = {{0, 0}};
            try { probe.values[0] = 1; throw "done"; }
            catch (string error) {}
            take(probe.values);
            return 0;
        }
        """,
        """
        int main() {
            int values[1] = {0}; int* alias = values;
            try { values[0] = 1; throw "done"; } catch (string error) {}
            return alias[0];
        }
        """,
        """
        int main() {
            int values[1] = {0}; int* alias = &values[0];
            try { values[0] = 1; throw "done"; } catch (string error) {}
            return alias[0];
        }
        """,
        """
        struct Probe { int value; };
        int main() {
            struct Probe probe = {0}; int* alias = &probe.value;
            try { probe.value = 1; throw "done"; } catch (string error) {}
            return *alias;
        }
        """,
        """
        int main() {
            int first = 0; int second = 1; int* pointer = &first;
            int** alias = &pointer;
            try { pointer = &second; throw "done"; } catch (string error) {}
            return **alias;
        }
        """,
        """
        int run(int value) {
            int* alias = &value;
            try { value = 1; throw "done"; } catch (string error) {}
            return *alias;
        }
        int main() { return run(0); }
        """,
        """
        int main() {
            volatile int value = 0;
            volatile int* alias = &value;
            return alias[0];
        }
        """,
        """
        void mutate(int* value) { *value = 1; }
        void forwardMutation(int* value) { mutate(value); }
        int main() {
            int value = 0;
            try { forwardMutation(&value); throw "done"; }
            catch (string error) {}
            return value;
        }
        """,
        """
        int* escaped;
        void remember(int* value) { escaped = value; }
        int main() {
            int value = 0;
            try { remember(&value); throw "done"; }
            catch (string error) {}
            return value;
        }
        """,
        """
        class Box<T> {
            public Box() {}
            public int run(int value) {
                int* alias = &value;
                try { value = 1; throw "done"; } catch (string error) {}
                return *alias;
            }
        }
        int main() { Box<int> box = new Box<int>(); return box.run(0); }
        """,
    ),
)
def test_volatile_storage_aliases_fail_at_the_owning_stage(source):
    analyzed = analyze_source(source)
    qualifier_errors = [error for error in analyzed.errors if "would discard volatile storage qualification" in error]
    if qualifier_errors:
        assert "volatile" in source
        assert "unsupported layered pointer qualifiers" in qualifier_errors[0]
        return
    assert not analyzed.errors
    with pytest.raises(
        CodegenError,
        match=r"unsupported layered pointer qualifiers|escapes into unmodelled storage",
    ):
        emit_c(source)


def test_outer_volatile_pointer_global_uses_cross_front_declarator_semantics():
    emitted = emit_c("""
        int value = 7;
        volatile int* pointer = &value;
        int main() { return *pointer == 7 ? 0 : 1; }
    """)

    assert "int* volatile pointer = (&value);" in emitted


def test_unaliased_and_shadowed_setjmp_storage_remains_supported():
    emitted = emit_c("""
        int main() {
            int value = 0;
            try { value = 1; throw "done"; } catch (string error) {}
            int size = sizeof(&value);
            {
                int value = 2;
                int* alias = &value;
                size = size + *alias;
            }
            return value + size;
        }
    """)

    assert "volatile int value = 0;" in emitted


def test_static_shadow_does_not_qualify_outer_automatic():
    emitted = emit_c("""
        int main() {
            int value = 0;
            {
                static int value = 0;
                try { value = 1; throw "done"; } catch (string error) {}
            }
            return value;
        }
    """)

    assert "volatile int value = 0;" not in emitted
    assert re.search(r"static int value(?:_\d+)? = 0;", emitted)


def test_cleanup_scope_markers_precede_registration_and_normal_discard():
    emitted = emit_c("""
        class Item { public Item() {} }
        int main() {
            try {
                { Item item = new Item(); }
                throw "later";
            } catch (string message) {}
            return 0;
        }
    """)

    item_declaration = emitted.index("Item* volatile item")
    marker = emitted.rfind("__btrc_cleanup_mark()", 0, item_declaration)
    registration = emitted.index("__btrc_register_cleanup(", marker)
    registration_text = emitted[registration : registration + 220]
    assert "((void*)(&item))" in registration_text
    assert re.search(r"__btrc_cleanup_take_\d+", registration_text)
    assert "Item* volatile* typed_slot" in emitted
    assert "void** ptr_ref" not in emitted
    adapter = emitted.index("static void* __btrc_cleanup_take_")
    assert emitted.index("struct Item {") < adapter < emitted.index("Item* Item_new(void) {")
    discard = emitted.index("__btrc_discard_cleanups_to(", marker)
    throw = emitted.rindex("__btrc_throw(")
    assert marker < registration < discard < throw


def test_return_expression_registration_is_discarded_before_return():
    emitted = emit_c("""
        class Item {
            public int value;
            public Item(int value) { self.value = value; }
        }
        int read(Item item) { return item.value; }
        int build() { return read(new Item(7)); }
        int main() {
            try {
                int result = build();
                if (result == 7) { throw "later"; }
            } catch (string message) {}
            return 0;
        }
    """)

    start = emitted.rindex("int build(void) {")
    end = emitted.index("\n}", start)
    body = emitted[start:end]
    marker = body.index("__btrc_cleanup_mark()")
    registration = body.index("__btrc_register_cleanup(")
    discard = body.index("__btrc_discard_cleanups_to(")
    returned = body.rindex("return ")
    assert marker < registration < discard < returned


def test_try_frames_are_indirect_and_catch_messages_are_owned():
    emitted = emit_c("""
        int main() {
            try { throw "outer"; }
            catch (string outer) {
                try { throw "inner"; } catch (string inner) {}
                assert(outer.equals("outer"));
            }
            return 0;
        }
    """)

    assert "__btrc_try_frame** __btrc_try_stack" in emitted
    assert "setjmp(__btrc_try_stack[__btrc_try_top]->env)" in emitted
    assert "longjmp(__btrc_try_stack[level]->env, 1)" in emitted
    assert "__btrc_str_track(__btrc_strdup(__btrc_error_msg))" in emitted


def test_string_exception_cleanup_uses_non_arc_unwind_path():
    emitted = emit_c("""
        void fail(string input) {
            string managed = input.substring(1, 2);
            throw managed;
        }
        int main() {
            try { fail("abcd"); } catch (string message) {}
            return 0;
        }
    """)

    assert re.search(
        r"__btrc_register_direct_cleanup\(\(\(void\*\)\(&managed\)\), "
        r"__btrc_cleanup_take_\d+, __btrc_string_release_cleanup\)",
        emitted,
    )
    assert "__btrc_register_cleanup(((void*)(&managed))" not in emitted


def test_string_pointer_arithmetic_is_a_borrowed_c_operand():
    emitted = emit_c("""
        bool matchesAt(string text, int offset) {
            return strncmp((char*)text + offset, "x", 1) == 0;
        }
        int main() { return matchesAt("ax", 1) ? 0 : 1; }
    """)

    start = emitted.index("bool matchesAt(")
    end = emitted.index("\n}", start)
    body = emitted[start:end]
    assert 'strncmp((((char*)text) + offset), "x", 1)' in body
    assert "__btrc_string_release" not in body
