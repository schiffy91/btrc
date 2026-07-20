"""Analyzer contracts for the structural parallel-range loop form."""

import dataclasses

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ast_nodes import Identifier
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _walk(value):
    if dataclasses.is_dataclass(value):
        yield value
        for field in dataclasses.fields(value):
            yield from _walk(getattr(value, field.name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


def test_parallel_range_binding_is_typed_inside_body():
    program = Parser(
        Lexer(
            """
        int main() {
            parallel for index in range(10) {
                if (index % 2 == 0) { continue; }
            }
            return 0;
        }
    """,
            "<parallel-range>",
        ).tokenize()
    ).parse()
    analyzed = Analyzer().analyze(program)

    assert analyzed.errors == []
    uses = [node for node in _walk(program) if isinstance(node, Identifier) and node.name == "index"]
    assert uses
    assert all(analyzed.node_types[id(node)].base == "int" for node in uses)
    IRGenerator(analyzed).generate()
