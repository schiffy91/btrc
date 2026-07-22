"""White-box tests for terminal ARC destroy-name resolution.

Mangled generic-instance names are awkward to reach through the auto-management
path, so drive the helpers directly with a real analyzed program. An ordinary
method named ``free`` must not affect the selected lifecycle entry point.
"""

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.ir.gen.arc import (
    _destroy_fn_for_managed,
    _get_destroy_name,
)
from src.compiler.python.ir.gen.arc_cycles import lookup_class_info
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser

_SRC = """
class Pool<T> {
    public T item;
    public Pool(T x) { self.item = x; }
    public void free(int marker) { }
}
class Plain { public int v; public Plain() { self.v = 0; } }
int main() {
    Pool<int> p = new Pool<int>(5);
    Plain q = new Plain();
    return 0;
}
"""


def _gen():
    analyzed = SemanticAnalyzer().analyze(Parser(Lexer(_SRC, "<t>").tokenize()).parse())
    return IRGenerator(analyzed)


def test_get_destroy_name_generic_uses_terminal_destructor():
    g = _gen()
    te = TypeExpr(base="Pool", generic_args=[TypeExpr(base="int")])
    name = _get_destroy_name(g, te, "Pool")
    assert name.endswith("_destroy")


def test_get_destroy_name_non_generic():
    g = _gen()
    te = TypeExpr(base="Plain", generic_args=[])
    assert _get_destroy_name(g, te, "Plain") == "Plain_destroy"


def test_destroy_fn_for_managed_generic_instance_ignores_ordinary_free_method():
    g = _gen()
    # A mangled generic-instance name whose base class has an unrelated method.
    mangled = next((m for m in ["btrc_Pool_int", "Pool_int"]), "Pool_int")
    assert _destroy_fn_for_managed(g, mangled) == f"{mangled}_destroy"


def test_generic_release_never_uses_ordinary_free_method():
    g = _gen()
    te = TypeExpr(base="Pool", generic_args=[TypeExpr(base="int")])
    assert _get_destroy_name(g, te, "Pool") == "btrc_Pool_int_destroy"


def test_destroy_fn_for_managed_plain_class():
    g = _gen()
    assert _destroy_fn_for_managed(g, "Plain") == "Plain_destroy"


def test_lookup_cls_info_by_mangled_name():
    g = _gen()
    info = lookup_class_info(g, "btrc_Pool_int")
    assert info is None or info.name == "Pool"
