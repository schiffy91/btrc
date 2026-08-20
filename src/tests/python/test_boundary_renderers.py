"""Deterministic AST and structured-IR boundary rendering contracts."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

import pytest

from src.compiler.python import Compiler
from src.compiler.python.application.results import CompilerOptions, CompilerOutput, CompilerResult
from src.compiler.python.cli.compiler import CompilerCommand
from src.compiler.python.ir.nodes import (
    IRCanonicalRenderer,
    IREnumDef,
    IRGpuBuffer,
    IRGpuKernel,
    IRGpuShaderModule,
    IRModule,
    IRStructDef,
)
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.codec import AstCanonicalRenderer
from src.compiler.python.syntax.ast.generated import Identifier, TypeExpr


def _parse(source: str, filename: str = "boundary.btrc"):
    return Parser(Lexer(source, filename).tokenize()).parse()


class _AstCompiler:
    stdlib_directory = ""
    stdlib_archive_available = False
    freestanding_header = ""

    def __init__(self, program) -> None:
        self.program = program

    def compile(self, source: str, input_path: str, options: CompilerOptions) -> CompilerResult:
        return CompilerResult(options=options, source_bundle=None, program=self.program)


def test_emit_ast_routes_through_the_canonical_ast_owner(tmp_path, capsys) -> None:
    program = _parse("int main() { return 0; }\n")
    program.declarations[0].source_file = "/host-specific/path/boundary.btrc"
    source_path = tmp_path / "boundary.btrc"
    source_path.write_text("ignored by the injected compiler", encoding="utf-8")

    CompilerCommand(_AstCompiler(program)).run([str(source_path), "--emit-ast", "--no-cache"])

    output = capsys.readouterr().out
    expected = (AstCanonicalRenderer().render(program) + "\n").encode()
    result = CompilerResult(options=CompilerOptions(output=CompilerOutput.AST), source_bundle=None, program=program)
    assert ("\n".join(result.ast_dump_lines()) + "\n").encode() == expected
    assert output.encode() == expected
    assert "source_file=nil" in output
    assert "/host-specific/path" not in output


def test_ir_renderer_serializes_every_module_field_and_nested_body() -> None:
    source = "int main() { int value = 3; return value; }\n"
    result = Compiler().compile(
        source,
        "boundary.btrc",
        CompilerOptions(
            output=CompilerOutput.IR,
            include_stdlib=False,
            use_cache=False,
        ),
    )
    assert result.ir_module is not None

    rendered = IRCanonicalRenderer().render(result.ir_module)
    module_value = json.loads(rendered)["module"]

    assert set(module_value) == {"$type", *(field.name for field in dataclasses.fields(IRModule))}
    assert '"$type": "IRVarDecl"' in rendered
    assert '"$type": "IRReturn"' in rendered


def test_ir_renderer_is_stable_for_unordered_state_and_type_plan_references() -> None:
    first_enum = IREnumDef(name="Color")
    first_struct = IRStructDef(name="Point")
    first = IRModule(runtime_roots={"zeta", "alpha"}, enum_defs=[first_enum], struct_defs=[first_struct])
    first.record_type_declaration_plan([first_struct, first_enum])

    second_enum = IREnumDef(name="Color")
    second_struct = IRStructDef(name="Point")
    second = IRModule(runtime_roots={"alpha", "zeta"}, enum_defs=[second_enum], struct_defs=[second_struct])
    second.record_type_declaration_plan([second_struct, second_enum])

    first_value = IRCanonicalRenderer().render(first)
    second_value = IRCanonicalRenderer().render(second)
    references = json.loads(first_value)["module"]["ordered_type_declarations"]

    assert first_value == second_value
    assert references == [
        {"$ref": {"field": "struct_defs", "index": 0}},
        {"$ref": {"field": "enum_defs", "index": 0}},
    ]


def test_ir_renderer_replaces_process_ids_with_shader_body_ordinals() -> None:
    first_program = _parse("int kernel(int value) { return value; }\n")
    second_program = _parse("int kernel(int value) { return value; }\n")
    first_body = first_program.declarations[0].body
    second_body = second_program.declarations[0].body
    first_identifier = next(node for node in _dataclass_nodes(first_body) if isinstance(node, Identifier))
    second_identifier = next(node for node in _dataclass_nodes(second_body) if isinstance(node, Identifier))

    first = _gpu_module(first_body, first_identifier)
    second = _gpu_module(second_body, second_identifier)
    first_rendered = IRCanonicalRenderer().render(first)
    second_rendered = IRCanonicalRenderer().render(second)
    node_types = json.loads(first_rendered)["module"]["gpu_kernels"][0]["shader_module"]["node_types"]

    assert first_rendered == second_rendered
    assert node_types["$scope"] == "shader-body-dataclass-preorder"
    assert len(node_types["entries"]) == 1
    assert isinstance(node_types["entries"][0]["node"], int)


@dataclass
class _UnknownSemanticValue:
    spelling: str


def test_ast_renderer_rejects_unknown_structured_values() -> None:
    with pytest.raises(TypeError, match="unsupported canonical AST value: _UnknownSemanticValue"):
        AstCanonicalRenderer().render(_UnknownSemanticValue("value"))


def test_ir_renderer_rejects_unknown_structured_values() -> None:
    module = IRModule(
        gpu_kernels=[
            IRGpuKernel(
                name="kernel",
                shader_module=IRGpuShaderModule(),
                param_buffers=[IRGpuBuffer(name="values", elem_type=_UnknownSemanticValue("int"))],
            )
        ]
    )

    with pytest.raises(TypeError, match=r"param_buffers\[0\]\.elem_type: _UnknownSemanticValue"):
        IRCanonicalRenderer().render(module)


def test_raw_and_optimized_ir_dumps_preserve_bodies_and_expose_dce() -> None:
    source = "int dead() { return 7; } int main() { return 0; }\n"
    compiler = Compiler()
    raw = compiler.compile(
        source,
        "boundary.btrc",
        CompilerOptions(output=CompilerOutput.IR, include_stdlib=False, use_cache=False),
    )
    optimized = compiler.compile(
        source,
        "boundary.btrc",
        CompilerOptions(output=CompilerOutput.OPTIMIZED_IR, include_stdlib=False, use_cache=False),
    )
    raw_dump = "\n".join(raw.ir_dump_lines())
    optimized_dump = "\n".join(optimized.ir_dump_lines())

    assert '"name": "dead"' in raw_dump
    assert '"name": "dead"' not in optimized_dump
    assert '"$type": "IRReturn"' in raw_dump
    assert '"$type": "IRReturn"' in optimized_dump
    assert raw_dump != optimized_dump


def _dataclass_nodes(root: object) -> list[object]:
    nodes: list[object] = []

    def visit(value: object) -> None:
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            nodes.append(value)
            for node_field in dataclasses.fields(value):
                visit(getattr(value, node_field.name))
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(root)
    return nodes


def _gpu_module(body: object, identifier: Identifier) -> IRModule:
    irrelevant = Identifier(name="outside")
    node_types = {
        id(identifier): TypeExpr(base="int"),
        id(irrelevant): TypeExpr(base="float"),
    }
    return IRModule(
        gpu_kernels=[
            IRGpuKernel(
                name="kernel",
                shader_module=IRGpuShaderModule(body=body, node_types=node_types, output_type=TypeExpr(base="int")),
                param_buffers=[IRGpuBuffer(name="values", elem_type=TypeExpr(base="int", is_array=True))],
                uniform_params=[("scale", TypeExpr(base="int"))],
            )
        ]
    )
