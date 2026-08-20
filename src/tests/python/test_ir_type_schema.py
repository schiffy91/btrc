"""Resolved-type and symbolic-expression contracts for structured IR."""

import ast
import shutil
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.analyzer.generated_symbols import GeneratedSymbolRegistry
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.lowering.types import CodegenError
from src.compiler.python.ir.nodes import (
    CType,
    IRCall,
    IRCast,
    IRFieldAccess,
    IRLiteral,
    IRModule,
    IRNode,
    IRSizeof,
    IRVar,
)
from src.compiler.python.ir.verifier import IRVerifier
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser

IR_ROOT = Path(__file__).parents[2] / "compiler/python/ir"
COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _self_attribute_chain(node: ast.AST) -> tuple[str, ...]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name) and node.id == "self":
        return tuple(reversed(parts))
    return ()


def test_ir_domain_owners_do_not_reach_through_module_private_state() -> None:
    reachthrough: list[str] = []
    for path in sorted(IR_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or not node.attr.startswith("_"):
                continue
            chain = _self_attribute_chain(node.value)
            if chain:
                reachthrough.append(f"{path.name}:{node.lineno}:self.{'.'.join((*chain, node.attr))}")
    assert reachthrough == []


def _analyze(source: str):
    program = Parser(Lexer(source, "<ir-type-schema>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert analyzed.errors == []
    return analyzed


def _generate(source: str):
    return IRLowerer(_analyze(source)).lower()


def _emit(source: str) -> str:
    pipeline = CompilationPipeline()
    module = pipeline.optimize(_generate(source), CompilerOptions())
    return pipeline.emit(module)


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
        IRVerifier(module).validate()


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
    nodes = list(IRNode.walk_value(constructor))
    size_operands = [node.operand for node in nodes if isinstance(node, IRSizeof)]

    assert size_operands == [CType(text="btrc_Crate_int")]
    assert not any(isinstance(node, IRCall) and node.callee == "sizeof" for node in nodes)


def test_enum_constants_and_tags_are_symbol_references_not_literals():
    module = _generate("""
        enum Color { RED, GREEN };
        enum class Payload { Number(int value), Empty }
        int main() { Color color = RED; return color == GREEN ? 0 : 1; }
    """)
    nodes = list(IRNode.walk_value(module))
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
    visitor = next(
        function
        for function in module.function_defs
        if function.name == GeneratedSymbolRegistry.cycle_visitor_symbol("Node")
    )
    calls = [node for node in IRNode.walk_value(visitor) if isinstance(node, IRCall)]

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
        member_call = next(
            node
            for node in IRNode.walk_value(functions[function_name])
            if isinstance(node, IRCall) and isinstance(node.callee, IRFieldAccess)
        )
        member = member_call.callee
        assert member.arrow is arrow
        assert member.field == "apply"
        assert member.obj == IRCall(callee=factory_name, args=[])
        assert member_call.args == [IRLiteral(text="1")]

        factory_calls = [
            node
            for node in IRNode.walk_value(functions[function_name])
            if isinstance(node, IRCall) and node.callee == factory_name
        ]
        assert factory_calls == [member.obj]


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_complex_function_pointer_member_calls_run_in_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    generated = _emit("""
        #include <assert.h>
        struct Handler { __fn_ptr<int, int> apply; };
        int valueFactoryCalls = 0;
        int pointerFactoryCalls = 0;
        int addForty(int value) { return value + 40; }
        struct Handler pointerHandler = {addForty};
        struct Handler makeValue() {
            valueFactoryCalls += 1;
            struct Handler result = {addForty};
            return result;
        }
        struct Handler* makePointer() {
            pointerFactoryCalls += 1;
            return &pointerHandler;
        }
        int callValue() { return makeValue().apply(1); }
        int callPointer() { return makePointer().apply(2); }
        int main() {
            assert(callValue() == 41);
            assert(callPointer() == 42);
            assert(valueFactoryCalls == 1);
            assert(pointerFactoryCalls == 1);
            return 0;
        }
    """)
    source = tmp_path / "function_pointer_member.c"
    executable = tmp_path / "function_pointer_member"
    source.write_text(generated)

    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O1",
            str(source),
            "-lm",
            "-pthread",
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([executable], check=True, capture_output=True, text=True)


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
