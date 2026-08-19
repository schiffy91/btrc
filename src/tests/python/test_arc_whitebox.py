"""White-box tests for managed-value owner resolution.

Mangled generic-instance names are awkward to reach through the auto-management
path, so drive the owner directly with a real analyzed program. An ordinary
method named ``free`` must not affect the selected lifecycle entry point.
"""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.ir.lowering.ownership import CycleMetadata, ManagedValueSemantics
from src.compiler.python.ir.lowering.session import LoweringSession
from src.compiler.python.ir.lowering.types import CTypeLowerer
from src.compiler.python.ir.nodes import IRModule
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import TypeExpr

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


def _owners() -> tuple[ManagedValueSemantics, CycleMetadata]:
    analyzed = SemanticAnalyzer().analyze(Parser(Lexer(_SRC, "<t>").tokenize()).parse())
    identity = TypeIdentity()
    session = LoweringSession(module=IRModule(), node_types=analyzed.node_types)
    types = CTypeLowerer(session, analyzed, identity)
    values = ManagedValueSemantics(analyzed, identity, types)
    return values, CycleMetadata(analyzed, values, identity)


def test_destroy_name_generic_uses_terminal_destructor():
    values, _ = _owners()
    te = TypeExpr(base="Pool", generic_args=[TypeExpr(base="int")])
    name = values.destroy_symbol(te)
    assert name.endswith("_destroy")


def test_destroy_name_non_generic():
    values, _ = _owners()
    te = TypeExpr(base="Plain", generic_args=[])
    assert values.destroy_symbol(te) == "Plain_destroy"


def test_cleanup_destroy_for_generic_instance_ignores_ordinary_free_method():
    values, _ = _owners()
    # A mangled generic-instance name whose base class has an unrelated method.
    mangled = next((m for m in ["btrc_Pool_int", "Pool_int"]), "Pool_int")
    assert values.cleanup_destroy_symbol(mangled) == f"{mangled}_destroy"


def test_generic_release_never_uses_ordinary_free_method():
    values, _ = _owners()
    te = TypeExpr(base="Pool", generic_args=[TypeExpr(base="int")])
    assert values.destroy_symbol(te) == "btrc_Pool_int_destroy"


def test_cleanup_destroy_for_plain_class():
    values, _ = _owners()
    assert values.cleanup_destroy_symbol("Plain") == "Plain_destroy"


def test_lookup_cls_info_by_mangled_name():
    _, cycles = _owners()
    info = cycles.lookup_class_info("btrc_Pool_int")
    assert info is not None
    assert info.name == "Pool"
