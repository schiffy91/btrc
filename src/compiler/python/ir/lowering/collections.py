"""Cohesive collections IR lowering owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCase,
    IRCast,
    IRCommaExpr,
    IRCompoundLiteral,
    IRDeref,
    IRDoWhile,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRFunctionDef,
    IRFunctionRef,
    IRIf,
    IRIndex,
    IRInitializerList,
    IRLiteral,
    IRNode,
    IRReturn,
    IRStatementSequence,
    IRStmt,
    IRStmtExpr,
    IRSwitch,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
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


@dataclass(frozen=True, slots=True)
class CollectionLiteralPlan:
    """A dynamic collection shape whose leaves await ordered lowering."""

    source: ListLiteral | MapLiteral
    leaves: tuple[object, ...]
    entry_width: int


class CollectionLowerer:
    """Own collections lowering for one run."""

    _COLLECTION_CLASS_BASES = frozenset({"Array", "List", "Map", "Set", "Vector"})
    _ASSIGNMENT_OPERATORS = frozenset({"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="})
    _MUTATING_CALL_SLOT: ClassVar[dict[str, int]] = {
        "__btrc_arc_replace_edge": 0,
        "__btrc_safe_realloc": 0,
        "free": 0,
        "memcpy": 0,
        "memmove": 0,
        "memset": 0,
        "qsort": 0,
        "realloc": 0,
    }

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

    @classmethod
    def owns_persistent_element_edges(cls, class_name: str) -> bool:
        """Whether explicit keeps in this class publish collection-owned slots."""
        return class_name in cls._COLLECTION_CLASS_BASES

    def protect_topology_mutation(
        self,
        function: IRFunctionDef,
        collection_type: TypeExpr,
    ) -> bool:
        """Exclude one physical collection edit from concurrent ARC snapshots."""
        concrete = self._types.canonical_type(collection_type) or collection_type
        if (
            concrete.base not in self._COLLECTION_CLASS_BASES
            or not self._cycles.generic_instance_needs_visitor(
                concrete.base,
                list(concrete.generic_args),
            )
            or function.body is None
            or not self._contains_self_storage_mutation(function.body)
        ):
            return False

        token_name = self._session.fresh_temp("__btrc_topology_scope")
        cleanup_enabled = self._cleanup_scope.exception_cleanup_active()
        marker_name = self._session.fresh_temp("__btrc_topology_cleanup") if cleanup_enabled else None
        self._session.require_helper("__btrc_arc_topology_begin")
        self._session.require_helper("__btrc_arc_topology_complete")

        prologue: list[IRStmt] = []
        if marker_name is not None:
            self._session.require_helper("__btrc_cleanup_mark")
            prologue.append(
                IRVarDecl(
                    c_type=CType(text="int"),
                    name=marker_name,
                    init=IRCall(
                        callee="__btrc_cleanup_mark",
                        args=[],
                        helper_ref="__btrc_cleanup_mark",
                    ),
                )
            )
        token_declaration = IRVarDecl(
            c_type=CType(text="void*"),
            name=token_name,
            init=IRCall(
                callee="__btrc_arc_topology_begin",
                args=[],
                helper_ref="__btrc_arc_topology_begin",
            ),
        )
        prologue.append(token_declaration)
        if marker_name is not None:
            self._session.require_helper("__btrc_arc_topology_cleanup")
            prologue.append(
                IRExprStmt(
                    expr=self._cleanup_slots.register(
                        token_declaration,
                        IRFunctionRef(name="__btrc_arc_topology_cleanup"),
                        direct=True,
                    )
                )
            )

        self._rewrite_topology_block(function, function.body, token_name, marker_name)
        if IRStatementSequence(function.body.stmts).may_fall_through():
            function.body.stmts.extend(self._topology_epilogue(token_name, marker_name))
        function.body.stmts[0:0] = prologue
        return True

    def _topology_epilogue(self, token_name: str, marker_name: str | None) -> list[IRStmt]:
        statements: list[IRStmt] = [
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_arc_topology_complete",
                    args=[
                        IRCast(
                            target_type=CType(text="void* volatile*"),
                            expr=IRAddressOf(expr=IRVar(name=token_name)),
                        )
                    ],
                    helper_ref="__btrc_arc_topology_complete",
                )
            )
        ]
        if marker_name is not None:
            self._session.require_helper("__btrc_discard_cleanups_to")
            statements.append(
                IRExprStmt(
                    expr=IRCall(
                        callee="__btrc_discard_cleanups_to",
                        args=[IRVar(name=marker_name)],
                        helper_ref="__btrc_discard_cleanups_to",
                    )
                )
            )
        return statements

    def _rewrite_topology_block(
        self,
        function: IRFunctionDef,
        block: IRBlock,
        token_name: str,
        marker_name: str | None,
    ) -> None:
        rewritten: list[IRStmt] = []
        for statement in block.stmts:
            self._rewrite_nested_topology_returns(
                function,
                statement,
                token_name,
                marker_name,
            )
            if isinstance(statement, IRReturn):
                if statement.value is not None:
                    result_name = self._session.fresh_temp("__btrc_topology_return")
                    rewritten.append(
                        IRVarDecl(
                            c_type=function.return_type,
                            name=result_name,
                            init=statement.value,
                        )
                    )
                    statement.value = IRVar(name=result_name)
                rewritten.extend(self._topology_epilogue(token_name, marker_name))
            rewritten.append(statement)
        block.stmts = rewritten

    def _rewrite_nested_topology_returns(
        self,
        function: IRFunctionDef,
        statement: IRStmt,
        token_name: str,
        marker_name: str | None,
    ) -> None:
        if isinstance(statement, IRBlock):
            self._rewrite_topology_block(function, statement, token_name, marker_name)
        elif isinstance(statement, IRIf):
            self._rewrite_topology_block(function, statement.then_block, token_name, marker_name)
            if statement.else_block is not None:
                self._rewrite_topology_block(function, statement.else_block, token_name, marker_name)
        elif isinstance(statement, (IRWhile, IRDoWhile, IRFor)):
            self._rewrite_topology_block(function, statement.body, token_name, marker_name)
        elif isinstance(statement, IRSwitch):
            for case in statement.cases:
                self._rewrite_topology_case(function, case, token_name, marker_name)

    def _rewrite_topology_case(
        self,
        function: IRFunctionDef,
        case: IRCase,
        token_name: str,
        marker_name: str | None,
    ) -> None:
        block = IRBlock(stmts=case.body)
        self._rewrite_topology_block(function, block, token_name, marker_name)
        case.body = block.stmts

    def _contains_self_storage_mutation(self, value: object) -> bool:
        aliases: set[str] = set()
        while self._collect_self_storage_aliases(value, aliases):
            pass
        return any(self._is_self_storage_mutation(node, aliases) for node in IRNode.walk_value(value))

    def _collect_self_storage_aliases(self, value: object, aliases: set[str]) -> bool:
        changed = False
        for node in IRNode.walk_value(value):
            if isinstance(node, IRVarDecl) and node.init is not None:
                changed |= self._add_self_storage_alias(node.name, node.init, aliases)
            elif isinstance(node, IRAssign) and isinstance(node.target, IRVar):
                changed |= self._add_self_storage_alias(node.target.name, node.value, aliases)
            elif isinstance(node, IRBinOp) and node.op == "=" and isinstance(node.left, IRVar):
                changed |= self._add_self_storage_alias(node.left.name, node.right, aliases)
        return changed

    def _add_self_storage_alias(self, name: str, source: object, aliases: set[str]) -> bool:
        if name in aliases or not self._is_rooted_in_self(source, aliases):
            return False
        aliases.add(name)
        return True

    def _is_self_storage_mutation(self, value: object, aliases: set[str]) -> bool:
        if isinstance(value, IRAssign) and self._is_self_storage(value.target, aliases):
            return True
        if (
            isinstance(value, IRBinOp)
            and value.op in self._ASSIGNMENT_OPERATORS
            and self._is_self_storage(value.left, aliases)
        ):
            return True
        if isinstance(value, IRUnaryOp) and value.op in {"++", "--"} and self._is_self_storage(value.operand, aliases):
            return True
        if isinstance(value, IRCall) and isinstance(value.callee, str):
            slot = self._MUTATING_CALL_SLOT.get(value.callee)
            if slot is not None and slot < len(value.args):
                return self._is_rooted_in_self(value.args[slot], aliases)
        return False

    def _is_self_storage(self, value: object, aliases: set[str]) -> bool:
        if isinstance(value, (IRFieldAccess, IRIndex)):
            return self._is_rooted_in_self(value.obj, aliases)
        if isinstance(value, IRDeref):
            return self._is_rooted_in_self(value.expr, aliases)
        if isinstance(value, IRUnaryOp) and value.op == "*":
            return self._is_rooted_in_self(value.operand, aliases)
        return False

    def _is_rooted_in_self(self, value: object, aliases: set[str]) -> bool:
        if isinstance(value, IRVar):
            return value.name == "self" or value.name in aliases
        if isinstance(value, (IRFieldAccess, IRIndex)):
            return self._is_rooted_in_self(value.obj, aliases)
        if isinstance(value, (IRAddressOf, IRCast, IRDeref)):
            return self._is_rooted_in_self(value.expr, aliases)
        if isinstance(value, IRUnaryOp):
            return self._is_rooted_in_self(value.operand, aliases)
        if isinstance(value, IRBinOp) and value.op in {"+", "-"}:
            return self._is_rooted_in_self(
                value.left,
                aliases,
            ) or self._is_rooted_in_self(value.right, aliases)
        return False

    def plan_brace(self, node: BraceInitializer, provenance: CallableProvenance) -> AggregatePlan:
        """Resolve one context-typed aggregate without lowering elements."""
        node_type = self._session.type_of(node)
        self._reject_shallow_initializer(node, node_type, provenance)
        canonical = self._types.canonical_type(node_type)
        if (
            canonical
            and canonical.generic_args
            and (canonical.base in self._analyzed.class_table or canonical.base in self._COLLECTION_CLASS_BASES)
        ):
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
        if plan.c_type is not None:
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
        source_flow = provenance.plan_evaluation(elements)
        for element in elements:
            entry = source_flow.entries.get(id(element), source_flow.incoming)
            with provenance.at_flow(entry):
                owns_result = self._ownership.owns_result(element, provenance=provenance)
            if owns_result:
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

    def cycle_storage_visit_stmts(
        self,
        type_expr: TypeExpr,
        collection: IRExpr,
    ) -> list[IRStmt] | None:
        """Traverse the physical managed slots of a built-in collection."""
        concrete = self._types.canonical_type(type_expr) or type_expr
        arguments = list(concrete.generic_args)
        if concrete.base in {"Array", "Vector"} and len(arguments) == 1:
            return self._dense_cycle_storage_visit_stmts(
                collection,
                arguments[0],
            )
        if concrete.base == "Map" and len(arguments) == 2:
            return self._hashed_cycle_storage_visit_stmts(
                collection,
                (("keys", arguments[0]), ("values", arguments[1])),
            )
        if concrete.base == "Set" and len(arguments) == 1:
            return self._hashed_cycle_storage_visit_stmts(
                collection,
                (("keys", arguments[0]),),
            )
        return None

    def _dense_cycle_storage_visit_stmts(
        self,
        collection: IRExpr,
        element_type: TypeExpr,
    ) -> list[IRStmt]:
        index_name = self._session.fresh_temp("__btrc_visit_index")
        index = IRVar(name=index_name)
        slot = IRIndex(
            obj=IRFieldAccess(obj=collection, field="data", arrow=True),
            index=index,
        )
        visits = self.slot_visit_stmts(element_type, slot)
        if not visits:
            return []
        return [
            self._cycle_storage_loop(
                collection,
                index_name,
                "len",
                visits,
            )
        ]

    def _hashed_cycle_storage_visit_stmts(
        self,
        collection: IRExpr,
        slots: tuple[tuple[str, TypeExpr], ...],
    ) -> list[IRStmt]:
        index_name = self._session.fresh_temp("__btrc_visit_index")
        index = IRVar(name=index_name)
        visits = [
            statement
            for field_name, field_type in slots
            for statement in self.slot_visit_stmts(
                field_type,
                IRIndex(
                    obj=IRFieldAccess(obj=collection, field=field_name, arrow=True),
                    index=index,
                ),
            )
        ]
        if not visits:
            return []
        occupied = IRIndex(
            obj=IRFieldAccess(obj=collection, field="occupied", arrow=True),
            index=index,
        )
        return [
            self._cycle_storage_loop(
                collection,
                index_name,
                "cap",
                [IRIf(condition=occupied, then_block=IRBlock(stmts=visits))],
            )
        ]

    @staticmethod
    def _cycle_storage_loop(
        collection: IRExpr,
        index_name: str,
        bound_field: str,
        body: list[IRStmt],
    ) -> IRFor:
        return IRFor(
            init=IRVarDecl(c_type=CType(text="int"), name=index_name, init=IRLiteral(text="0")),
            condition=IRBinOp(
                left=IRVar(name=index_name),
                op="<",
                right=IRFieldAccess(obj=collection, field=bound_field, arrow=True),
            ),
            update=IRUnaryOp(op="++", operand=IRVar(name=index_name), prefix=False),
            body=IRBlock(stmts=body),
        )

    @staticmethod
    def plan_literal(node: ListLiteral | MapLiteral) -> CollectionLiteralPlan:
        """Preserve literal source order without traversing any leaf."""
        if isinstance(node, ListLiteral):
            return CollectionLiteralPlan(
                source=node,
                leaves=tuple(node.elements),
                entry_width=1,
            )
        return CollectionLiteralPlan(
            source=node,
            leaves=tuple(leaf for entry in node.entries for leaf in (entry.key, entry.value)),
            entry_width=2,
        )

    def literal_leaf_targets(self, plan: CollectionLiteralPlan) -> tuple[TypeExpr | None, ...]:
        """Return the storage target type each literal leaf is prepared against.

        A collection's declared element type governs its leaves, so a
        ``Vector<string>`` literal converts a class element through ``toString``
        instead of storing the class pointer.
        """

        collection_type = self._session.type_of(plan.source)
        arguments = collection_type.generic_args if collection_type is not None else []
        if plan.entry_width == 1:
            element = arguments[0] if arguments else None
            return (element,) * len(plan.leaves)
        if len(arguments) != 2:
            return (None,) * len(plan.leaves)
        key, value = arguments
        return tuple(key if index % 2 == 0 else value for index in range(len(plan.leaves)))

    def materialize_literal(
        self,
        plan: CollectionLiteralPlan,
        lowered_leaves: list[IRExpr],
    ) -> IRExpr:
        """Allocate and populate one collection from stabilized leaf values."""
        if len(lowered_leaves) != len(plan.leaves):
            raise ValueError("collection literal materialization requires every planned leaf")
        if plan.entry_width == 1:
            assert isinstance(plan.source, ListLiteral)
            return self.lower_list_literal(plan.source, lowered_leaves)
        if plan.entry_width != 2 or not isinstance(plan.source, MapLiteral):
            raise ValueError("unsupported collection literal entry shape")
        entries = [(lowered_leaves[index], lowered_leaves[index + 1]) for index in range(0, len(lowered_leaves), 2)]
        return self.lower_map_literal(plan.source, entries)

    def lower_list_literal(
        self,
        node: ListLiteral,
        lowered_elements: list[IRExpr],
    ):
        """Build a typed list/vector and consume caller-owned elements."""
        list_type = self._session.type_of(node)
        element_type = (
            list_type.generic_args[0]
            if list_type is not None and list_type.generic_args
            else self._session.type_of(node.elements[0])
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
        map_type = self._session.type_of(node)
        if map_type is not None and len(map_type.generic_args) == 2:
            key_type, value_type = map_type.generic_args
        elif node.entries:
            key_type = self._session.type_of(node.entries[0].key) or TypeExpr(base="string")
            value_type = self._session.type_of(node.entries[0].value) or TypeExpr(base="int")
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
