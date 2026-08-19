"""Unit contracts for reusable operand-boundary evaluation."""

from __future__ import annotations

from src.compiler.python.ir.lowering.calls import CallBoundaryLowerer, CallOperand
from src.compiler.python.ir.lowering.session import LoweringSession
from src.compiler.python.ir.nodes import IRFieldAccess, IRLiteral, IRModule, IRVar
from src.compiler.python.syntax.ast.generated import TypeExpr


class _Lifetime:
    def __init__(self) -> None:
        self.protected = []

    def protect_temporary(
        self,
        declaration,
        _type_expr,
        _declarations,
        _prefix,
        _flag_prefix,
        *,
        active=None,
    ) -> None:
        del active
        self.protected.append(declaration)

    @staticmethod
    def release_and_clear(
        _value,
        _type_expr,
        _declarations,
        _c_type,
    ) -> list:
        return []


class _CleanupScope:
    @staticmethod
    def exception_cleanup_active() -> bool:
        return False


class _Values:
    @staticmethod
    def is_managed(_type_expr) -> bool:
        return False


def _boundary() -> tuple[LoweringSession, _Lifetime, CallBoundaryLowerer]:
    session = LoweringSession(module=IRModule(), node_types={})
    lifetime = _Lifetime()
    return (
        session,
        lifetime,
        CallBoundaryLowerer(session, lifetime, _CleanupScope(), _Values()),
    )


class TestCallBoundaryEvaluation:
    def test_owned_operand_is_protected_by_the_retained_lifetime_owner(self) -> None:
        session, lifetime, boundary = _boundary()
        node = object()

        evaluation = boundary.evaluate(
            [
                CallOperand(
                    node=node,
                    type_expr=object(),
                    c_type="char *",
                    owned=True,
                    lowered=IRLiteral(text='"value"'),
                )
            ]
        )

        assert lifetime.protected == evaluation.declarations
        assert session.function_declarations == evaluation.declarations
        assert evaluation.values[id(node)].name.startswith("__btrc_call_operand_")
        assert len(evaluation.declarations) == 1
        assert len(evaluation.prefix) == 1

    def test_array_operand_temporary_keeps_original_struct_storage_root(self) -> None:
        _session, _lifetime, boundary = _boundary()
        node = object()
        source = IRFieldAccess(
            obj=IRVar(name="probe"),
            field="values",
            array_storage_root="probe",
            array_storage_known=True,
        )

        evaluation = boundary.evaluate(
            [
                CallOperand(
                    node=node,
                    type_expr=TypeExpr(base="int", is_array=True),
                    c_type="int*",
                    lowered=source,
                )
            ]
        )

        temporary = evaluation.values[id(node)]
        assert temporary.array_storage_known
        assert temporary.array_storage_root == "probe"

    def test_array_operand_temporary_keeps_known_pointer_storage_rootless(self) -> None:
        _session, _lifetime, boundary = _boundary()
        node = object()
        source = IRFieldAccess(
            obj=IRVar(name="owner"),
            field="values",
            arrow=True,
            array_storage_root="",
            array_storage_known=True,
        )

        evaluation = boundary.evaluate(
            [
                CallOperand(
                    node=node,
                    type_expr=TypeExpr(base="int", is_array=True),
                    c_type="int*",
                    lowered=source,
                )
            ]
        )

        temporary = evaluation.values[id(node)]
        assert temporary.array_storage_known
        assert temporary.array_storage_root == ""
