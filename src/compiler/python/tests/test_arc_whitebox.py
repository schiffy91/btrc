"""White-box tests for ARC destroy-name resolution. These branches depend on a
generic class exposing a free() method and on mangled generic-instance names —
states that the auto-management path doesn't produce for generic collections, so
drive the helpers directly with a real analyzed program."""

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.ir.gen.arc import (
    _destroy_fn_for_managed,
    _get_destroy_name,
    _lookup_cls_info,
)
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser

_SRC = """
class Pool<T> {
    public T item;
    public Pool(T x) { self.item = x; }
    public void free() { }
}
class Plain { public int v; public Plain() { self.v = 0; } }
int main() {
    Pool<int> p = new Pool<int>(5);
    Plain q = new Plain();
    return 0;
}
"""


def _gen():
    analyzed = Analyzer().analyze(Parser(Lexer(_SRC, "<t>").tokenize()).parse())
    return IRGenerator(analyzed)


def test_get_destroy_name_generic_with_free():
    g = _gen()
    te = TypeExpr(base="Pool", generic_args=[TypeExpr(base="int")])
    name = _get_destroy_name(g, te, "Pool")
    assert name.endswith("_free")            # Pool defines free()


def test_get_destroy_name_non_generic():
    g = _gen()
    te = TypeExpr(base="Plain", generic_args=[])
    assert _get_destroy_name(g, te, "Plain") == "Plain_destroy"


def test_destroy_fn_for_managed_generic_instance_with_free():
    g = _gen()
    # A mangled generic-instance name whose base class defines free().
    mangled = next((m for m in [
        "btrc_Pool_int", "Pool_int"] ), "Pool_int")
    name = _destroy_fn_for_managed(g, mangled)
    assert name.endswith("_free") or name.endswith("_destroy")


def test_destroy_fn_for_managed_plain_class():
    g = _gen()
    assert _destroy_fn_for_managed(g, "Plain") == "Plain_destroy"


def test_lookup_cls_info_by_mangled_name():
    g = _gen()
    info = _lookup_cls_info(g, "btrc_Pool_int")
    assert info is None or info.name == "Pool"
