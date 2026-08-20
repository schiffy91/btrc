"""Source-ordered callable validation at persistent storage boundaries."""

import re
from types import SimpleNamespace

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.ir.lowering.calls import (
    CallableProvenance,
    CallableReturnABI,
    CallableSignatureLowerer,
)
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.lowering.session import LoweringSession
from src.compiler.python.ir.lowering.types import CodegenError, CTypeLowerer
from src.compiler.python.ir.nodes import IRModule
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import AssignExpr, Identifier, Program, TypeExpr
from src.tests.python.test_codegen import emit_c


def _assert_value_initializer_promotes_call_result(function: str) -> None:
    declarations = [line for line in function.splitlines() if re.search(r"\bvalue\s*=", line)]
    for declaration in declarations:
        result = re.search(r"(?P<name>__btrc_call_result_\d+)\s*=", declaration)
        if result is not None and f"__btrc_string_retain({result.group('name')})" in declaration:
            return
    raise AssertionError("value initializer did not promote its borrowed call-result temporary")


def _callable_owner(
    *,
    function_table: dict[str, object] | None = None,
    node_types: dict[int, TypeExpr] | None = None,
    local_names: set[str] | None = None,
) -> CallableProvenance:
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={},
        function_table=dict(function_table or {}),
        node_types=dict(node_types or {}),
    )
    session = LoweringSession(module=IRModule(), node_types=analyzed.node_types)
    if local_names:
        session.local_ownership_scopes.append(dict.fromkeys(local_names))
    types = CTypeLowerer(session, analyzed)
    return CallableProvenance(analyzed, session, types, CallableSignatureLowerer(analyzed, types))


def _program(body: str, *, generic: bool) -> str:
    declarations = """
        extern string foreignString();
        string make() { return f"owned={1}"; }
        struct CallbackSlot { __fn_ptr<string> callback; };
        struct CallbackRecord {
            bool ignored;
            CallbackSlot slot;
        };
        class Holder {
            public __fn_ptr<string> callback;
            public Holder() { self.callback = foreignString; }
        }
        Holder selectHolder(Holder holder, bool ignored) {
            return holder;
        }
        int consumeCallback(__fn_ptr<string> callback) { return 0; }
        int consume(bool ignored, __fn_ptr<string> callback) {
            return 0;
        }
    """
    if not generic:
        return f"""
            {declarations}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """
    return f"""
        {declarations}
        class Wrap<T> {{
            public Wrap() {{}}
            public int run() {{ {body} }}
        }}
        int main() {{
            Wrap<int> wrap = new Wrap<int>();
            return wrap.run();
        }}
    """


def _lower_ir(source: str) -> IRModule:
    program = Parser(Lexer(source, "<callable-boundary>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors
    return IRLowerer(analyzed).lower()


def test_ordinary_method_classification_does_not_lower_callable_argument_twice():
    module = _lower_ir("""
        class Runner {
            public Runner() {}
            public int invoke(__fn_ptr<int, int> callback) {
                return callback(7);
            }
        }
        int main() {
            Runner runner = new Runner();
            return runner.invoke((int value) => value);
        }
    """)

    lambdas = [function.name for function in module.function_defs if function.name.startswith("__btrc_lambda_")]
    assert lambdas == ["__btrc_lambda_1"]


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_aggregate_callback_slot_observes_earlier_sibling_rebinding(generic):
    source = _program(
        """
            __fn_ptr<string> callback = foreignString;
            CallbackRecord record = {
                (bool)(callback = make),
                {callback}
            };
            return 0;
        """,
        generic=generic,
    )

    with pytest.raises(
        CodegenError,
        match="Managed-return callback cannot cross aggregate storage",
    ):
        emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_aggregate_callback_slot_accepts_later_borrowed_rebinding(generic):
    source = _program(
        """
            __fn_ptr<string> callback = make;
            CallbackRecord record = {
                (bool)(callback = foreignString),
                {callback}
            };
            return 0;
        """,
        generic=generic,
    )

    emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_assignment_rhs_observes_callback_rebinding_in_field_target(generic):
    source = _program(
        """
            __fn_ptr<string> callback = foreignString;
            Holder holder = new Holder();
            selectHolder(
                holder,
                (bool)(callback = make)
            ).callback = callback;
            return 0;
        """,
        generic=generic,
    )

    with pytest.raises(
        CodegenError,
        match="Managed-return callback cannot cross field storage",
    ):
        emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_assignment_rhs_accepts_borrowed_rebinding_in_field_target(generic):
    source = _program(
        """
            __fn_ptr<string> callback = make;
            Holder holder = new Holder();
            selectHolder(
                holder,
                (bool)(callback = foreignString)
            ).callback = callback;
            return 0;
        """,
        generic=generic,
    )

    emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_callback_argument_observes_earlier_callee_rebinding(generic):
    source = _program(
        """
            __fn_ptr<string> callback = foreignString;
            ((bool)(callback = make) ? consumeCallback : consumeCallback)(callback);
            return 0;
        """,
        generic=generic,
    )

    with pytest.raises(
        CodegenError,
        match="Managed-return callback for parameter 1 erases",
    ):
        emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_callback_argument_accepts_earlier_borrowed_callee_rebinding(generic):
    source = _program(
        """
            __fn_ptr<string> callback = make;
            ((bool)(callback = foreignString) ? consumeCallback : consumeCallback)(callback);
            return 0;
        """,
        generic=generic,
    )

    emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_callback_argument_observes_earlier_argument_rebinding(generic):
    source = _program(
        """
            __fn_ptr<string> callback = foreignString;
            return consume(
                (bool)(callback = make),
                callback
            );
        """,
        generic=generic,
    )

    with pytest.raises(
        CodegenError,
        match="bare __fn_ptr parameters accept only borrowed C callbacks",
    ):
        emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_callback_argument_accepts_earlier_borrowed_rebinding(generic):
    source = _program(
        """
            __fn_ptr<string> callback = make;
            return consume(
                (bool)(callback = foreignString),
                callback
            );
        """,
        generic=generic,
    )

    emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_compiler_owned_comparison_preserves_borrowed_callback_type(generic):
    source = _program(
        """
            __fn_ptr<string> callback = foreignString;
            return __btrc_eq(callback, foreignString) ? 0 : 1;
        """,
        generic=generic,
    )

    emit_c(source)


def test_called_generic_specialization_cannot_erase_borrowed_callback():
    source = """
        extern string foreignString();
        class Probe<T> {
            public Probe() {}
            public int erase(T value) {
                return __btrc_string_length(value);
            }
        }
        int main() {
            Probe<__fn_ptr<string>> probe = new Probe<__fn_ptr<string>>();
            return probe.erase(foreignString);
        }
    """

    with pytest.raises(
        CodegenError,
        match="an erased or opaque value cannot preserve its return ownership ABI",
    ):
        emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_default_helper_assignment_does_not_rebind_same_named_caller_local(generic):
    declarations = """
        extern string foreignString();
        string make() { return f"owned={1}"; }
        int consumeDefault(
            __fn_ptr<string> callback,
            bool ignored = ((callback = make) != null)
        ) {
            return ignored ? 1 : 0;
        }
    """
    body = """
        __fn_ptr<string> callback = foreignString;
        consumeDefault(callback);
        string value = callback();
        return len(value);
    """
    source = (
        f"""
            {declarations}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """
        if not generic
        else f"""
            {declarations}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    )

    emitted = emit_c(source)
    marker = "static int btrc_Wrap_int_run(btrc_Wrap_int* self) {" if generic else "int run(void) {"
    function = emitted[emitted.index(marker) :]
    _assert_value_initializer_promotes_call_result(function)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_nested_constructor_arguments_update_later_outer_call_operands(generic):
    declarations = """
        extern string foreignString();
        string make() { return f"owned={1}"; }
        class Marker {
            public Marker(bool ignored) {}
        }
        void consumeMarker(Marker marker, string value) {}
    """
    body = """
        __fn_ptr<string> callback = make;
        consumeMarker(
            new Marker((bool)(callback = foreignString)),
            callback()
        );
        string value = callback();
        return len(value);
    """
    source = (
        f"""
            {declarations}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """
        if not generic
        else f"""
            {declarations}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    )

    emitted = emit_c(source)
    marker = "static int btrc_Wrap_int_run(btrc_Wrap_int* self) {" if generic else "int run(void) {"
    function = emitted[emitted.index(marker) :]
    _assert_value_initializer_promotes_call_result(function)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_callable_boundary_observes_rebinding_inside_earlier_deferred_projection(generic):
    declarations = """
        extern string foreignString();
        string make() { return f"owned={1}"; }
        class ProjectionHolder {
            public int values[1];
            public ProjectionHolder(bool initialized) {
                self.values[0] = initialized ? 1 : 0;
            }
        }
        ProjectionHolder makeProjectionHolder(bool initialized) {
            return new ProjectionHolder(initialized);
        }
        void consumeProjectionCallback(int[] values, __fn_ptr<string> callback) {}
    """
    body = """
        __fn_ptr<string> callback = foreignString;
        consumeProjectionCallback(
            makeProjectionHolder((bool)(callback = make)).values,
            callback
        );
        return 0;
    """
    source = (
        f"""
            {declarations}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """
        if not generic
        else f"""
            {declarations}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    )

    with pytest.raises(
        CodegenError,
        match="bare __fn_ptr parameters accept only borrowed C callbacks",
    ):
        emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
@pytest.mark.parametrize(
    "receiver_initializer",
    ("null", "new Maybe()"),
    ids=("null-receiver", "non-null-receiver"),
)
def test_nested_optional_call_joins_skipped_argument_rebinding(
    generic,
    receiver_initializer,
):
    declarations = """
        extern string foreignString();
        string make() { return f"owned={1}"; }
        class Maybe {
            public Maybe() {}
            public int touch(bool ignored) { return ignored ? 1 : 0; }
        }
        void consumeOptional(int ignored, string value) {}
    """
    body = f"""
        Maybe? maybe = {receiver_initializer};
        __fn_ptr<string> callback = foreignString;
        consumeOptional(
            maybe?.touch((bool)(callback = make)),
            callback()
        );
        return 0;
    """
    source = (
        f"""
            {declarations}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """
        if not generic
        else f"""
            {declarations}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    )

    with pytest.raises(CodegenError, match="ambiguous ownership ABI"):
        emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_default_callback_parameter_uses_declaration_scope_not_caller_names(generic):
    declarations = """
        extern string foreignString();
        string make() { return f"owned={1}"; }
        int invokeDefault(
            __fn_ptr<string> input,
            __fn_ptr<string> output = input
        ) {
            string value = output();
            return len(value);
        }
    """
    body = """
        __fn_ptr<string> input = make;
        return invokeDefault(foreignString);
    """
    source = (
        f"""
            {declarations}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """
        if not generic
        else f"""
            {declarations}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    )

    emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_default_prior_callable_parameter_uses_its_argument_source_entry(generic):
    declarations = """
        extern string foreignString();
        string make() { return f"owned={1}"; }
        int invokeDefault(
            __fn_ptr<string> input,
            bool ignored,
            __fn_ptr<string> output = input
        ) {
            return len(output());
        }
    """
    body = """
        __fn_ptr<string> callback = foreignString;
        return invokeDefault(callback, (bool)(callback = make));
    """
    source = (
        f"""
            {declarations}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """
        if not generic
        else f"""
            {declarations}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    )

    emitted = emit_c(source)
    marker = "static int btrc_Wrap_int_run(" if generic else "int run(void) {"
    function = emitted[emitted.index(marker) :]
    captured = function.index("= callback")
    rebound = function.index("callback = make", captured)
    defaulted = function.index("__btrc_default_invokeDefault_3", rebound)
    assert captured < rebound < defaulted


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_default_global_callback_is_not_shadowed_by_same_named_caller_local(generic):
    declarations = """
        extern string foreignString();
        string make() { return f"owned={1}"; }
        int invokeDefault(__fn_ptr<string> output = foreignString) {
            string value = output();
            return len(value);
        }
    """
    body = """
        __fn_ptr<string> foreignString = make;
        return invokeDefault();
    """
    source = (
        f"""
            {declarations}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """
        if not generic
        else f"""
            {declarations}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    )

    emit_c(source)


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_managed_return_callback_default_is_rejected(generic):
    declarations = """
        string make() { return f"owned={1}"; }
        int invokeDefault(__fn_ptr<string> output = make) {
            return 0;
        }
    """
    body = "return invokeDefault();"
    source = (
        f"""
            {declarations}
            int run() {{ {body} }}
            int main() {{ return run(); }}
        """
        if not generic
        else f"""
            {declarations}
            class Wrap<T> {{
                public Wrap() {{}}
                public int run() {{ {body} }}
            }}
            int main() {{
                Wrap<int> wrap = new Wrap<int>();
                return wrap.run();
            }}
        """
    )

    with pytest.raises(
        CodegenError,
        match="bare __fn_ptr parameters accept only borrowed C callbacks",
    ):
        emit_c(source)


class TestCallableProvenanceQueryIsolation:
    """Abstract evaluation must not publish facts from a lowering dry run."""

    @staticmethod
    def _owner_and_assignment():
        callback_type = TypeExpr(
            base="__fn_ptr",
            generic_args=[TypeExpr(base="string")],
        )
        assignment = AssignExpr(
            target=Identifier(name="callback"),
            op="=",
            value=Identifier(name="make"),
        )
        owner = _callable_owner(
            function_table={"make": SimpleNamespace(body=object())},
            node_types={id(assignment.target): callback_type},
            local_names={"callback"},
        )
        owner.bind_local(
            "callback",
            callback_type,
            Identifier(name="foreignString"),
        )
        return owner, assignment

    @staticmethod
    def _begin_observers(owner):
        mutations = owner.begin_mutation_capture()
        exceptions = owner.begin_exception_capture()
        return mutations, exceptions, tuple(exceptions.states)

    @staticmethod
    def _assert_observers_unchanged(
        owner,
        mutations,
        exceptions,
        exception_states,
    ) -> None:
        assert not mutations.names
        assert tuple(exceptions.states) == exception_states
        owner.finish_exception_capture(exceptions)
        assert not owner.finish_mutation_capture(mutations)

    def test_plan_evaluation_does_not_publish_flow_observers(self):
        owner, assignment = self._owner_and_assignment()
        mutations, exceptions, exception_states = self._begin_observers(owner)

        plan = owner.plan_evaluation((assignment,))

        assert plan.outgoing.bindings["callback"].return_abi is CallableReturnABI.OWNED
        assert owner.return_abi_for_name("callback") is CallableReturnABI.BORROWED
        self._assert_observers_unchanged(
            owner,
            mutations,
            exceptions,
            exception_states,
        )

    def test_evaluated_return_abi_does_not_publish_flow_observers(self):
        owner, assignment = self._owner_and_assignment()
        mutations, exceptions, exception_states = self._begin_observers(owner)

        result = owner.evaluated_return_abi(assignment)

        assert result is CallableReturnABI.OWNED
        assert owner.return_abi_for_name("callback") is CallableReturnABI.BORROWED
        self._assert_observers_unchanged(
            owner,
            mutations,
            exceptions,
            exception_states,
        )


@pytest.mark.parametrize(
    "non_scalar_type",
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
def test_callable_provenance_accepts_only_scalar_function_pointer_values(
    non_scalar_type,
):
    assert not _callable_owner().is_callable(non_scalar_type)
