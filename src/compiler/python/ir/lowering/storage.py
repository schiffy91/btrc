"""Cohesive storage IR lowering owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.storage import StorageModel
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRBinOp,
    IRCommaExpr,
    IRDeref,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRIndex,
    IRLiteral,
    IRSizeof,
    IRStmt,
    IRStmtExpr,
    IRTernary,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.syntax.ast.generated import (
    VarDeclStmt,
)

from .types import CTypeLowerer

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalyzedProgram

    from .calls import CallableProvenance
    from .ownership import (
        ManagedLifetimeLowerer,
        ManagedValueSemantics,
        OwnershipLowerer,
    )
    from .session import LoweringSession


@dataclass(frozen=True)
class CArrayBinding:
    is_array: bool
    logical_length: object | None = None


@dataclass(frozen=True, slots=True)
class StoragePlan:
    target: object
    value: object
    operator: str
    target_type: object | None
    value_type: object | None


@dataclass(frozen=True, slots=True)
class VariableDeclarationPlan:
    """One lexical declaration awaiting expression materialization."""

    source: VarDeclStmt
    c_name: str
    c_type: str
    element_c_type: str | None
    initializer: object | None
    array_size: object | None
    storage: dict[str, bool]


class StorageLowerer:
    """Own storage lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        ownership: OwnershipLowerer,
        values: ManagedValueSemantics,
        lifetime: ManagedLifetimeLowerer,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._ownership = ownership
        self._values = values
        self._lifetime = lifetime

    def plan_store(self, target, value, *, operator="="):
        return StoragePlan(
            target=target,
            value=value,
            operator=operator,
            target_type=self._session.type_of(target),
            value_type=self._session.type_of(value),
        )

    def materialize_store(self, plan, lowered_target, lowered_value):
        return IRBinOp(left=lowered_target, op=plan.operator, right=lowered_value)

    def plan_declaration(
        self,
        node: VarDeclStmt,
        provenance: CallableProvenance,
    ) -> VariableDeclarationPlan:
        """Plan a lexical declaration without lowering its source expressions."""
        from src.compiler.python.analyzer.types import TypeSystem

        element_c_type = None
        if node.type is not None and node.type.is_array:
            element_type = TypeSystem.strip_outer_storage(node.type, array=True)
            element_c_type = self._types.render(element_type)
        c_name = self._ownership.next_source_binding_c_name(node.name, provenance)
        return VariableDeclarationPlan(
            source=node,
            c_name=c_name,
            c_type=self._types.render(node.type) if node.type is not None else "int",
            element_c_type=element_c_type,
            initializer=node.initializer,
            array_size=node.type.array_size if node.type is not None and node.type.is_array else None,
            storage=self.storage_metadata(node),
        )

    def materialize_declaration(
        self,
        plan: VariableDeclarationPlan,
        provenance: CallableProvenance,
        *,
        initializer: IRExpr | None,
        array_size: IRExpr | None,
    ) -> list[IRStmt]:
        """Materialize a declaration from values lowered by the statement owner."""
        source = plan.source
        external = bool(source.type and source.type.is_extern and source.initializer is None)
        is_array = bool(source.type and source.type.is_array)
        declaration = IRVarDecl(
            c_type=CType(text=plan.element_c_type if is_array else plan.c_type),
            name=plan.c_name,
            init=initializer,
            array_size=array_size,
            is_unsized_array=bool(is_array and array_size is None),
            **plan.storage,
        )
        self._session.record_declaration(declaration)
        self.declare_c_binding(source.name, is_array=is_array)
        self._ownership.declare_local_ownership(source.name, provenance, c_name=plan.c_name)
        provenance.bind_local(source.name, source.type, source.initializer)
        result: list[IRStmt] = [declaration]
        if external:
            result.append(StorageLowerer.mark_external_declaration_used(plan.c_name))
            return result
        source_type = self._session.type_of(source.initializer)
        managed_type = (
            source.type
            if self._values.is_managed(source.type)
            else source_type
            if self._values.is_managed(source_type)
            else None
        )
        if managed_type is not None:
            runtime_type = self._values.runtime_name(managed_type)
            owns_initializer = bool(
                source.initializer is not None
                and self._ownership.owns_result(source.initializer, provenance=provenance)
            )
            if source.initializer is not None and not owns_initializer:
                result.append(IRExprStmt(expr=self._lifetime.retain_value(IRVar(name=plan.c_name), managed_type)))
            self._ownership.register_managed_var(
                source.name,
                runtime_type,
                provenance,
                cycle_seed=bool(owns_initializer and not self._values.is_string(managed_type)),
            )
            self._ownership.declare_local_ownership(source.name, provenance, runtime_type, c_name=plan.c_name)
            self._lifetime.register_named_cleanup(plan.c_name, runtime_type, result)
        canonical = self._types.canonical_type(source.type)
        if (
            source.initializer is not None
            and canonical is not None
            and canonical.base == "Thread"
            and canonical.generic_args
        ):
            self._ownership.register_thread_var(source.name, provenance)
            self._session.require_helper("__btrc_thread_free")
            self._lifetime.register_direct_cleanup(plan.c_name, "__btrc_thread_free", result)
        return result

    @staticmethod
    def safe_array_size(logical_length: IRExpr) -> IRExpr:
        """Represent an empty logical array with a valid one-element C VLA."""
        return IRTernary(
            condition=IRBinOp(
                left=logical_length,
                op=">",
                right=IRLiteral(text="0"),
            ),
            true_expr=logical_length,
            false_expr=IRLiteral(text="1"),
        )

    def declare_c_binding(self, name: str, *, is_array: bool, logical_length=None) -> None:
        """Record the current scope's representation for one lexical binding."""
        if self._session.c_array_scopes:
            self._session.c_array_scopes[-1][name] = (
                CArrayBinding(is_array, logical_length) if logical_length is not None else is_array
            )

    def local_c_array_status(self, name: str) -> bool | None:
        """Return the nearest local binding's array status, or ``None`` if absent."""
        for scope in reversed(self._session.c_array_scopes):
            if name in scope:
                binding = scope[name]
                return binding.is_array if isinstance(binding, CArrayBinding) else binding
        return None

    def local_gpu_array_length(self, name: str):
        """Return the logical GPU result length for the nearest binding."""
        for scope in reversed(self._session.c_array_scopes):
            if name in scope:
                binding = scope[name]
                return binding.logical_length if isinstance(binding, CArrayBinding) else None
        return None

    def consume_addressable_handle(self, obj, *, handle_c_type: str, prefix: str):
        """Move one lvalue handle and clear its source before it is consumed."""
        if not isinstance(obj, (IRVar, IRFieldAccess, IRIndex, IRDeref)):
            return obj
        slot_name = self._session.fresh_temp(f"{prefix}_slot")
        handle_name = self._session.fresh_temp(f"{prefix}_handle")
        slot = IRVar(name=slot_name)
        handle = IRVar(name=handle_name)
        return IRStmtExpr(
            stmts=[
                IRVarDecl(c_type=CType(text=f"{handle_c_type}* volatile*"), name=slot_name),
                IRVarDecl(c_type=CType(text=f"{handle_c_type}*"), name=handle_name),
            ],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(left=slot, op="=", right=IRAddressOf(expr=obj)),
                    IRBinOp(left=handle, op="=", right=IRDeref(expr=slot)),
                    IRBinOp(left=IRDeref(expr=slot), op="=", right=IRLiteral(text="NULL")),
                    handle,
                ]
            ),
        )

    def storage_metadata(self, node: VarDeclStmt) -> dict[str, bool]:
        """Return C storage qualifiers for one lexical declaration."""
        type_expr = node.type
        return {
            "is_static": bool(getattr(type_expr, "is_static", False)),
            "is_extern": bool(getattr(type_expr, "is_extern", False)),
            "is_volatile": bool(getattr(type_expr, "is_volatile", False)),
            "effective_is_volatile": StorageModel.effective_outer_volatile(type_expr, self._analyzed.typedef_table),
        }

    @staticmethod
    def mark_external_declaration_used(name: str) -> IRExprStmt:
        """Keep a strict-import external declaration visible to C analysis."""
        return IRExprStmt(expr=IRSizeof(operand=IRAddressOf(expr=IRVar(name=name))))
