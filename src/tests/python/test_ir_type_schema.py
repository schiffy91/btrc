"""Resolved-type and symbolic-expression contracts for structured IR."""

from dataclasses import FrozenInstanceError

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.cycle_symbols import cycle_visitor_symbol
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.errors import CodegenError
from src.compiler.python.ir.gen.lowerer import IRLowerer
from src.compiler.python.ir.nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCast,
    IRFieldAccess,
    IRLiteral,
    IRModule,
    IRSizeof,
    IRVar,
)
from src.compiler.python.ir.optimizer_walk import IRTree
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(source: str):
    program = Parser(Lexer(source, "<ir-type-schema>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert analyzed.errors == []
    return analyzed


def _generate(source: str):
    return IRLowerer(_analyze(source)).lower()


@pytest.mark.parametrize(
    ("text", "error_type"),
    [
        (None, TypeError),
        (7, TypeError),
        ("", ValueError),
        (" int", ValueError),
        ("int ", ValueError),
        ("int\nlong", ValueError),
        ("int\0long", ValueError),
        ("int;", ValueError),
        ("struct { int value; }", ValueError),
    ],
)
def test_c_type_rejects_unresolved_or_declaration_shaped_text(text, error_type: type[Exception]):
    with pytest.raises(error_type):
        CType(text=text)


def test_c_type_is_an_immutable_resolved_value():
    c_type = CType(text="void (*)(int)")

    assert str(c_type) == "void (*)(int)"
    with pytest.raises(FrozenInstanceError):
        c_type.text = "int"


def test_cast_and_sizeof_require_typed_operands():
    value = IRVar(name="value")

    with pytest.raises(TypeError, match=r"IRCast\.target_type"):
        IRCast(target_type="int", expr=value)
    with pytest.raises(TypeError, match=r"IRCast\.expr"):
        IRCast(target_type=CType(text="int"), expr="value")
    with pytest.raises(TypeError, match=r"IRSizeof\.operand"):
        IRSizeof(operand="int")
    with pytest.raises(TypeError, match=r"IRSizeof\.operand"):
        IRSizeof(operand=None)

    emitter = CEmitter()
    assert emitter._expr(IRCast(CType("int"), value)) == "((int)value)"
    assert emitter._expr(IRSizeof(CType("int"))) == "sizeof(int)"
    assert emitter._expr(IRSizeof(value)) == "sizeof(value)"


@pytest.mark.parametrize(
    "field_name",
    (
        "preprocessor_decls",
        "struct_forwards",
        "function_pointer_typedefs",
        "function_decls",
        "helper_decls",
        "enum_defs",
        "typedef_defs",
        "tagged_union_defs",
        "struct_defs",
        "global_decls",
        "function_defs",
        "gpu_kernels",
    ),
)
def test_module_rejects_raw_top_level_declarations(field_name: str):
    module = IRModule()
    setattr(module, field_name, ["raw C"])

    with pytest.raises(TypeError, match=field_name):
        module.validate_declarations()


def test_generic_registry_uses_lexical_identity_not_parameter_spelling():
    analyzed = _analyze("""
        class Inner<Value> { public Value value; }
        class Outer<Element> {
            public Inner<Element> child;
            public Inner<Result> wrap<Result>(Result value) {
                Inner<Result> result;
                return result;
            }
        }
        int main() { Outer<int> value; return 0; }
    """)

    assert [args[0].base for args in analyzed.generic_instances["Inner"]] == ["int"]
    assert all(args[0].base != "Result" for args in analyzed.generic_instances["Inner"])
    assert [args[0].base for args in analyzed.generic_instances["Outer"]] == ["int"]


def test_real_multi_letter_nominal_type_is_a_concrete_generic_argument():
    analyzed = _analyze("""
        class Element {}
        class Box<Value> { public Value value; }
        void run() { Box<Element> value; }
    """)

    argument = analyzed.generic_instances["Box"][0][0]
    assert (argument.base, argument.pointer_depth) == ("Element", 1)


def test_generic_allocation_uses_structured_sizeof_type_operands():
    module = _generate("""
        class Crate<Element> {
            public Element value;
            public Crate(Element value) { self.value = value; }
        }
        int main() { Crate<int> crate = Crate(1); return 0; }
    """)
    constructor = next(function for function in module.function_defs if function.name == "btrc_Crate_int_new")
    nodes = list(IRTree(constructor))
    size_operands = [node.operand for node in nodes if isinstance(node, IRSizeof)]

    assert size_operands == [CType(text="btrc_Crate_int")]
    assert not any(isinstance(node, IRCall) and node.callee == "sizeof" for node in nodes)


def test_enum_constants_and_tags_are_symbol_references_not_literals():
    module = _generate("""
        enum Color { RED, GREEN };
        enum class Payload { Number(int value), Empty }
        int main() { Color color = RED; return color == GREEN ? 0 : 1; }
    """)
    nodes = list(IRTree(module))
    symbols = {node.name for node in nodes if isinstance(node, IRVar)}
    symbolic_names = {
        "Color_RED",
        "Color_GREEN",
        "Payload_Number_TAG",
        "Payload_Empty_TAG",
    }

    assert symbolic_names <= symbols
    assert not any(isinstance(node, IRLiteral) and node.text in symbolic_names for node in nodes)


def test_cycle_visitor_calls_its_function_pointer_as_an_expression():
    module = _generate("""
        class Node { public Node next; }
        int main() { return 0; }
    """)
    visitor = next(function for function in module.function_defs if function.name == cycle_visitor_symbol("Node"))
    calls = [node for node in IRTree(visitor) if isinstance(node, IRCall)]

    assert len(calls) == 1
    assert calls[0].callee == IRVar(name="fn")


def test_complex_function_pointer_member_calls_preserve_receiver_structure():
    module = _generate("""
        struct Handler { __fn_ptr<int, int> apply; };
        struct Handler makeValue();
        struct Handler* makePointer();
        int callValue() { return makeValue().apply(1); }
        int callPointer() { return makePointer().apply(1); }
        int main() { return 0; }
    """)
    functions = {function.name: function for function in module.function_defs}

    for function_name, factory_name, arrow in (
        ("callValue", "makeValue", False),
        ("callPointer", "makePointer", True),
    ):
        materialized = next(
            node
            for node in IRTree(functions[function_name])
            if isinstance(node, IRBinOp) and isinstance(node.right, IRFieldAccess)
        )
        assert isinstance(materialized.left, IRVar)
        assert materialized.left.name.startswith("__btrc_callable_")
        assert materialized.right.arrow is arrow
        assert materialized.right.field == "apply"
        assert materialized.right.obj == IRCall(callee=factory_name, args=[])
        member_call = next(
            node
            for node in IRTree(functions[function_name])
            if isinstance(node, IRCall) and node.callee == materialized.left
        )
        assert member_call.args == [IRLiteral(text="1")]


def test_unresolved_generic_constructor_never_guesses_a_registered_instance():
    with pytest.raises(CodegenError, match="no concrete analyzed call type"):
        _generate("""
            class Empty<Element> {}
            int main() {
                Empty<int> known = Empty();
                Empty();
                return 0;
            }
        """)
