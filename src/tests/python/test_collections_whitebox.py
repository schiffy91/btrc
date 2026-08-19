"""Collection literals lower through the configured IR stage."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.nodes import IRCall, IRNode
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _call_targets(src: str) -> set[str]:
    analyzed = SemanticAnalyzer().analyze(Parser(Lexer(src, "<t>").tokenize()).parse())
    module = IRLowerer(analyzed).lower()
    return {
        node.callee
        for node in IRNode.walk_value(module)
        if isinstance(node, IRCall) and isinstance(node.callee, str)
    }


def test_lower_nonempty_list_literal_infers_vector():
    targets = _call_targets("int main() { var xs = [1, 2, 3]; return 0; }")
    assert any("Vector" in target for target in targets)


def test_lower_empty_list_literal_falls_back():
    targets = _call_targets("int main() { var xs = []; return 0; }")
    assert any("Vector" in target for target in targets)


def test_lower_nonempty_map_literal_infers_map():
    targets = _call_targets('int main() { var m = {"a": 1, "b": 2}; return 0; }')
    assert any("Map" in target for target in targets)


def test_lower_empty_map_literal_falls_back():
    targets = _call_targets("int main() { Map<string, int> m = {}; return 0; }")
    assert any("Map" in target for target in targets)
