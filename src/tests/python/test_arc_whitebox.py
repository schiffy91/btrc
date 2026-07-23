"""White-box tests for managed-value owner resolution.

Mangled generic-instance names are awkward to reach through the auto-management
path, so drive the owner directly with a real analyzed program. An ordinary
method named ``free`` must not affect the selected lifecycle entry point.
"""

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.ir.gen.lowerer import IRLowerer
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
    return IRLowerer(analyzed)


def test_destroy_name_generic_uses_terminal_destructor():
    g = _gen()
    te = TypeExpr(base="Pool", generic_args=[TypeExpr(base="int")])
    name = g.managed_values.destroy_symbol(te)
    assert name.endswith("_destroy")


def test_destroy_name_non_generic():
    g = _gen()
    te = TypeExpr(base="Plain", generic_args=[])
    assert g.managed_values.destroy_symbol(te) == "Plain_destroy"


def test_cleanup_destroy_for_generic_instance_ignores_ordinary_free_method():
    g = _gen()
    # A mangled generic-instance name whose base class has an unrelated method.
    mangled = next((m for m in ["btrc_Pool_int", "Pool_int"]), "Pool_int")
    assert g.managed_values.cleanup_destroy_symbol(mangled) == f"{mangled}_destroy"


def test_generic_release_never_uses_ordinary_free_method():
    g = _gen()
    te = TypeExpr(base="Pool", generic_args=[TypeExpr(base="int")])
    assert g.managed_values.destroy_symbol(te) == "btrc_Pool_int_destroy"


def test_cleanup_destroy_for_plain_class():
    g = _gen()
    assert g.managed_values.cleanup_destroy_symbol("Plain") == "Plain_destroy"


def test_lookup_cls_info_by_mangled_name():
    g = _gen()
    info = g.cycles.lookup_class_info("btrc_Pool_int")
    assert info is not None
    assert info.name == "Pool"
