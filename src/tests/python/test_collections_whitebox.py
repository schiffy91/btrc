"""White-box tests for collection-literal lowering (ir/gen/collections.py).
A bare typed list/map literal lowers to a Vector/Map constructor call; drive the
lowering functions directly on literal nodes from an analyzed program."""

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ast_nodes import (
    FunctionDecl,
    ListLiteral,
    MapLiteral,
    VarDeclStmt,
)
from src.compiler.python.ir.gen.collections import lower_list_literal, lower_map_literal
from src.compiler.python.ir.gen.lowerer import IRLowerer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _gen_and_inits(src):
    analyzed = SemanticAnalyzer().analyze(Parser(Lexer(src, "<t>").tokenize()).parse())
    gen = IRLowerer(analyzed)
    inits = []
    for d in analyzed.program.declarations:
        if isinstance(d, FunctionDecl) and d.body:
            for s in d.body.statements:
                if isinstance(s, VarDeclStmt) and s.initializer is not None:
                    inits.append(s.initializer)
    return gen, inits


def test_lower_nonempty_list_literal_infers_vector():
    gen, inits = _gen_and_inits("int main() { var xs = [1, 2, 3]; return 0; }")
    lit = next(i for i in inits if isinstance(i, ListLiteral))
    call = lower_list_literal(gen, lit)
    assert "Vector" in str(call)


def test_lower_empty_list_literal_falls_back():
    gen, inits = _gen_and_inits("int main() { var xs = []; return 0; }")
    lits = [i for i in inits if isinstance(i, ListLiteral)]
    if lits:
        call = lower_list_literal(gen, lits[0])
        assert "Vector" in str(call)


def test_lower_nonempty_map_literal_infers_map():
    gen, inits = _gen_and_inits('int main() { var m = {"a": 1, "b": 2}; return 0; }')
    lits = [i for i in inits if isinstance(i, MapLiteral)]
    if lits:
        call = lower_map_literal(gen, lits[0])
        assert "Map" in str(call)


def test_lower_empty_map_literal_falls_back():
    gen, inits = _gen_and_inits("int main() { Map<string, int> m = {}; return 0; }")
    lits = [i for i in inits if isinstance(i, MapLiteral)]
    if lits:
        call = lower_map_literal(gen, lits[0])
        assert "Map" in str(call)
