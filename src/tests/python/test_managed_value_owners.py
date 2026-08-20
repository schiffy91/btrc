"""Managed-value policy and generic specialization have explicit owners."""

from src.compiler.python.analyzer.program import AnalyzedProgram, ClassInfo
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.ir.lowering.generics import (
    SpecializedDeclarationView,
    TypeSubstitution,
)
from src.compiler.python.ir.lowering.ownership import ManagedValueSemantics
from src.compiler.python.ir.lowering.session import LoweringSession
from src.compiler.python.ir.lowering.types import CTypeLowerer
from src.compiler.python.ir.nodes import IRModule
from src.compiler.python.syntax.ast.generated import Program, TypeExpr


def _analyzed() -> AnalyzedProgram:
    return AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={
            "Item": ClassInfo(name="Item"),
            "Box": ClassInfo(name="Box", generic_params=["T"]),
        },
    )


def test_managed_value_policy_classifies_concrete_generic_instances() -> None:
    analyzed = _analyzed()
    identity = TypeIdentity()
    session = LoweringSession(module=IRModule(), node_types=analyzed.node_types)
    types = CTypeLowerer(session, analyzed, identity)
    values = ManagedValueSemantics(analyzed, identity, types)

    assert values.is_managed(TypeExpr(base="Item"))
    assert values.is_managed(TypeExpr(base="Box", generic_args=[TypeExpr(base="Item")]))
    assert values.is_managed(TypeExpr(base="string"))
    assert not values.is_managed(TypeExpr(base="int"))


def test_specialization_is_scoped_state_on_the_shared_lowering_session() -> None:
    analyzed = _analyzed()
    identity = TypeIdentity()
    session = LoweringSession(module=IRModule(), node_types=analyzed.node_types)
    substitution = TypeSubstitution(
        arguments={"T": TypeExpr(base="Item")},
        typedefs={},
        identity=identity,
    )
    view = SpecializedDeclarationView(
        declaration=object(),
        substitution=substitution,
        symbol=identity.specialization_symbol("Box", [TypeExpr(base="Item")]),
        base_name="Box",
        type_arguments=(TypeExpr(base="Item"),),
        selected_callables=frozenset(),
        owner_name="Box",
        owner_symbol=identity.specialization_symbol("Box", [TypeExpr(base="Item")]),
    )

    assert session.active_specialization is None
    with session.specialization(view):
        assert session.active_specialization is view
        assert session.active_specialization.substitution.resolve(TypeExpr(base="T")) == TypeExpr(base="Item")
    assert session.active_specialization is None
