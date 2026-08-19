"""Cohesive collections IR lowering owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRCompoundLiteral,
    IRExpr,
    IRExprStmt,
    IRFunctionRef,
    IRIf,
    IRInitializerList,
    IRLiteral,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.syntax.ast.generated import BraceInitializer, ListLiteral, MapLiteral, TupleLiteral, TypeExpr

from .types import CodegenError, CTypeLowerer

if TYPE_CHECKING:
    from .calls import CallableProvenance
    from .ownership import (
        CleanupScopeState,
        CleanupSlotRegistry,
        CycleMetadata,
        ManagedLifetimeLowerer,
        ManagedValueSemantics,
        OwnershipLowerer,
    )
    from .session import LoweringSession


@dataclass(frozen=True, slots=True)
class AggregatePlan:
    """Backend-neutral aggregate shape awaiting lowered element values."""

    source: object
    c_type: str | None
    field_names: tuple[str, ...]
    constructor: str | None = None


@dataclass(frozen=True, slots=True)
class StaticAggregatePlan:
    """Typed shape for one recursively lowered static initializer."""

    field_types: tuple[TypeExpr, ...] | None


class CollectionLowerer:
    """Own collections lowering for one run."""

    _COLLECTION_CLASS_BASES = frozenset({"Array", "List", "Map", "Set", "Vector"})

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        type_identity: TypeIdentity,
        ownership: OwnershipLowerer,
        values: ManagedValueSemantics,
        lifetime: ManagedLifetimeLowerer,
        cycles: CycleMetadata,
        cleanup_slots: CleanupSlotRegistry,
        cleanup_scope: CleanupScopeState,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._type_identity = type_identity
        self._ownership = ownership
        self._values = values
        self._lifetime = lifetime
        self._cycles = cycles
        self._cleanup_slots = cleanup_slots
        self._cleanup_scope = cleanup_scope

    def plan_brace(self, node: BraceInitializer, provenance: CallableProvenance) -> AggregatePlan:
        """Resolve one context-typed aggregate without lowering elements."""
        node_type = self._session.type_of(node)
        self._reject_shallow_initializer(node, node_type, provenance)
        canonical = self._types.canonical_type(node_type)
        if canonical and canonical.base in self._analyzed.class_table and canonical.generic_args:
            if not node.elements:
                return AggregatePlan(
                    source=node,
                    c_type=None,
                    field_names=(),
                    constructor=self._type_identity.specialization_symbol(canonical.base, canonical.generic_args),
                )
            if canonical.base not in self._COLLECTION_CLASS_BASES:
                raise CodegenError(
                    "cannot use a non-empty brace initializer for heap class "
                    f"'{canonical.base}'; use an explicit constructor call"
                )
        if canonical and canonical.pointer_depth == 0:
            struct_name = canonical.base.removeprefix("struct ")
            declaration = self._analyzed.struct_table.get(struct_name)
            if declaration is not None and not declaration.is_forward:
                return AggregatePlan(
                    source=node,
                    c_type=self._types.render(node_type),
                    field_names=tuple(field.name for field in declaration.fields[: len(node.elements)]),
                )
            if canonical.base == "Tuple":
                return AggregatePlan(
                    source=node,
                    c_type=self._types.render(node_type),
                    field_names=tuple(f"_{index}" for index in range(len(node.elements))),
                )
        return AggregatePlan(source=node, c_type=None, field_names=())

    def plan_tuple(self, node: TupleLiteral, provenance: CallableProvenance) -> AggregatePlan:
        """Resolve a tuple representation without lowering its elements."""
        self._reject_owned_elements(node.elements, "a shallow aggregate", provenance)
        node_type = self._session.type_of(node)
        element_types = (
            list(node_type.generic_args)
            if node_type is not None and node_type.generic_args
            else [self._session.type_of(element) or TypeExpr(base="int") for element in node.elements]
        )
        return AggregatePlan(
            source=node,
            c_type=self._type_identity.generic_symbol("Tuple", element_types),
            field_names=tuple(f"_{index}" for index in range(len(node.elements))),
        )

    @staticmethod
    def materialize_aggregate(plan: AggregatePlan, lowered_elements: list[IRExpr]) -> IRExpr:
        """Build structured aggregate IR from explicitly lowered operands."""
        if plan.constructor is not None:
            return IRCall(callee=f"{plan.constructor}_new", args=[])
        if plan.c_type is not None and plan.field_names:
            return IRCompoundLiteral(
                c_type=CType(text=plan.c_type),
                fields=list(zip(plan.field_names, lowered_elements)),
            )
        if lowered_elements:
            return IRInitializerList(elements=lowered_elements)
        return IRLiteral(text="NULL")

    def plan_static(self, node, provenance: CallableProvenance) -> StaticAggregatePlan | None:
        """Describe a static aggregate without traversing its expressions."""
        if not isinstance(node, (BraceInitializer, ListLiteral)):
            return None
        node_type = self._session.type_of(node)
        self._reject_shallow_initializer(node, node_type, provenance)
        canonical = self._types.canonical_type(node_type)
        field_types = self._aggregate_field_types(canonical)
        return StaticAggregatePlan(field_types=tuple(field_types) if field_types is not None else None)

    def materialize_static(
        self,
        plan: StaticAggregatePlan,
        elements: list[IRExpr],
    ) -> IRInitializerList:
        """Materialize a static aggregate from already lowered elements."""
        if plan.field_types is not None and elements:
            elements.extend(
                self._zero_static_initializer(field_type) for field_type in plan.field_types[len(elements) :]
            )
        return IRInitializerList(elements=elements)

    def _aggregate_field_types(self, type_expr):
        if type_expr is None or type_expr.pointer_depth > 0 or type_expr.is_array:
            return None
        struct_name = type_expr.base.removeprefix("struct ")
        declaration = self._analyzed.struct_table.get(struct_name)
        if declaration is not None and not declaration.is_forward:
            return [field.type for field in declaration.fields]
        if type_expr.base == "Tuple":
            return list(type_expr.generic_args)
        return None

    def _zero_static_initializer(self, type_expr):
        canonical = self._types.canonical_type(type_expr)
        if canonical and (canonical.is_array or self._aggregate_field_types(canonical) is not None):
            return IRInitializerList(elements=[])
        return IRLiteral(text="0")

    def _reject_shallow_initializer(self, node, node_type, provenance: CallableProvenance) -> None:
        canonical = self._types.canonical_type(node_type)
        if canonical is None:
            return
        struct_name = canonical.base.removeprefix("struct ")
        if canonical.is_array or canonical.base == "Tuple" or struct_name in self._analyzed.struct_table:
            self._reject_owned_elements(node.elements, "a shallow aggregate", provenance)

    def _reject_owned_elements(self, elements, aggregate: str, provenance: CallableProvenance) -> None:
        for element in elements:
            if self._ownership.owns_result(element, provenance=provenance):
                raise CodegenError(
                    "caller-owned temporary cannot be embedded in "
                    f"{aggregate}; aggregate class elements are shallow "
                    "borrowed references, so bind the owner to a local first"
                )

    def ensure_cycle_callback_alias(self) -> None:
        """Root the mutually-recursive typed visitor ABI runtime declaration."""
        self._session.require_helper("__btrc_arc_callback_types")

    def slot_visit_stmts(self, type_expr: TypeExpr, slot: IRExpr) -> list:
        """Visit one typed managed slot as a first-class graph edge."""
        action = self._cycles.visit_action(type_expr, set())
        if action is None:
            return []
        emitted_name = self._values.runtime_name(type_expr)
        access = self._cleanup_slots.ensure_arc_slot_adapter(
            CType(text=self._values.emitted_value_c_type(emitted_name))
        )
        call = IRCall(
            callee=IRVar(name="fn"),
            args=[
                IRCast(target_type=CType(text="volatile void*"), expr=IRAddressOf(expr=slot)),
                IRFunctionRef(name=access),
                self._lifetime.arc_type_descriptor(type_expr),
                IRVar(name="context"),
            ],
        )
        return [IRIf(condition=slot, then_block=IRBlock(stmts=[IRExprStmt(expr=call)]))]

    def lower_list_literal(
        self,
        node: ListLiteral,
        lowered_elements: list[IRExpr],
    ):
        """Build a typed list/vector and consume caller-owned elements."""
        list_type = self._analyzed.node_types.get(id(node))
        element_type = (
            list_type.generic_args[0]
            if list_type is not None and list_type.generic_args
            else self._analyzed.node_types.get(id(node.elements[0]))
            if node.elements
            else TypeExpr(base="int")
        )
        if list_type is None:
            list_type = TypeExpr(base="Vector", generic_args=[element_type])
        mangled = self._type_identity.specialization_symbol(list_type.base, list_type.generic_args)
        declarations, sequence, collection, result = self._collection_storage(list_type, mangled, "__list")
        for lowered in lowered_elements:
            sequence.append(
                IRCall(
                    callee=f"{mangled}_push",
                    args=[collection, lowered],
                )
            )
        CollectionLowerer._finish_collection(sequence, collection, result)
        return IRStmtExpr(stmts=declarations, result=IRCommaExpr(expressions=sequence))

    def lower_map_literal(
        self,
        node: MapLiteral,
        lowered_entries: list[tuple[IRExpr, IRExpr]],
    ):
        """Build a typed map and consume caller-owned keys and values."""
        map_type = self._analyzed.node_types.get(id(node))
        if map_type is not None and len(map_type.generic_args) == 2:
            key_type, value_type = map_type.generic_args
        elif node.entries:
            key_type = self._analyzed.node_types.get(id(node.entries[0].key)) or TypeExpr(base="string")
            value_type = self._analyzed.node_types.get(id(node.entries[0].value)) or TypeExpr(base="int")
            map_type = TypeExpr(base="Map", generic_args=[key_type, value_type])
        else:
            key_type, value_type = (TypeExpr(base="string"), TypeExpr(base="int"))
            map_type = TypeExpr(base="Map", generic_args=[key_type, value_type])
        mangled = self._type_identity.specialization_symbol(map_type.base, map_type.generic_args)
        if not node.entries and (not self._cleanup_scope.exception_cleanup_active()):
            return IRCall(callee=f"{mangled}_new", args=[])
        declarations, sequence, collection, result = self._collection_storage(map_type, mangled, "__map")
        for key, value in lowered_entries:
            sequence.append(
                IRCall(
                    callee=f"{mangled}_put",
                    args=[collection, key, value],
                )
            )
        CollectionLowerer._finish_collection(sequence, collection, result)
        return IRStmtExpr(stmts=declarations, result=IRCommaExpr(expressions=sequence))

    def _collection_storage(self, type_expr, mangled, prefix):
        temporary = IRVarDecl(c_type=CType(text=f"{mangled}*"), name=self._session.fresh_temp(prefix))
        self._session.function_declarations.append(temporary)
        declarations = [temporary]
        collection = IRVar(name=temporary.name)
        sequence = [IRBinOp(left=collection, op="=", right=IRCall(callee=f"{mangled}_new", args=[]))]
        result = collection
        if self._cleanup_scope.exception_cleanup_active():
            cleanup_decls, cleanup_exprs = self._lifetime.cleanup_registration(
                temporary, type_expr, "__btrc_collection_cleanup"
            )
            declarations.extend(cleanup_decls)
            sequence.extend(cleanup_exprs)
            result_decl = IRVarDecl(
                c_type=CType(text=f"{mangled}*"), name=self._session.fresh_temp("__btrc_collection_result")
            )
            self._session.function_declarations.append(result_decl)
            declarations.append(result_decl)
            result = IRVar(name=result_decl.name)
        return (declarations, sequence, collection, result)

    @staticmethod
    def _finish_collection(sequence, collection, result):
        if result is not collection:
            sequence.extend(
                [
                    IRBinOp(left=result, op="=", right=collection),
                    IRBinOp(left=collection, op="=", right=IRLiteral(text="NULL")),
                ]
            )
        sequence.append(result)
