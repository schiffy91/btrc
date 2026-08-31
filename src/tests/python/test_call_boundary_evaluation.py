"""Unit contracts for reusable operand-boundary evaluation."""

from __future__ import annotations

from src.compiler.python.ir.lowering.calls import (
    CallBoundaryLowerer,
    CallOperand,
    CallResultPlan,
)
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


class _ActiveCleanupScope:
    @staticmethod
    def exception_cleanup_active() -> bool:
        return True


class _Values:
    @staticmethod
    def is_managed(_type_expr) -> bool:
        return False


def _boundary(
    cleanup_scope: object | None = None,
) -> tuple[LoweringSession, _Lifetime, CallBoundaryLowerer]:
    session = LoweringSession(module=IRModule(), node_types={})
    lifetime = _Lifetime()
    return (
        session,
        lifetime,
        CallBoundaryLowerer(
            session,
            lifetime,
            cleanup_scope or _CleanupScope(),
            _Values(),
        ),
    )


class TestCallBoundaryEvaluation:
    def test_typed_result_is_volatile_only_across_exception_cleanup(self) -> None:
        ordinary_declarations = []
        _session, _lifetime, ordinary = _boundary()
        ordinary._append_typed_result(
            [],
            [],
            ordinary_declarations,
            IRLiteral(text="probe()"),
            CallResultPlan(c_type="Probe*"),
        )
        assert not ordinary_declarations[0].is_volatile

        protected_declarations = []
        _session, _lifetime, protected = _boundary(_ActiveCleanupScope())
        protected._append_typed_result(
            [],
            [],
            protected_declarations,
            IRLiteral(text="probe()"),
            CallResultPlan(c_type="Probe*"),
        )
        assert protected_declarations[0].is_volatile

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
        assert evaluation.ownership[id(node)] is False
        assert len(evaluation.declarations) == 1
        assert len(evaluation.prefix) == 1

    def test_transferred_operand_exposes_its_owned_handoff_fact(self) -> None:
        _session, _lifetime, boundary = _boundary()
        node = object()

        evaluation = boundary.evaluate(
            [
                CallOperand(
                    node=node,
                    type_expr=object(),
                    c_type="char *",
                    owned=True,
                    transferred=True,
                    lowered=IRLiteral(text='"value"'),
                )
            ]
        )

        assert evaluation.values[id(node)].name.startswith("__btrc_transferred_operand_")
        assert evaluation.ownership[id(node)] is True

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
