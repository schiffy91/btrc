"""Structured-IR contracts for concrete runtime ARC metadata."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.lowering.ownership import (
    CycleMetadata,
    ManagedValueSemantics,
    OwnershipLowerer,
)
from src.compiler.python.ir.lowering.session import LoweringSession
from src.compiler.python.ir.lowering.types import CTypeLowerer
from src.compiler.python.ir.nodes import IRModule
from src.compiler.python.ir.optimizer import IROptimizer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import TypeExpr

IDENTITY = TypeIdentity()


def _generate(source: str):
    program = Parser(Lexer(source, "<test>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors, analyzed.errors
    return IRLowerer(analyzed).lower()


def _cycles(source: str) -> CycleMetadata:
    program = Parser(Lexer(source, "<test>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors, analyzed.errors
    session = LoweringSession(module=IRModule(), node_types=analyzed.node_types)
    types = CTypeLowerer(session, analyzed, IDENTITY)
    values = ManagedValueSemantics(analyzed, IDENTITY, types)
    return CycleMetadata(analyzed, values, IDENTITY)


def test_every_concrete_managed_layout_starts_with_one_real_arc_header():
    module = _generate("""
        class Base {}
        class Child extends Base {}
        class Box<T> { public T value; }
        int main() {
            Base base = new Child();
            Box<int> box = new Box<int>();
            return 0;
        }
    """)
    mangled_box = IDENTITY.specialization_symbol("Box", [TypeExpr(base="int")])
    structures = {definition.name: definition for definition in module.struct_defs}
    for name in ("Base", "Child", mangled_box):
        first = structures[name].fields[0]
        assert first.name == "__arc"
        assert str(first.c_type) == "__btrc_arc_header"
        assert all(field.name not in {"__rc", "__cycle_safe_rc"} for field in structures[name].fields)


def test_every_concrete_managed_type_has_one_interned_descriptor():
    module = _generate("""
        class Base {}
        class Child extends Base { public Base link; }
        class Box<T> { public T value; }
        int main() {
            Base base = new Child();
            Box<Base> box = new Box<Base>();
            return 0;
        }
    """)
    mangled_box = IDENTITY.specialization_symbol("Box", [TypeExpr(base="Base", pointer_depth=1)])
    globals_by_name = {declaration.name: declaration for declaration in module.global_decls}
    for name in ("Base", "Child", mangled_box):
        descriptor = globals_by_name[OwnershipLowerer.descriptor_symbol(name)]
        assert str(descriptor.c_type) == "const __btrc_arc_type"


def test_descriptor_reachability_tracks_live_constructors_and_lifecycle():
    module = _generate("""
        class Dead { public Dead next; }
        class Live { public Live next; }
        int main() {
            Live value = new Live();
            return 0;
        }
    """)

    IROptimizer(module).optimize()

    global_names = {declaration.name for declaration in module.global_decls}
    function_names = {function.name for function in module.function_defs}
    assert OwnershipLowerer.descriptor_symbol("Live") in global_names
    assert OwnershipLowerer.descriptor_symbol("Dead") not in global_names
    assert "Live_destroy" in function_names
    assert "__btrc_arc_visit_Live" in function_names
    assert "Dead_destroy" not in function_names
    assert "__btrc_arc_visit_Dead" not in function_names


def test_cycle_boundaries_expand_subclasses_but_visitors_remain_exact():
    cycles = _cycles("""
        class Base {}
        class Derived extends Base { public Base peer; }
        class Holder { public Base value; }
    """)
    base = TypeExpr(base="Base")
    derived = TypeExpr(base="Derived")
    holder = TypeExpr(base="Holder")

    assert cycles.type_may_cycle(base)
    assert cycles.type_may_cycle(derived)
    assert not cycles.type_may_cycle(holder)
    assert not cycles.type_needs_visitor(base)
    assert cycles.type_needs_visitor(derived)


def test_generic_cycle_graph_expands_base_typed_edges():
    cycles = _cycles("""
        class Base {}
        class Box<T> { public T value; }
        class Derived extends Base { public Box<Base> owner; }
    """)

    assert cycles.type_may_cycle(
        TypeExpr(
            base="Box",
            generic_args=[TypeExpr(base="Base", pointer_depth=1)],
        )
    )
