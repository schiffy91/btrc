"""Managed-return callback provenance across nontrivial source control flow."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.compiler.python.analyzer.program import AnalyzedProgram, ClassInfo, InterfaceInfo
from src.compiler.python.analyzer.types import IndexedProtocolResolver, TypeIdentity
from src.compiler.python.ir.lowering.calls import (
    CallableProvenance,
    CallableReturnABI,
    CallableSignatureLowerer,
)
from src.compiler.python.ir.lowering.ownership import (
    CleanupScopeState,
    CleanupSlotRegistry,
    CycleMetadata,
    ManagedLifetimeLowerer,
    ManagedValueSemantics,
    OwnershipLowerer,
)
from src.compiler.python.ir.lowering.session import LoweringSession
from src.compiler.python.ir.lowering.types import CodegenError, CTypeLowerer
from src.compiler.python.ir.nodes import IRCall, IRExprStmt, IRModule, IRStatementSequence, IRSwitch
from src.compiler.python.syntax.ast.generated import (
    AssignExpr,
    BinaryExpr,
    CallExpr,
    FieldAccessExpr,
    Identifier,
    Program,
    TypeExpr,
)
from src.tests.python.test_analyzer import analyze
from src.tests.python.test_codegen import emit_c

STRICT_C_COMPILERS = tuple(
    compiler for compiler in (shutil.which("gcc"), shutil.which("clang")) if compiler is not None
)
ASAN_COMPILER = (
    "/usr/bin/clang"
    if sys.platform == "darwin" and os.access("/usr/bin/clang", os.X_OK)
    else (STRICT_C_COMPILERS[-1] if STRICT_C_COMPILERS else None)
)


def _callable_owner(
    *,
    class_table: dict[str, object] | None = None,
    function_table: dict[str, object] | None = None,
    interface_table: dict[str, InterfaceInfo] | None = None,
    hosted_call_ids: set[int] | None = None,
    node_types: dict[int, TypeExpr] | None = None,
    local_names: set[str] | None = None,
) -> CallableProvenance:
    """Build the callable owner through its concrete lowering-state API."""

    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table=dict(class_table or {}),
        function_table=dict(function_table or {}),
        interface_table=dict(interface_table or {}),
        hosted_call_ids=set(hosted_call_ids or ()),
        node_types=dict(node_types or {}),
    )
    session = LoweringSession(module=IRModule(), node_types=analyzed.node_types)
    if local_names:
        session.local_ownership_scopes.append(dict.fromkeys(local_names))
    types = CTypeLowerer(session, analyzed)
    return CallableProvenance(analyzed, session, types, CallableSignatureLowerer(analyzed, types))


class CallableRuntimeHarness:
    """Strict-C execution proof for ordinary and generic callable ownership."""

    SOURCE = r"""
        #include <assert.h>

        extern string foreign(bool ignored);
        extern string? missing(bool ignored);
        string make(bool ignored) { return f"owned={1}"; }
        string other(bool ignored) { return f"other={2}"; }
        void consume(string value) { assert(len(value) == 7); }

        int exercise(bool choose) {
            __fn_ptr<string, bool> callback = make;
            choose && (bool)(callback = other);
            string shortAnd = callback(false);
            assert(len(shortAnd) == 7);

            callback = make;
            choose || (bool)(callback = other);
            string shortOr = callback(false);
            assert(len(shortOr) == 7);

            callback = choose ? make : other;
            string conditional = callback(false);
            assert(len(conditional) == 7);

            callback = foreign;
            string savedCallee = callback((bool)(callback = make));
            assert(len(savedCallee) == 7);

            __fn_ptr<string, bool> chained = (callback = other);
            string assigned = chained(false);
            assert(len(assigned) == 7);

            callback = foreign;
            string effectfulCallee =
                ((bool)(callback = make) ? callback : callback)(false);
            assert(len(effectfulCallee) == 7);

            callback = foreign;
            string effectfulBranch =
                ((bool)(callback = make) ? callback(false) : foreign(false));
            assert(len(effectfulBranch) == 7);

            callback = foreign;
            string coalesced =
                missing((bool)(callback = make)) ?? callback(false);
            assert(len(coalesced) == 7);

            callback = foreign;
            int receiverLength =
                ((bool)(callback = make) ? callback(false) : foreign(false)).length();
            assert(receiverLength == 7);

            __fn_ptr<void, string> consumer = consume;
            callback = foreign;
            ((bool)(callback = make) ? consumer : consumer)(callback(false));
            string afterOwnedArgument = callback(false);
            assert(len(afterOwnedArgument) == 7);

            callback = make;
            ((bool)(callback = foreign) ? consumer : consumer)(callback(false));
            string afterBorrowedArgument = callback(false);
            assert(len(afterBorrowedArgument) == 7);
            return 0;
        }

        int exerciseImmediateCaptureOrder() {
            int capturedScalar = 3;
            int scalarResult =
                ((int first, int second) => capturedScalar)(
                    (int)(capturedScalar = 9),
                    capturedScalar
                );
            assert(scalarResult == 3);

            string capturedString = f"old={1}";
            string stringResult =
                ((string ignored) => capturedString)(
                    (string)(capturedString = f"new={2}")
                );
            assert(stringResult == "old=1");
            return 0;
        }

        class Wrap<T> {
            public Wrap() {}
            public int exercise(bool choose) {
                __fn_ptr<string, bool> callback = make;
                choose && (bool)(callback = other);
                string shortCircuit = callback(false);
                assert(len(shortCircuit) == 7);

                callback = choose ? make : other;
                string conditional = callback(false);
                assert(len(conditional) == 7);

                callback = foreign;
                string savedCallee = callback((bool)(callback = make));
                assert(len(savedCallee) == 7);

                callback = foreign;
                string effectfulCallee =
                    ((bool)(callback = make) ? callback : callback)(false);
                assert(len(effectfulCallee) == 7);

                callback = foreign;
                string effectfulBranch =
                    ((bool)(callback = make) ? callback(false) : foreign(false));
                assert(len(effectfulBranch) == 7);

                callback = foreign;
                string coalesced =
                    missing((bool)(callback = make)) ?? callback(false);
                assert(len(coalesced) == 7);

                callback = foreign;
                int receiverLength =
                    ((bool)(callback = make) ? callback(false) : foreign(false)).length();
                assert(receiverLength == 7);

                __fn_ptr<void, string> consumer = consume;
                callback = foreign;
                ((bool)(callback = make) ? consumer : consumer)(callback(false));
                string afterOwnedArgument = callback(false);
                assert(len(afterOwnedArgument) == 7);

                callback = make;
                ((bool)(callback = foreign) ? consumer : consumer)(callback(false));
                string afterBorrowedArgument = callback(false);
                assert(len(afterBorrowedArgument) == 7);
                return 0;
            }
        }

        int main() {
            assert(exercise(false) == 0);
            assert(exercise(true) == 0);
            assert(exerciseImmediateCaptureOrder() == 0);
            Wrap<int> wrap = new Wrap<int>();
            assert(wrap.exercise(false) == 0);
            assert(wrap.exercise(true) == 0);
            return 0;
        }
    """
    SANITIZER_SOURCE = SOURCE
    FOREIGN_DEFINITION = """
        char* foreign(bool ignored) {
            (void)ignored;
            return "foreign";
        }
        char* missing(bool ignored) {
            (void)ignored;
            return NULL;
        }
    """

    @classmethod
    def build_and_run(
        cls,
        tmp_path: Path,
        compiler: str,
        *extra_flags: str,
        source_text: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> None:
        source = tmp_path / f"callable-runtime-{Path(compiler).name}.c"
        executable = source.with_suffix("")
        source.write_text(emit_c(source_text or cls.SOURCE) + "\n" + cls.FOREIGN_DEFINITION)
        built = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                *extra_flags,
                str(source),
                "-lm",
                "-lpthread",
                "-o",
                str(executable),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            env=environment,
        )
        assert built.returncode == 0, built.stderr
        executed = subprocess.run(
            [str(executable)],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            env=environment,
        )
        assert executed.returncode == 0, executed.stderr

    @staticmethod
    def sanitizer_environment(compiler: str) -> dict[str, str] | None:
        """Keep Apple's ASan runtime outside an enclosing Nix toolchain."""
        if sys.platform != "darwin" or os.path.realpath(compiler) != "/usr/bin/clang":
            return None
        environment = {
            name: os.environ[name]
            for name in (
                "HOME",
                "USER",
                "LOGNAME",
                "LANG",
                "LC_ALL",
                "LC_CTYPE",
            )
            if name in os.environ
        }
        environment.update(
            {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "TMPDIR": "/tmp",
                "ASAN_OPTIONS": "abort_on_error=1",
            }
        )
        return environment


def test_source_static_method_callback_preserves_owned_return_abi():
    emitted = emit_c(
        """
        class Factory {
            static string make() { return f"owned={1}"; }
        }
        int main() {
            __fn_ptr<string> callback = Factory.make;
            string value = callback();
            return 0;
        }
        """
    )

    main = emitted[emitted.index("int main(void) {") :]
    assert "char* value = callback();" in main
    assert "__btrc_string_retain(value)" not in main
    assert "__btrc_string_release" in main


def test_bodyless_static_method_keeps_foreign_return_abi():
    method = SimpleNamespace(access="class", body=None)
    owner = _callable_owner(
        class_table={"Foreign": SimpleNamespace(methods={"make": method})},
    )
    expression = FieldAccessExpr(obj=Identifier(name="Foreign"), field="make")

    assert owner.return_abi(expression) is CallableReturnABI.BORROWED


def test_generic_bodyless_function_return_is_promoted_to_owned():
    emitted = emit_c(
        """
        extern string foreignString();
        class Wrap<T> {
            public Wrap() {}
            public string get() { return foreignString(); }
        }
        int main() {
            Wrap<int> wrap = new Wrap<int>();
            string value = wrap.get();
            return 0;
        }
        """
    )

    method = emitted.split(
        "static char* btrc_Wrap_int_get(btrc_Wrap_int* self) {",
        1,
    )[1].split("\n}", 1)[0]
    assert "__btrc_string_retain" in method


def test_generic_source_callback_return_keeps_owned_abi():
    emitted = emit_c(
        """
        string make() { return f"owned={1}"; }
        class Wrap<T> {
            public Wrap() {}
            public string get() {
                __fn_ptr<string> callback = make;
                return callback();
            }
        }
        int main() {
            Wrap<int> wrap = new Wrap<int>();
            string value = wrap.get();
            return 0;
        }
        """
    )

    method = emitted.split(
        "static char* btrc_Wrap_int_get(btrc_Wrap_int* self) {",
        1,
    )[1].split("\n}", 1)[0]
    assert "return callback();" in method
    assert "__btrc_string_retain" not in method


def test_authenticated_hosted_call_precedes_generic_source_shadow():
    call = CallExpr(callee=Identifier(name="hostedString"), args=[])
    declaration = SimpleNamespace(body=object())
    owner = _callable_owner(
        function_table={"hostedString": declaration},
        hosted_call_ids={id(call)},
    )

    assert not owner.call_returns_owned(call)


def test_null_coalescing_joins_callable_return_abi():
    owner = _callable_owner(
        function_table={"owned": SimpleNamespace(body=object())},
    )

    expression = BinaryExpr(
        left=Identifier(name="owned"),
        op="??",
        right=Identifier(name="foreign"),
    )

    assert owner.return_abi(expression) is CallableReturnABI.AMBIGUOUS


def test_local_shadow_blocks_static_method_callable_provenance():
    owner = _callable_owner(
        class_table={
            "Factory": SimpleNamespace(
                methods={
                    "make": SimpleNamespace(
                        access="class",
                        body=object(),
                    )
                }
            )
        },
        local_names={"Factory"},
    )

    expression = FieldAccessExpr(
        obj=Identifier(name="Factory"),
        field="make",
    )

    assert owner.return_abi(expression) is CallableReturnABI.BORROWED


def test_generic_thread_and_interface_calls_use_owned_return_abi():
    thread = Identifier(name="thread")
    service = Identifier(name="service")
    thread_type = TypeExpr(
        base="Thread",
        generic_args=[TypeExpr(base="string")],
    )
    interface_type = TypeExpr(base="Service")
    types = {
        id(thread): thread_type,
        id(service): interface_type,
    }
    owner = _callable_owner(
        interface_table={
            "Service": InterfaceInfo(
                name="Service",
                methods={"load": object()},
            )
        },
        node_types=types,
        local_names={"thread", "service"},
    )

    assert owner.call_returns_owned(
        CallExpr(
            callee=FieldAccessExpr(obj=thread, field="join"),
            args=[],
        )
    )
    assert owner.call_returns_owned(
        CallExpr(
            callee=FieldAccessExpr(obj=service, field="load"),
            args=[],
        )
    )


@pytest.mark.parametrize(
    "storage_type",
    (
        TypeExpr(
            base="__fn_ptr",
            generic_args=[TypeExpr(base="string")],
            pointer_depth=1,
        ),
        TypeExpr(
            base="__fn_ptr",
            generic_args=[TypeExpr(base="string")],
            is_array=True,
        ),
    ),
    ids=("pointer-to-function-pointer", "function-pointer-array"),
)
def test_indirect_function_pointer_storage_is_not_a_callable_value(storage_type):
    assert not _callable_owner().is_callable(storage_type)


@pytest.mark.parametrize(
    "replacement",
    (
        "(int value) => value",
        "(int value) => value + offset",
    ),
)
def test_analyzer_rejects_environment_callable_reassignment(replacement):
    analyzed = analyze(
        f"""
        int run() {{
            int offset = 3;
            var callback = (int value) => value + offset;
            callback = {replacement};
            return callback(1);
        }}
        """
    )

    assert any("environment-bearing callable local cannot be reassigned" in error for error in analyzed.errors)


def test_exception_flow_through_inner_shadow_preserves_outer_callable_binding():
    callable_type = TypeExpr(
        base="__fn_ptr",
        generic_args=[TypeExpr(base="string")],
    )
    owner = _callable_owner(
        function_table={"make": SimpleNamespace(body=object())},
    )
    owner.bind_with_abi("callback", callable_type, CallableReturnABI.OWNED)
    expected = owner.snapshot().bindings["callback"]
    capture = owner.begin_exception_capture()
    scope = owner.begin_scope()
    owner.bind_borrowed("callback", callable_type)
    owner.record_exceptional_flow()
    owner.finish_scope(scope)

    states = owner.finish_exception_capture(capture)

    assert states
    assert all(state.bindings["callback"] == expected for state in states)


def test_loop_exit_through_inner_shadow_preserves_outer_callable_binding():
    callable_type = TypeExpr(
        base="__fn_ptr",
        generic_args=[TypeExpr(base="string")],
    )
    owner = _callable_owner(
        function_table={"make": SimpleNamespace(body=object())},
    )
    owner.bind_with_abi("callback", callable_type, CallableReturnABI.OWNED)
    expected = owner.snapshot().bindings["callback"]
    capture = owner.begin_loop_capture()
    scope = owner.begin_scope()
    owner.bind_borrowed("callback", callable_type)
    owner.record_control_exit("break", ["loop"])
    owner.finish_scope(scope)

    break_states, continue_states = owner.finish_loop_capture(capture)

    assert [state.bindings["callback"] for state in break_states] == [expected]
    assert not continue_states


def test_switch_exit_through_inner_callable_shadow_preserves_outer_binding():
    callable_type = TypeExpr(
        base="__fn_ptr",
        generic_args=[TypeExpr(base="string")],
    )
    owner = _callable_owner(
        function_table={"make": SimpleNamespace(body=object())},
    )
    owner.bind_local("callback", callable_type, Identifier(name="make"))
    expected = owner.snapshot().bindings["callback"]
    capture = owner.begin_switch_capture()
    scope = owner.begin_scope()
    owner.bind_borrowed("callback", callable_type)
    owner.record_control_exit("break", ["switch"])
    owner.finish_scope(scope)

    break_states = owner.finish_switch_capture(capture)

    assert [state.bindings["callback"] for state in break_states] == [expected]


def test_shadow_restores_outer_callable_mutation_made_before_declaration():
    callable_type = TypeExpr(
        base="__fn_ptr",
        generic_args=[TypeExpr(base="string")],
    )
    owner = _callable_owner(
        function_table={"make": SimpleNamespace(body=object())},
    )
    owner.bind_borrowed("callback", callable_type)
    scope = owner.begin_scope()
    owner.rebind_assignment(
        AssignExpr(
            target=Identifier(name="callback"),
            op="=",
            value=Identifier(name="make"),
        )
    )
    expected = owner.snapshot().bindings["callback"]
    owner.bind_borrowed("callback", callable_type)
    owner.finish_scope(scope)

    assert owner.snapshot().bindings["callback"] == expected


def test_invalid_callable_return_abi_is_rejected():
    owner = _callable_owner()

    with pytest.raises(ValueError):
        owner.bind_with_abi(
            "callback",
            TypeExpr(
                base="__fn_ptr",
                generic_args=[TypeExpr(base="string")],
            ),
            "invalid",
        )


@pytest.mark.skipif(
    not STRICT_C_COMPILERS,
    reason="requires a strict C11 compiler",
)
@pytest.mark.parametrize(
    "c_compiler",
    STRICT_C_COMPILERS,
    ids=lambda path: Path(path).name,
)
def test_callable_runtime_is_strict_c11_clean(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    CallableRuntimeHarness.build_and_run(
        tmp_path,
        c_compiler,
        "-O2",
    )


@pytest.mark.skipif(
    ASAN_COMPILER is None,
    reason="requires AddressSanitizer",
)
def test_callable_runtime_is_address_sanitizer_clean(tmp_path: Path) -> None:
    assert ASAN_COMPILER is not None
    CallableRuntimeHarness.build_and_run(
        tmp_path,
        ASAN_COMPILER,
        "-O1",
        "-fsanitize=address",
        "-fno-omit-frame-pointer",
        source_text=CallableRuntimeHarness.SANITIZER_SOURCE,
        environment=CallableRuntimeHarness.sanitizer_environment(ASAN_COMPILER),
    )


def test_catch_joins_intermediate_callback_state_before_throw():
    with pytest.raises(CodegenError, match="ambiguous ownership ABI"):
        emit_c(
            """
            extern string foreignString();
            void fail() { throw "stop"; }
            int main() {
                __fn_ptr<string> callback = foreignString;
                try {
                    callback = () => f"owned={1}";
                    fail();
                    callback = foreignString;
                } catch (string error) {
                    string value = callback();
                }
                return 0;
            }
            """
        )


def test_switch_fallthrough_composes_callback_provenance():
    with pytest.raises(CodegenError, match="ambiguous ownership ABI"):
        emit_c(
            """
            extern string foreignString();
            int main() {
                __fn_ptr<string> callback = foreignString;
                switch (1) {
                    case 1:
                        callback = () => f"owned={1}";
                    case 2:
                        string value = callback();
                        break;
                    default:
                        break;
                }
                return 0;
            }
            """
        )


def test_typedef_receiver_property_is_observable_for_sequencing():
    receiver = Identifier(name="counter")
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={"Counter": ClassInfo(name="Counter", properties={"next": object()})},
        typedef_table={"Alias": TypeExpr(base="Counter")},
        node_types={id(receiver): TypeExpr(base="Alias")},
    )
    session = LoweringSession(module=IRModule(), node_types=analyzed.node_types)
    identity = TypeIdentity()
    types = CTypeLowerer(session, analyzed, identity)
    values = ManagedValueSemantics(analyzed, identity, types)
    cycles = CycleMetadata(analyzed, values, identity)
    cleanup_slots = CleanupSlotRegistry(session)
    cleanup_scope = CleanupScopeState(session, cross_function_enabled=False)
    lifetime = ManagedLifetimeLowerer(
        context=session,
        analyzed=analyzed,
        values=values,
        cycles=cycles,
        cleanup_slots=cleanup_slots,
        cleanup_scope=cleanup_scope,
        types=types,
    )
    owner = OwnershipLowerer(
        session,
        analyzed,
        types,
        IndexedProtocolResolver(identity, analyzed.class_table),
        values,
        cycles,
        lifetime,
        cleanup_scope,
        program_has_exceptions=False,
    )
    expression = FieldAccessExpr(obj=receiver, field="next")

    assert owner.has_observable_effect(expression)


@pytest.mark.parametrize(
    "expression",
    (
        "choose && ((callback = make) != null)",
        "choose || ((callback = make) != null)",
        "choose ? (callback = make) : callback",
    ),
)
@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_expression_control_flow_joins_callable_abi(expression, generic):
    body = f"""
        __fn_ptr<string> callback = foreignString;
        {expression};
        string value = callback();
        return len(value);
    """
    if generic:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run(bool choose) {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run(false);
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            int run(bool choose) {{ {body} }}
            int main() {{ return run(false); }}
        """

    with pytest.raises(CodegenError, match="ambiguous ownership ABI"):
        emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_ordered_call_uses_callee_abi_from_before_argument_effects(generic):
    body = """
        __fn_ptr<string, bool> callback = foreign;
        string value = callback((bool)(callback = make));
        return len(value);
    """
    if generic:
        source = f"""
            extern string foreign(bool ignored);
            string make(bool ignored) {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    else:
        source = f"""
            extern string foreign(bool ignored);
            string make(bool ignored) {{ return f"owned={{1}}"; }}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """

    emitted = emit_c(source)
    function_marker = "static int btrc_Wrap_int_run(" if generic else "int run(void) {"
    function = emitted[emitted.index(function_marker) :]
    assert "__btrc_string_retain(value)" in function


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_assignment_expression_propagates_owned_callable_abi(generic):
    body = """
        __fn_ptr<string> first = foreignString;
        __fn_ptr<string> second = (first = make);
        string value = second();
        return len(value);
    """
    if generic:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """

    emitted = emit_c(source)
    function_marker = "static int btrc_Wrap_int_run(" if generic else "int run(void) {"
    function = emitted[emitted.index(function_marker) :]
    assert "__btrc_string_retain(value)" not in function


def test_struct_callable_slot_rejects_environment_bearing_value_in_analyzer():
    analyzed = analyze(
        """
        struct Holder { __fn_ptr<int, int> callback; };
        int run() {
            int offset = 3;
            struct Holder holder = {(int value) => value + offset};
            return 0;
        }
        """
    )

    assert any("environment-requiring callable value" in error for error in analyzed.errors)


@pytest.mark.parametrize(
    "boundary",
    (
        "__fn_ptr<string> callback = factory.make;",
        "consume(factory.make);",
        "return factory.make;",
    ),
)
def test_bound_instance_method_value_is_rejected(boundary):
    if boundary.startswith("return"):
        function = f"__fn_ptr<string> run(Factory factory) {{ {boundary} }}"
        main = "int main() { Factory factory = new Factory(); run(factory); return 0; }"
    else:
        function = f"""
            int consume(__fn_ptr<string> callback) {{ return 0; }}
            int run(Factory factory) {{ {boundary} return 0; }}
        """
        main = "int main() { Factory factory = new Factory(); return run(factory); }"
    analyzed = analyze(
        f"""
        class Factory {{
            public Factory() {{}}
            public string make() {{ return f"owned={{1}}"; }}
        }}
        {function}
        {main}
        """
    )

    assert any("environment-requiring callable value" in error for error in analyzed.errors)


def test_direct_instance_method_call_and_static_method_value_remain_valid():
    analyzed = analyze(
        """
        class Factory {
            public Factory() {}
            public string make() { return f"owned={1}"; }
            static string staticMake() { return f"static={1}"; }
        }
        int main() {
            Factory factory = new Factory();
            string direct = factory.make();
            __fn_ptr<string> callback = Factory.staticMake;
            string indirect = callback();
            return len(direct) + len(indirect);
        }
        """
    )

    assert not analyzed.errors


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_non_fallthrough_if_branch_does_not_poison_continuation(generic):
    body = """
        __fn_ptr<string> callback = foreignString;
        if (choose) {
            callback = make;
            string owned = callback();
            return len(owned);
        }
        string value = callback();
        return len(value);
    """
    if generic:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run(bool choose) {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run(false);
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            int run(bool choose) {{ {body} }}
            int main() {{ return run(false); }}
        """

    emitted = emit_c(source)
    function_marker = "static int btrc_Wrap_int_run(" if generic else "int run(bool choose) {"
    function = emitted[emitted.index(function_marker) :]
    assert "__btrc_string_retain(value)" in function


@pytest.mark.parametrize(
    "loop",
    (
        "while (index < 2) { string value = callback(); callback = make; index++; }",
        "do { string value = callback(); callback = make; index++; } while (index < 2);",
        "do { string value = callback(); callback = make; index++; } while (true);",
        "for (index = 0; index < 2; index++) { string value = callback(); callback = make; }",
    ),
)
@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_loop_carried_callable_abi_change_fails_closed(loop, generic):
    body = f"""
        __fn_ptr<string> callback = foreignString;
        int index = 0;
        {loop}
        return 0;
    """
    if generic:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """

    with pytest.raises(CodegenError, match="invariant across a repeated loop"):
        emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_literal_true_do_while_propagates_only_reachable_break_flow(generic):
    body = """
        __fn_ptr<string> callback = foreignString;
        do {
            if (stop) {
                callback = make;
                break;
            }
        } while (true);
        string value = callback();
        return len(value);
    """
    if generic:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run(bool stop) {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run(true);
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            int run(bool stop) {{ {body} }}
            int main() {{ return run(true); }}
        """

    emit_c(source)


def test_do_while_break_bypasses_condition_callable_flow():
    with pytest.raises(CodegenError, match="ambiguous ownership ABI"):
        emit_c(
            """
            extern string foreignString();
            string make() { return f"owned={1}"; }
            int main() {
                bool stop = true;
                __fn_ptr<string> callback = foreignString;
                do {
                    if (stop) {
                        callback = make;
                        break;
                    }
                } while ((callback = foreignString) != null);
                string value = callback();
                return 0;
            }
            """
        )


def test_ir_completion_uses_structured_never_returns_metadata():
    assert not IRStatementSequence(
        [
            IRExprStmt(
                expr=IRCall(
                    callee="arbitrary_symbol",
                    never_returns=True,
                )
            )
        ]
    ).may_fall_through()


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_non_fallthrough_catch_does_not_poison_try_continuation(generic):
    body = """
        __fn_ptr<string> callback = foreignString;
        try {
            int untouched = 0;
        } catch (string error) {
            callback = make;
            return 1;
        }
        string value = callback();
        return len(value);
    """
    if generic:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """

    emitted = emit_c(source)
    function_marker = "static int btrc_Wrap_int_run(" if generic else "int run(void) {"
    function = emitted[emitted.index(function_marker) :]
    assert "__btrc_string_retain(value)" in function


def test_switch_return_state_is_excluded_but_break_state_reaches_continuation():
    emitted = emit_c(
        """
        extern string foreignString();
        string make() { return f"owned={1}"; }
        int run(int choice) {
            __fn_ptr<string> callback = foreignString;
            switch (choice) {
                case 1:
                    callback = make;
                    return 1;
                default:
                    break;
            }
            string value = callback();
            return len(value);
        }
        int main() { return run(0); }
        """
    )
    function = emitted[emitted.index("int run(int choice) {") :]
    assert "__btrc_string_retain(value)" in function

    with pytest.raises(CodegenError, match="ambiguous ownership ABI"):
        emit_c(
            """
            extern string foreignString();
            string make() { return f"owned={1}"; }
            int run(int choice) {
                __fn_ptr<string> callback = foreignString;
                switch (choice) {
                    case 1:
                        callback = make;
                        break;
                    default:
                        break;
                }
                string value = callback();
                return len(value);
            }
            int main() { return run(0); }
            """
        )


def test_loop_update_and_do_condition_may_normalize_backedge_abi():
    emit_c(
        """
        extern string foreignString();
        string make() { return f"owned={1}"; }
        int main() {
            __fn_ptr<string> callback = foreignString;
            for (int index = 0; index < 2; callback = foreignString) {
                callback = make;
                index++;
            }
            do {
                callback = make;
            } while ((callback = foreignString) == null);
            string value = callback();
            return len(value);
        }
        """
    )


def test_managed_callable_address_escape_has_one_primary_diagnostic():
    analyzed = analyze(
        """
        extern void mutate(void* slot);
        string make() { return f"owned={1}"; }
        int main() {
            __fn_ptr<string> callback = make;
            mutate((void*)&callback);
            return 0;
        }
        """
    )

    matching = [error for error in analyzed.errors if "Managed-return callable storage cannot be addressed" in error]
    assert len(matching) == 1
    assert not any("Function pointers cannot be cast" in error for error in analyzed.errors)


def test_pointer_to_function_pointer_storage_remains_a_legal_object_pointer_cast():
    analyzed = analyze(
        """
        int main() {
            __fn_ptr<int>* callback_slot = null;
            void* erased = (void*)callback_slot;
            return erased == null ? 0 : 1;
        }
        """
    )

    assert not analyzed.errors


def test_direct_function_pointer_to_object_pointer_cast_is_rejected():
    analyzed = analyze(
        """
        int make() { return 1; }
        int main() {
            __fn_ptr<int> callback = make;
            void* erased = (void*)callback;
            return erased == null ? 0 : 1;
        }
        """
    )

    assert any(
        "Function pointers cannot be cast to or from object pointers or integer values in strict C11" in error
        for error in analyzed.errors
    )


@pytest.mark.parametrize(
    "body",
    (
        "stash(callback);",
        "stash((void*)callback);",
    ),
)
def test_managed_return_callable_cannot_cross_erased_call_argument(body):
    analyzed = analyze(
        f"""
        extern void stash(void* value);
        string make() {{ return f"owned={{1}}"; }}
        int main() {{
            __fn_ptr<string> callback = make;
            {body}
            return 0;
        }}
        """
    )

    assert any(
        "Managed-return callable cannot cross an erased or opaque value boundary" in error for error in analyzed.errors
    )


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_effectful_callee_is_classified_after_its_own_evaluation(generic):
    body = """
        __fn_ptr<string> callback = foreignString;
        string value = ((bool)(callback = make) ? callback : callback)();
        return len(value);
    """
    if generic:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """

    emitted = emit_c(source)
    marker = "static int btrc_Wrap_int_run(" if generic else "int run(void) {"
    function = emitted[emitted.index(marker) :]
    assert "__btrc_string_retain(value)" not in function


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_conditional_result_ownership_uses_post_condition_callable_state(generic):
    body = """
        __fn_ptr<string> callback = foreignString;
        string value = ((bool)(callback = make) ? callback() : foreignString());
        return len(value);
    """
    if generic:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """

    emitted = emit_c(source)
    marker = "static int btrc_Wrap_int_run(" if generic else "int run(void) {"
    function = emitted[emitted.index(marker) :]
    assert "__btrc_string_retain" in function


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_effectful_conditional_receiver_uses_post_condition_ownership(generic):
    body = """
        __fn_ptr<string> callback = foreignString;
        int value = ((bool)(callback = make) ? callback() : foreignString()).length();
        return value;
    """
    if generic:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """

    emitted = emit_c(source)
    marker = "static int btrc_Wrap_int_run(" if generic else "int run(void) {"
    function = emitted[emitted.index(marker) :]
    assert "__btrc_string_release" in function


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_finally_only_rethrow_edge_does_not_poison_normal_continuation(generic):
    body = """
        __fn_ptr<string> callback = foreignString;
        try {
            mayThrow();
            callback = make;
        } finally {
        }
        string value = callback();
        return len(value);
    """
    if generic:
        source = f"""
            extern string foreignString();
            extern void mayThrow();
            string make() {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            extern void mayThrow();
            string make() {{ return f"owned={{1}}"; }}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """

    emitted = emit_c(source)
    marker = "static int btrc_Wrap_int_run(" if generic else "int run(void) {"
    function = emitted[emitted.index(marker) :]
    assert "__btrc_string_retain(value)" not in function


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_persistent_callback_return_uses_post_evaluation_abi(generic):
    body = """
        __fn_ptr<string> callback = foreignString;
        return ((bool)(callback = make) ? callback : foreignString);
    """
    if generic:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public __fn_ptr<string> exportCallback() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                wrap.exportCallback();
                return 0;
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            __fn_ptr<string> exportCallback() {{ {body} }}
            int main() {{ exportCallback(); return 0; }}
        """

    with pytest.raises(CodegenError, match="Managed-return callback cannot cross a function return"):
        emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
@pytest.mark.parametrize("boundary", ("global", "field"))
def test_persistent_callback_store_uses_post_evaluation_abi(generic, boundary):
    value = "((bool)(callback = make) ? callback : foreignString)"
    if boundary == "global":
        declaration = "__fn_ptr<string> stored = foreignString;"
        setup = ""
        store = f"stored = {value};"
    else:
        declaration = """
            class Holder {
                public __fn_ptr<string> callback;
                public Holder() { self.callback = foreignString; }
            }
        """
        setup = "Holder holder = new Holder();"
        store = f"holder.callback = {value};"
    body = f"""
        {setup}
        __fn_ptr<string> callback = foreignString;
        {store}
        return 0;
    """
    if generic:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            {declaration}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            string make() {{ return f"owned={{1}}"; }}
            {declaration}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """

    with pytest.raises(
        CodegenError,
        match=r"Managed-return callback cannot cross (global|field) storage",
    ):
        emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_null_coalescing_rhs_ownership_uses_post_left_callable_state(generic):
    body = """
        __fn_ptr<string> callback = foreignString;
        string value = missing((bool)(callback = make)) ?? callback();
        return len(value);
    """
    if generic:
        source = f"""
            extern string foreignString();
            extern string? missing(bool ignored);
            string make() {{ return f"owned={{1}}"; }}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    else:
        source = f"""
            extern string foreignString();
            extern string? missing(bool ignored);
            string make() {{ return f"owned={{1}}"; }}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """

    emitted = emit_c(source)
    marker = "static int btrc_Wrap_int_run(" if generic else "int run(void) {"
    function = emitted[emitted.index(marker) :]
    assert "__btrc_string_retain" in function


def test_ir_switch_completion_uses_structured_fallthrough_metadata():
    assert not IRStatementSequence(
        [
            IRSwitch(
                can_fall_through=False,
            )
        ]
    ).may_fall_through()
