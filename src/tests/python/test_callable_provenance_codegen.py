"""Managed-return callback provenance across nontrivial source control flow."""

from types import SimpleNamespace

import pytest

from src.compiler.python.ast_nodes import CallExpr, FieldAccessExpr, Identifier, TypeExpr
from src.compiler.python.ir.gen.callable_provenance import (
    BORROWED_RETURN,
    callable_return_abi,
)
from src.compiler.python.ir.gen.errors import CodegenError
from src.compiler.python.ir.gen.evaluation_order import has_observable_effect
from src.compiler.python.ir.gen.generics.user_callable_provenance import (
    generic_known_language_call,
)
from src.tests.python.test_codegen import emit_c


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
    analyzed = SimpleNamespace(
        class_table={"Foreign": SimpleNamespace(methods={"make": method})},
        function_table={},
    )
    context = SimpleNamespace(analyzed=analyzed, callable_return_abis={})
    expression = FieldAccessExpr(obj=Identifier(name="Foreign"), field="make")

    assert callable_return_abi(context, expression) == BORROWED_RETURN


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
    analyzed = SimpleNamespace(
        class_table={},
        function_table={"hostedString": declaration},
        hosted_call_ids={id(call)},
    )
    emitter = SimpleNamespace(
        _gen=SimpleNamespace(analyzed=analyzed),
        _var_types={},
    )

    assert not generic_known_language_call(emitter, call)


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
    class_info = SimpleNamespace(properties={"next": object()})
    analyzed = SimpleNamespace(
        class_table={"Counter": class_info},
        typedef_table={"Alias": TypeExpr(base="Counter")},
    )
    gen = SimpleNamespace(analyzed=analyzed)
    receiver = Identifier(name="counter")
    expression = FieldAccessExpr(obj=receiver, field="next")

    assert has_observable_effect(
        gen,
        expression,
        type_of=lambda node: TypeExpr(base="Alias") if node is receiver else None,
    )
