"""Cohesive expressions IR lowering owner."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.types import IndexedProtocolResolver, TypeIdentity, TypeSystem
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRDeref,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDecl,
    IRFunctionRef,
    IRLiteral,
    IRParam,
    IRSizeof,
    IRStmt,
    IRStmtExpr,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.syntax.ast.generated import (
    AssignExpr,
    BinaryExpr,
    BoolLiteral,
    BraceInitializer,
    CallExpr,
    CastExpr,
    CharLiteral,
    FieldAccessExpr,
    FloatLiteral,
    FStringExpr,
    FStringLiteral,
    FStringText,
    Identifier,
    IndexExpr,
    IntLiteral,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    NullLiteral,
    SelfExpr,
    SizeofExpr,
    SizeofExprOp,
    SizeofType,
    SpawnExpr,
    StringLiteral,
    SuperExpr,
    TernaryExpr,
    TupleLiteral,
    TypeExpr,
    UnaryExpr,
)

from .calls import CallableReturnABI, CallDispatch, CallOperand, CallResultPlan, ValuePreparationPlan
from .gpu import GpuSourceArguments
from .ownership import ManagedSlotTarget, ProjectionStorageOperand
from .storage import StorageKind
from .types import CodegenError, CTypeLowerer

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalyzedProgram

    from .calls import (
        CallableEnvironment,
        CallableProvenance,
        CallableStorageBoundary,
        CallBoundaryLowerer,
        CallLowerer,
        DefaultArgumentLoweringContext,
    )
    from .collections import CollectionLowerer
    from .concurrency import ConcurrencyLowerer, SyncMethodPlan
    from .gpu import GpuLowerer
    from .ownership import (
        CleanupScopeState,
        CleanupSlotRegistry,
        ManagedLifetimeLowerer,
        ManagedValueSemantics,
        OwnershipLowerer,
        OwnershipOperandOrder,
    )
    from .session import LoweringSession
    from .storage import StorageLowerer
_FLAT_CHAIN_MIN_TERMS = 32


@dataclass(frozen=True)
class LambdaPlan:
    """Deferred lambda declaration consumed by the function owner."""

    node: object
    function_name: str
    capture_abis: tuple[tuple[object, CallableReturnABI], ...]


@dataclass(frozen=True, slots=True)
class FieldAccessMaterialization:
    node: FieldAccessExpr


@dataclass(frozen=True, slots=True)
class IndexMaterialization:
    node: IndexExpr


@dataclass(frozen=True, slots=True)
class AggregateMaterialization:
    plan: object
    elements: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class StaticInitializerMaterialization:
    """One recursive C-initializer shape whose scalar leaves may be stabilized."""

    source: object
    plan: object | None
    elements: tuple[StaticInitializerMaterialization, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparedStaticInitializer:
    """Ordered statement work surrounding one declaration-only initializer."""

    before: tuple[IRStmt, ...]
    value: IRExpr
    after: tuple[IRStmt, ...]


@dataclass(frozen=True, slots=True)
class CollectionLiteralMaterialization:
    """A collection literal whose leaves are stabilized by the boundary.

    ``leaf_targets`` carries the collection's declared element (and, for a map,
    key/value) types so each leaf is prepared against its storage target rather
    than being pushed with its own source type.
    """

    plan: object
    leaf_targets: tuple[TypeExpr | None, ...] = ()


@dataclass(frozen=True, slots=True)
class BinaryMaterialization:
    node: BinaryExpr


@dataclass(frozen=True, slots=True)
class UnaryMaterialization:
    node: UnaryExpr


@dataclass(frozen=True, slots=True)
class AssignmentMaterialization:
    node: AssignExpr


@dataclass(frozen=True, slots=True)
class OptionalMethodCallMaterialization:
    node: CallExpr


@dataclass(frozen=True, slots=True)
class SyncMethodMaterialization:
    """A Mutex call whose operands are stabilized by the call boundary."""

    plan: SyncMethodPlan
    receiver: object
    arguments: tuple[object, ...]
    argument_targets: tuple[TypeExpr | None, ...]


@dataclass(frozen=True, slots=True)
class ProjectionDependencyKey:
    """Identity for one hidden backing-storage call operand."""

    index: int


@dataclass(frozen=True, slots=True)
class ProjectionStorageRequest:
    """One projected source and its surrounding call-lifetime context."""

    source: object
    parameter_index: int | None = None
    has_later_effects: bool = True


@dataclass(frozen=True, slots=True)
class StabilizedProjectionStorage:
    """One projection root materialized by the shared operand transaction."""

    operand: ProjectionStorageOperand
    type_expr: TypeExpr
    value: IRVar


@dataclass(frozen=True, slots=True)
class PreparedProjectionStorage:
    """Stable physical projection and the ordered work that establishes it."""

    declarations: tuple[IRVarDecl, ...]
    assignments: tuple[IRExpr, ...]
    value: IRExpr
    storage: tuple[StabilizedProjectionStorage, ...]


@dataclass(frozen=True, slots=True)
class OptionalAccessPlan:
    field: str | None = None
    callee: str | None = None


class ExpressionLowerer:
    """Own expressions lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        default_context: DefaultArgumentLoweringContext,
        type_identity: TypeIdentity,
        index_protocols: IndexedProtocolResolver,
        ownership: OwnershipLowerer,
        values: ManagedValueSemantics,
        lifetime: ManagedLifetimeLowerer,
        cleanup_slots: CleanupSlotRegistry,
        cleanup_scope: CleanupScopeState,
        operand_order: OwnershipOperandOrder,
        call_boundary: CallBoundaryLowerer,
        callable_boundaries: CallableStorageBoundary,
        storage: StorageLowerer,
        calls: CallLowerer,
        collections: CollectionLowerer,
        concurrency: ConcurrencyLowerer,
        gpu: GpuLowerer,
        *,
        program_has_exceptions: bool,
        source_visible_helpers: frozenset[str] | set[str],
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._default_arguments = default_context
        self._type_identity = type_identity
        self._index_protocols = index_protocols
        self._ownership = ownership
        self._values = values
        self._lifetime = lifetime
        self._cleanup_slots = cleanup_slots
        self._cleanup_scope = cleanup_scope
        self._operand_order = operand_order
        self._call_boundary = call_boundary
        self._callable_boundaries = callable_boundaries
        self._storage = storage
        self._calls = calls
        self._collections = collections
        self._concurrency = concurrency
        self._gpu = gpu
        self._program_has_exceptions = bool(program_has_exceptions)
        self._source_visible_helpers = frozenset(source_visible_helpers)

    def lower_expression(self, node, provenance: CallableProvenance):
        return self.lower_expr(
            node,
            provenance,
        )

    def prepare_projection_storage(
        self,
        source,
        provenance: CallableProvenance,
    ) -> PreparedProjectionStorage | None:
        """Evaluate backing storage once before exposing a raw projection.

        The returned transaction deliberately leaves managed-root ownership to
        the consuming domain.  Calls release at the call boundary; iteration
        instead adopts or keeps the stabilized root for the whole loop.
        """
        operands = self._ownership.projection_storage_operands(source, provenance)
        if not operands:
            return None

        evaluation = self._call_boundary.start()
        fact_types: dict[int, TypeExpr] = {}
        stabilized: list[StabilizedProjectionStorage] = []
        for operand in operands:
            type_expr = self._types.resolve_active_type(self._session.type_of(operand.expression))
            if type_expr is None:
                self._ownership.reject_opaque_ordering(operand.expression, "projection storage")
            fact_types[id(operand.expression)] = type_expr
            with self._session.operand_scope(evaluation.values, fact_types, evaluation.ownership):
                lowered = self.lower_expr(operand.expression, provenance)
            self._call_boundary.append(
                evaluation,
                CallOperand(
                    node=operand.expression,
                    type_expr=type_expr,
                    c_type=self._operand_order.operand_c_type(operand.expression, type_expr),
                    lowered=lowered,
                ),
            )
            stable = evaluation.values[id(operand.expression)]
            if not isinstance(stable, IRVar):
                raise CodegenError("projection storage did not materialize an addressable operand")
            stabilized.append(
                StabilizedProjectionStorage(
                    operand=operand,
                    type_expr=type_expr,
                    value=stable,
                )
            )

        with self._session.operand_scope(evaluation.values, fact_types, evaluation.ownership):
            value = self.lower_expr(source, provenance)
        return PreparedProjectionStorage(
            declarations=tuple(evaluation.declarations),
            assignments=tuple(evaluation.before_value),
            value=value,
            storage=tuple(stabilized),
        )

    def lower_gpu_arguments(
        self,
        call: CallExpr,
        provenance: CallableProvenance,
    ) -> GpuSourceArguments:
        """Stabilize GPU source operands and raw-projection storage in order."""
        plans = self._gpu.plan_source_arguments(call, provenance)
        if not any(plan.projection_storage for plan in plans):
            return GpuSourceArguments(
                declarations=(),
                assignments=(),
                cleanup=(),
                values=tuple(self.lower_expr(plan.source, provenance) for plan in plans),
                capacities=tuple(None for _plan in plans),
                stabilized=tuple(False for _plan in plans),
                owned=tuple(plan.owned for plan in plans),
                pinned=tuple(plan.pin for plan in plans),
            )
        evaluation = self._call_boundary.start()
        fact_types = {id(plan.source): plan.type_expr for plan in plans if plan.type_expr is not None}
        for plan in plans:
            for storage in plan.projection_storage:
                storage_type = self._types.resolve_active_type(self._session.type_of(storage.expression))
                if storage_type is None:
                    self._ownership.reject_opaque_ordering(storage.expression, "GPU projection storage")
                fact_types[id(storage.expression)] = storage_type

        values = []
        capacities = []
        for plan in plans:
            for storage in plan.projection_storage:
                storage_type = fact_types[id(storage.expression)]
                with self._session.operand_scope(evaluation.values, fact_types, evaluation.ownership):
                    lowered_storage = self.lower_expr(storage.expression, provenance)
                self._call_boundary.append(
                    evaluation,
                    CallOperand(
                        node=storage.expression,
                        type_expr=storage_type,
                        c_type=self._operand_order.operand_c_type(storage.expression, storage_type),
                        keep=storage.keep,
                        owned=storage.owned,
                        lowered=lowered_storage,
                    ),
                )

            if plan.type_expr is None:
                self._ownership.reject_opaque_ordering(plan.source, "GPU argument")
            with self._session.operand_scope(evaluation.values, fact_types, evaluation.ownership):
                lowered = self.lower_expr(plan.source, provenance)
                capacity = (
                    self._gpu.source_array_capacity(plan.source, lowered, provenance)
                    if plan.requires_capacity
                    else None
                )
            self._call_boundary.append(
                evaluation,
                CallOperand(
                    node=plan.source,
                    type_expr=plan.type_expr,
                    c_type=self._operand_order.operand_c_type(plan.source, plan.type_expr),
                    pin=plan.pin,
                    owned=plan.owned,
                    lowered=lowered,
                ),
            )
            values.append(evaluation.values[id(plan.source)])
            if capacity is None:
                capacities.append(None)
                continue
            capacity_slot = object()
            int_type = TypeExpr(base="int")
            self._call_boundary.append(
                evaluation,
                CallOperand(
                    node=capacity_slot,
                    type_expr=int_type,
                    c_type="int",
                    lowered=capacity,
                ),
            )
            capacities.append(evaluation.values[id(capacity_slot)])

        return GpuSourceArguments(
            declarations=tuple(evaluation.declarations),
            assignments=tuple(evaluation.before_value),
            cleanup=tuple(evaluation.suffix),
            values=tuple(values),
            capacities=tuple(capacities),
            stabilized=tuple(True for _plan in plans),
            owned=tuple(plan.owned for plan in plans),
            pinned=tuple(plan.pin for plan in plans),
        )

    def _sequence_operands(
        self,
        nodes,
        provenance: CallableProvenance,
        *,
        materialization,
        result_type,
        promote_result: bool = False,
        result_owned: bool = False,
        keep_nodes=(),
        pin_nodes=(),
        force: bool = False,
        allow_trailing_opaque: bool = False,
        opaque_context: str = "expression",
    ):
        """Materialize an expression's eager operands through one boundary."""
        if isinstance(materialization, SyncMethodMaterialization):
            operand_targets = (None, *materialization.argument_targets)
        elif isinstance(materialization, CollectionLiteralMaterialization) and materialization.leaf_targets:
            operand_targets = materialization.leaf_targets
        else:
            operand_targets = (None,) * len(nodes)
        prepared = self._prepare_operand_evaluation(
            nodes,
            provenance,
            operand_targets=operand_targets,
            keep_nodes=keep_nodes,
            pin_nodes=pin_nodes,
            force=force,
            allow_trailing_opaque=allow_trailing_opaque,
            opaque_context=opaque_context,
        )
        if prepared is None:
            return None
        evaluation, fact_types = prepared
        with self._session.operand_scope(evaluation.values, fact_types, evaluation.ownership):
            call = self._materialize_sequenced(materialization, provenance)
        return self._call_boundary.materialize(
            evaluation,
            call,
            CallResultPlan(
                c_type=(self._types.render(result_type) if result_type is not None else None),
                type_expr=result_type,
                promote=promote_result,
                owned=bool(result_owned or promote_result),
            ),
        )

    def _prepare_operand_evaluation(
        self,
        nodes,
        provenance: CallableProvenance,
        *,
        operand_targets,
        keep_nodes=(),
        pin_nodes=(),
        force: bool = False,
        allow_trailing_opaque: bool = False,
        opaque_context: str = "expression",
    ):
        """Build the shared typed source-order transaction for eager operands."""
        if self._session.is_unevaluated:
            return None
        keep_ids = {id(node) for node in keep_nodes}
        pin_ids = {id(node) for node in pin_nodes}
        if len(operand_targets) != len(nodes):
            raise ValueError("sequenced operand targets do not match source operands")
        source_flow = provenance.plan_evaluation(nodes)
        facts = []
        for node, target_type in zip(nodes, operand_targets):
            contextual_type = target_type if target_type is not None and self._session.type_of(node) is None else None
            entry = source_flow.entries.get(id(node), source_flow.incoming)
            with (
                provenance.at_flow(entry),
                self._session.operand_scope(
                    {},
                    {id(node): contextual_type} if contextual_type is not None else None,
                ),
            ):
                if target_type is not None:
                    preparation = self._calls.plan_value(node, target_type, provenance)
                    type_expr = preparation.effective_type
                    owned = preparation.owned
                else:
                    type_expr = self._session.type_of(node)
                    owned = self._ownership.lowered_result_is_owned(node, provenance=provenance)
            facts.append(
                (
                    node,
                    type_expr,
                    target_type,
                    contextual_type,
                    owned,
                    id(node) in keep_ids,
                    id(node) in pin_ids and not owned and self._ownership.borrowed_value_can_be_pinned(node),
                )
            )
        effects = [
            bool(
                self._operand_order.has_effect(node)
                or (
                    target_type is not None
                    and self._calls.requires_string_conversion(target_type, self._session.type_of(node))
                )
            )
            for node, _type_expr, target_type, *_rest in facts
        ]
        automatic_pins = self._operand_order.source_order_pin_flags(
            nodes,
            [type_expr for _node, type_expr, *_rest in facts],
            [owned for _node, _type_expr, _target, _contextual, owned, *_rest in facts],
            effects=effects,
        )
        facts = [
            (node, type_expr, target_type, contextual_type, owned, keep, pin or automatic_pins[index])
            for index, (node, type_expr, target_type, contextual_type, owned, keep, pin) in enumerate(facts)
        ]
        lifetime_required = any(
            owned or keep or pin for _node, _type_expr, _target, _contextual, owned, keep, pin in facts
        )
        if not (force or lifetime_required):
            return None
        missing = [index for index, (_node, type_expr, *_rest) in enumerate(facts) if type_expr is None]
        if missing:
            trailing = len(facts) - 1
            if allow_trailing_opaque and missing == [trailing]:
                node, _type_expr, _target, _contextual, owned, keep, pin = facts.pop()
                if owned or keep or pin:
                    self._ownership.reject_opaque_ordering(node, opaque_context)
            else:
                self._ownership.reject_opaque_ordering(facts[missing[0]][0], opaque_context)
        fact_types = {id(node): type_expr for node, type_expr, *_rest in facts}

        evaluation = self._call_boundary.start()
        for node, type_expr, target_type, contextual_type, owned, keep, pin in facts:
            override_types = {key: fact_types[key] for key in evaluation.values if key in fact_types}
            if contextual_type is not None:
                override_types[id(node)] = contextual_type
            with self._session.operand_scope(evaluation.values, override_types, evaluation.ownership):
                lowered = (
                    self.prepare_value(node, target_type, provenance).value
                    if target_type is not None
                    else self.lower_expression(node, provenance)
                )
            self._call_boundary.append(
                evaluation,
                CallOperand(
                    node=node,
                    type_expr=type_expr,
                    c_type=self._operand_order.operand_c_type(node, type_expr),
                    keep=keep,
                    pin=pin,
                    owned=owned,
                    lowered=lowered,
                ),
            )
        return evaluation, fact_types

    def _materialize_sequenced(self, materialization, provenance: CallableProvenance) -> IRExpr:
        """Materialize one inert expression plan after operand stabilization."""
        if isinstance(materialization, FieldAccessMaterialization):
            return self._lower_field_access_plain(materialization.node, provenance)
        if isinstance(materialization, IndexMaterialization):
            return self._lower_index_plain(materialization.node, provenance)
        if isinstance(materialization, AggregateMaterialization):
            return self._collections.materialize_aggregate(
                materialization.plan,
                [self.lower_expr(element, provenance) for element in materialization.elements],
            )
        if isinstance(materialization, CollectionLiteralMaterialization):
            return self._collections.materialize_literal(
                materialization.plan,
                [self.lower_expr(leaf, provenance) for leaf in materialization.plan.leaves],
            )
        if isinstance(materialization, BinaryMaterialization):
            return self._lower_binary_plain(materialization.node, provenance)
        if isinstance(materialization, UnaryMaterialization):
            return self._lower_unary_plain(materialization.node, provenance)
        if isinstance(materialization, AssignmentMaterialization):
            return self._lower_assignment_plain(materialization.node, provenance)
        if isinstance(materialization, OptionalMethodCallMaterialization):
            return self._lower_optional_method_call_plain(materialization.node, provenance)
        if isinstance(materialization, SyncMethodMaterialization):
            return self._concurrency.materialize_sync_method(
                materialization.plan,
                self.lower_expr(materialization.receiver, provenance),
                [self.lower_expr(argument, provenance) for argument in materialization.arguments],
            )
        raise TypeError(f"unsupported sequenced expression plan: {type(materialization).__name__}")

    def lower_call_plan(
        self,
        plan,
        provenance: CallableProvenance,
    ):
        if plan.dispatch is CallDispatch.IMMEDIATE_LAMBDA:
            return self._lower_immediate_lambda_call(plan, provenance)
        return self._lower_bound_call_plan(plan, provenance)

    def _lower_bound_call_plan(
        self,
        plan,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Traverse a call once in language order, then form its ABI order."""
        callable_environment = (
            provenance.environment(plan.callee.name)
            if plan.dispatch is CallDispatch.CALLABLE and isinstance(plan.callee, Identifier)
            else None
        )
        dynamic_callee = bool(
            plan.dispatch is CallDispatch.CALLABLE and plan.callee is not None and callable_environment is None
        )
        binding_effects = [self._call_binding_has_effect(plan, binding) for binding in plan.bindings]
        projected_sources = [
            *([ProjectionStorageRequest(plan.callee)] if dynamic_callee else []),
            *([ProjectionStorageRequest(plan.receiver)] if plan.receiver is not None else []),
            *(
                ProjectionStorageRequest(
                    binding.source,
                    parameter_index=binding.parameter_index,
                    has_later_effects=any(binding_effects[index + 1 :]),
                )
                for index, binding in enumerate(plan.bindings)
                if not binding.is_default
            ),
        ]
        source_flow = provenance.plan_evaluation(request.source for request in projected_sources)
        self._calls.reject_owned_rich_enum_arguments(plan, provenance, source_flow.entries)
        projection_storage = self._projection_storage_by_source(
            projected_sources,
            provenance,
            call=plan.source if isinstance(plan.source, CallExpr) else None,
            flow_entries=source_flow.entries,
        )
        deferred_ids = frozenset(projection_storage)
        if callable_environment is not None:
            callee = callable_environment.function_name
        elif plan.callee is None:
            callee = None
        elif plan.dispatch is CallDispatch.CALLABLE and id(plan.callee) not in deferred_ids:
            callee = self.lower_expr(plan.callee, provenance)
        elif isinstance(plan.callee, str):
            callee = plan.callee
        elif isinstance(plan.callee, Identifier):
            callee = provenance.source_function_c_name(plan.callee.name, plan.source)
        elif id(plan.callee) in deferred_ids:
            callee = None
        else:
            callee = self.lower_expr(plan.callee, provenance)

        call_effect = provenance.capture_call_effect(plan.source) if isinstance(plan.source, CallExpr) else None

        receiver = (
            self.lower_expr(plan.receiver, provenance)
            if plan.receiver is not None and id(plan.receiver) not in deferred_ids
            else None
        )
        explicit = []
        for binding_index, binding in enumerate(plan.bindings):
            if binding.is_default:
                continue
            parameter = self._bound_parameter(plan, binding.parameter_index)
            entry = source_flow.entries.get(id(binding.source), source_flow.incoming)
            with provenance.at_flow(entry):
                if parameter is None:
                    type_expr = self._types.resolve_active_type(
                        self._default_arguments.resolve_type(self._session.type_of(binding.source))
                    )
                    owned = self._ownership.lowered_result_is_owned(binding.source, provenance=provenance)
                else:
                    self._callable_boundaries.reject_call_argument(
                        parameter,
                        binding.source,
                        provenance,
                    )
                    target_type = self._calls.argument_target_type(parameter, binding.source)
                    preparation = self._calls.plan_value(
                        binding.source,
                        target_type,
                        provenance,
                    )
                    type_expr = preparation.effective_type
                    owned = preparation.owned
            explicit.append((binding_index, binding, parameter, None, type_expr, owned))

        leading = []
        if plan.dispatch is CallDispatch.CALLABLE and plan.callee is not None and callable_environment is None:
            callee_type = self._types.resolve_active_type(self._session.type_of(plan.callee))
            if callee_type is None and isinstance(plan.callee, Identifier):
                callee_type = self._types.resolve_active_type(self._analyzed.global_var_types.get(plan.callee.name))
            leading.append(("callee", plan.callee, callee, callee_type, False, False, False))
        if plan.receiver is not None:
            receiver_type = self._types.resolve_active_type(self._session.type_of(plan.receiver))
            receiver_entry = source_flow.entries.get(id(plan.receiver), source_flow.incoming)
            with provenance.at_flow(receiver_entry):
                receiver_owned = self._ownership.lowered_result_is_owned(plan.receiver, provenance=provenance)
            leading.append(("receiver", plan.receiver, receiver, receiver_type, receiver_owned, False, False))

        rows = list(leading)
        for binding_index, binding, parameter, value, type_expr, owned in explicit:
            rows.append(
                (
                    binding_index,
                    binding.source,
                    value,
                    type_expr,
                    owned,
                    bool(parameter is not None and parameter.keep and self._values.is_managed(type_expr)),
                    bool(parameter is not None and parameter.transferred and owned),
                )
            )
        for binding_index, binding in enumerate(plan.bindings):
            if not binding.is_default:
                continue
            parameter = self._bound_parameter(plan, binding.parameter_index)
            if parameter is None:
                raise CodegenError("default call binding has no resolved parameter")
            managed = self._values.is_managed(parameter.type)
            rows.append(
                (
                    binding_index,
                    binding.source,
                    None,
                    parameter.type,
                    managed,
                    bool(managed and parameter.keep),
                    bool(managed and parameter.transferred),
                )
            )

        rows = self._expand_projection_rows(rows, projection_storage)

        nodes = [row[1] for row in rows]
        types = [row[3] for row in rows]
        owned = [row[4] for row in rows]
        effects = [
            binding_effects[key] if isinstance(key, int) else self._operand_order.has_effect(source)
            for key, source, *_rest in rows
        ]
        pins = self._operand_order.source_order_pin_flags(nodes, types, owned, effects=effects)
        first_default = next(
            (index for index, row in enumerate(rows) if isinstance(row[0], int) and plan.bindings[row[0]].is_default),
            None,
        )
        if first_default is not None:
            for index in range(first_default):
                pins[index] = bool(
                    pins[index]
                    or (
                        not owned[index]
                        and self._values.is_managed(types[index])
                        and self._ownership.borrowed_value_can_be_pinned(nodes[index])
                    )
                )

        result_type = self._call_result_type(plan)
        result_owned = (
            self._ownership.source_call_owns_result(
                plan.source,
                provenance,
                call_effect,
            )
            if isinstance(plan.source, CallExpr)
            else self._ownership.owns_result(plan.source, provenance=provenance)
        )
        promote_result = bool(self._values.is_managed(result_type) and not result_owned)
        needs_boundary = bool(
            projection_storage
            or first_default is not None
            or promote_result
            or self._operand_order.operands_require_order(nodes)
            or any(row[4] or row[5] or row[6] or pins[index] for index, row in enumerate(rows))
        )
        if not needs_boundary:
            values = {}
            source_types = {}
            for binding_index, binding, parameter, _value, type_expr, _owned in explicit:
                if parameter is None:
                    value = self.lower_expr(binding.source, provenance)
                else:
                    prepared = self.prepare_value(
                        binding.source,
                        self._calls.argument_target_type(parameter, binding.source),
                        provenance,
                    )
                    value = prepared.value
                    type_expr = prepared.effective_type
                values[binding_index] = value
                source_types[binding_index] = type_expr
            arguments = self._abi_call_arguments(plan, values, source_types)
            if callable_environment is not None:
                arguments.append(self._callable_environment_argument(callable_environment))
            return self._calls.materialize(plan, callee, receiver, arguments)

        evaluation = self._call_boundary.start()
        row_values: dict[object, IRExpr] = {}
        source_types: dict[int, TypeExpr] = {}
        bound_nodes = self._calls.bound_nodes_by_parameter(list(plan.parameters), list(plan.bindings))
        explicit_by_index = {row[0]: row for row in explicit}
        fact_types = {id(source): type_expr for _key, source, _value, type_expr, *_rest in rows}
        for row_index, row in enumerate(rows):
            key, source, value, type_expr, row_owned, keep, transferred = row
            override_types = {entry: fact_types[entry] for entry in evaluation.values if entry in fact_types}
            if type_expr is None:
                # A trailing borrowed operand has nothing sequenced after it, so
                # its unknown type never has to be spelled; every other position
                # would need a C type to stage it.
                trailing = bool(
                    row_index + 1 == len(rows)
                    and (row_index > 0 or plan.receiver is not None)
                    and not row_owned
                    and not keep
                )
                if not trailing:
                    self._ownership.reject_opaque_ordering(source, "call arguments", typed_declaration=True)
                if value is None:
                    with self._session.operand_scope(evaluation.values, override_types, evaluation.ownership):
                        value = self.lower_expr(source, provenance)
                row_values[key] = value
                if isinstance(key, int) and key in explicit_by_index:
                    source_types[key] = explicit_by_index[key][4]
                continue
            if isinstance(key, ProjectionDependencyKey):
                with self._session.operand_scope(evaluation.values, override_types, evaluation.ownership):
                    value = self.lower_expr(source, provenance)
            elif isinstance(key, int) and plan.bindings[key].is_default:
                parameter_index = plan.bindings[key].parameter_index
                if parameter_index is None:
                    raise CodegenError("default call binding has no parameter slot")
                parameter = plan.parameters[parameter_index]
                with provenance.declaration_default_callable_scope(
                    plan.parameters,
                    parameter_index,
                    bound_nodes,
                    source_flow.entries,
                ):
                    self._callable_boundaries.reject_call_argument(
                        parameter,
                        source,
                        provenance,
                    )
                receiver_value = evaluation.values.get(id(plan.receiver)) if plan.receiver is not None else None
                with self._session.operand_scope(evaluation.values, override_types, evaluation.ownership):
                    value = self._calls.materialize_default_call(
                        plan.source,
                        list(plan.parameters),
                        parameter_index,
                        bound_nodes,
                        evaluation.values,
                        provenance,
                        receiver_node=plan.receiver,
                        receiver_value=receiver_value,
                    )
                source_types[key] = type_expr
            elif isinstance(key, int):
                binding = plan.bindings[key]
                parameter = self._bound_parameter(plan, binding.parameter_index)
                if value is None:
                    with self._session.operand_scope(evaluation.values, override_types, evaluation.ownership):
                        if parameter is None:
                            value = self.lower_expr(source, provenance)
                        else:
                            value = self.prepare_value(
                                source,
                                self._calls.argument_target_type(parameter, source),
                                provenance,
                            ).value
                source_types[key] = explicit_by_index[key][4]
            elif value is None:
                with self._session.operand_scope(evaluation.values, override_types, evaluation.ownership):
                    value = self.lower_expr(source, provenance)
            assert value is not None
            self._call_boundary.append(
                evaluation,
                CallOperand(
                    node=source,
                    type_expr=type_expr,
                    c_type=self._types.render(type_expr),
                    keep=keep,
                    pin=pins[row_index],
                    owned=row_owned,
                    transferred=transferred,
                    lowered=value,
                ),
            )
            row_values[key] = evaluation.values[id(source)]

        lowered_callee = row_values.get("callee", callee)
        lowered_receiver = row_values.get("receiver", receiver)
        argument_values = {index: value for index, value in row_values.items() if isinstance(index, int)}
        arguments = self._abi_call_arguments(plan, argument_values, source_types)
        if callable_environment is not None:
            arguments.append(self._callable_environment_argument(callable_environment))
        call = self._calls.materialize(plan, lowered_callee, lowered_receiver, arguments)
        call = self._calls.materialize_requested_hosted_result(plan.source, call)
        return self._call_boundary.materialize(
            evaluation,
            call,
            CallResultPlan(
                c_type=self._types.render(result_type) if result_type is not None else None,
                type_expr=result_type,
                opaque=result_type is None,
                source_site=plan.source,
                promote=promote_result,
                owned=bool(result_owned or promote_result),
            ),
        )

    @staticmethod
    def _callable_environment_argument(environment: CallableEnvironment) -> IRExpr:
        return IRCast(
            target_type=CType(text="void*"),
            expr=IRAddressOf(expr=IRVar(name=environment.variable_name)),
        )

    @staticmethod
    def _bound_parameter(plan, parameter_index):
        if parameter_index is None or not 0 <= parameter_index < len(plan.parameters):
            return None
        return plan.parameters[parameter_index]

    def _call_binding_has_effect(self, plan, binding) -> bool:
        if binding.is_default or self._ownership.has_observable_effect(binding.source):
            return True
        parameter = self._bound_parameter(plan, binding.parameter_index)
        if parameter is None:
            return False
        return self._calls.requires_string_conversion(
            self._calls.argument_target_type(parameter, binding.source),
            self._session.type_of(binding.source),
        )

    def _projection_storage_by_source(
        self,
        requests,
        provenance: CallableProvenance,
        *,
        call: CallExpr | None = None,
        flow_entries=None,
    ):
        storage = {}
        for request in requests:
            entry = flow_entries.get(id(request.source)) if flow_entries is not None else None
            if entry is None:
                operands = self._ownership.projection_storage_operands(
                    request.source,
                    provenance,
                    call=call,
                    parameter_index=request.parameter_index,
                    has_later_effects=request.has_later_effects,
                )
            else:
                with provenance.at_flow(entry):
                    operands = self._ownership.projection_storage_operands(
                        request.source,
                        provenance,
                        call=call,
                        parameter_index=request.parameter_index,
                        has_later_effects=request.has_later_effects,
                    )
            if operands:
                storage[id(request.source)] = operands
        return storage

    def _expand_projection_rows(self, rows, projection_storage):
        expanded = []
        dependency_index = 0
        for row in rows:
            for dependency in projection_storage.get(id(row[1]), ()):
                dependency_index += 1
                dependency_type = self._types.resolve_active_type(self._session.type_of(dependency.expression))
                expanded.append(
                    (
                        ProjectionDependencyKey(dependency_index),
                        dependency.expression,
                        None,
                        dependency_type,
                        dependency.owned,
                        dependency.keep,
                        False,
                    )
                )
            expanded.append(row)
        return expanded

    def _abi_call_arguments(self, plan, values, source_types) -> list[IRExpr]:
        ordered: dict[int, IRExpr] = {}
        unbound: list[IRExpr] = []
        for binding_index, binding in enumerate(plan.bindings):
            value = values[binding_index]
            parameter = self._bound_parameter(plan, binding.parameter_index)
            if parameter is not None:
                value = self._types.upcast_class_pointer(
                    parameter.type,
                    source_types[binding_index],
                    value,
                )
            elif plan.variadic:
                value = self._calls.promote_variadic_argument(
                    source_types[binding_index],
                    value,
                )
            if parameter is None:
                unbound.append(value)
            else:
                ordered[binding.parameter_index] = value
        return [ordered[index] for index in range(len(plan.parameters)) if index in ordered] + unbound

    def _call_result_type(self, plan) -> TypeExpr | None:
        source = plan.source
        type_expr = self._session.type_of(source)
        if isinstance(source, NewExpr):
            type_expr = type_expr or source.type
        if type_expr is None and plan.declaration is not None:
            type_expr = getattr(plan.declaration, "return_type", None) or TypeExpr(base="void")
        if type_expr is None and plan.dispatch is CallDispatch.BUILTIN_PRINT:
            type_expr = TypeExpr(base="void")
        if type_expr is None and plan.dispatch is CallDispatch.CALLABLE:
            signature = self._types.function_pointer_signature(self._session.type_of(plan.callee))
            if signature:
                type_expr = signature[0]
        return self._types.resolve_active_type(self._default_arguments.resolve_type(type_expr))

    def _lower_immediate_lambda_call(
        self,
        plan,
        provenance: CallableProvenance,
    ) -> IRExpr:
        node = plan.callee
        if not isinstance(node, LambdaExpr):
            raise TypeError("immediate lambda dispatch requires a LambdaExpr")
        call_effect = provenance.capture_call_effect(plan.source)
        function = self.lower_expr(node, provenance)
        if not isinstance(function, IRFunctionRef):
            raise TypeError("lambda lowering must produce a function reference")
        evaluation = self._call_boundary.start()
        environment = None
        capture_values = []
        if node.captures:
            lambda_id = function.name.rsplit("_", 1)[-1]
            environment_name = f"__btrc_lambda_{lambda_id}_call_env"
            environment = IRVar(name=environment_name)
            environment_declaration = IRVarDecl(
                c_type=CType(text=f"struct __btrc_lambda_{lambda_id}_env"),
                name=environment_name,
            )
            self._session.record_declaration(environment_declaration)
            evaluation.declarations.append(environment_declaration)
            for capture in node.captures:
                capture_type = self._types.resolve_active_type(capture.type)
                if capture_type is None:
                    raise CodegenError(f"cannot resolve lambda capture type for '{capture.name}'")
                self._call_boundary.append(
                    evaluation,
                    CallOperand(
                        node=capture,
                        type_expr=capture_type,
                        c_type=self._types.render(capture_type),
                        pin=self._values.is_managed(capture_type),
                        lowered=IRVar(name=provenance.source_binding_c_name(capture.name)),
                    ),
                )
                capture_values.append((capture, provenance.source_binding_c_name(capture.name)))
            for capture, field_name in capture_values:
                evaluation.prefix.append(
                    IRBinOp(
                        left=IRFieldAccess(obj=environment, field=field_name, arrow=False),
                        op="=",
                        right=evaluation.values[id(capture)],
                    )
                )
        explicit_bindings = [(index, binding) for index, binding in enumerate(plan.bindings) if not binding.is_default]
        if any(binding.is_default for binding in plan.bindings):
            raise CodegenError("immediate lambda defaults require a declaration-owned helper")
        binding_effects = [self._call_binding_has_effect(plan, binding) for binding in plan.bindings]
        projection_requests = [ProjectionStorageRequest(binding.source) for _index, binding in explicit_bindings]
        source_flow = provenance.plan_evaluation(request.source for request in projection_requests)
        projection_storage = self._projection_storage_by_source(
            projection_requests,
            provenance,
            call=plan.source,
            flow_entries=source_flow.entries,
        )
        prepared_arguments = []
        for binding_index, binding in explicit_bindings:
            parameter = self._bound_parameter(plan, binding.parameter_index)
            entry = source_flow.entries.get(id(binding.source), source_flow.incoming)
            with provenance.at_flow(entry):
                if parameter is None:
                    argument_type = self._types.resolve_active_type(self._session.type_of(binding.source))
                    owned = self._ownership.lowered_result_is_owned(binding.source, provenance=provenance)
                else:
                    preparation = self._calls.plan_value(binding.source, parameter.type, provenance)
                    argument_type = preparation.effective_type
                    owned = preparation.owned
            prepared_arguments.append(
                (
                    binding_index,
                    binding.source,
                    None,
                    argument_type,
                    owned,
                    bool(parameter is not None and parameter.keep and self._values.is_managed(argument_type)),
                    bool(parameter is not None and parameter.transferred and owned),
                )
            )
        rows = self._expand_projection_rows(prepared_arguments, projection_storage)
        argument_nodes = [row[1] for row in rows]
        argument_types = [row[3] for row in rows]
        argument_owned = [row[4] for row in rows]
        argument_effects = [
            binding_effects[key] if isinstance(key, int) else self._operand_order.has_effect(argument)
            for key, argument, *_rest in rows
        ]
        argument_pins = self._operand_order.source_order_pin_flags(
            argument_nodes,
            argument_types,
            argument_owned,
            effects=argument_effects,
        )
        argument_values = {}
        source_types = {}
        fact_types = {id(source): type_expr for _key, source, _value, type_expr, *_rest in rows}
        for index, row in enumerate(rows):
            key, argument, value, argument_type, owned, keep, transferred = row
            override_types = {entry: fact_types[entry] for entry in evaluation.values if entry in fact_types}
            if argument_type is None:
                self._ownership.reject_opaque_ordering(argument, "immediate lambda call")
            if isinstance(key, ProjectionDependencyKey):
                with self._session.operand_scope(evaluation.values, override_types, evaluation.ownership):
                    value = self.lower_expr(argument, provenance)
            elif value is None:
                binding = plan.bindings[key]
                parameter = self._bound_parameter(plan, binding.parameter_index)
                with self._session.operand_scope(evaluation.values, override_types, evaluation.ownership):
                    if parameter is None:
                        value = self.lower_expr(argument, provenance)
                    else:
                        prepared = self.prepare_value(argument, parameter.type, provenance)
                        value = prepared.value
                        argument_type = prepared.effective_type
                        owned = prepared.owned
            assert value is not None
            self._call_boundary.append(
                evaluation,
                CallOperand(
                    node=argument,
                    type_expr=argument_type,
                    c_type=self._operand_order.operand_c_type(argument, argument_type),
                    keep=keep,
                    pin=argument_pins[index],
                    owned=owned,
                    transferred=transferred,
                    lowered=value,
                ),
            )
            if isinstance(key, int):
                argument_values[key] = evaluation.values[id(argument)]
                source_types[key] = argument_type
        arguments = self._abi_call_arguments(plan, argument_values, source_types)
        if environment is not None:
            arguments.append(
                IRCast(
                    target_type=CType(text="void*"),
                    expr=IRAddressOf(expr=environment),
                )
            )
        call = IRCall(callee=function.name, args=arguments)
        result_owned = self._ownership.source_call_owns_result(
            plan.source,
            provenance,
            call_effect,
        )
        result_type = self._call_result_type(plan)
        return self._call_boundary.materialize(
            evaluation,
            call,
            CallResultPlan(
                c_type=self._types.render(result_type) if result_type is not None else None,
                type_expr=result_type,
                opaque=result_type is None,
                source_site=plan.source,
                promote=bool(self._values.is_managed(result_type) and not result_owned),
                owned=result_owned,
            ),
        )

    def _declare_deferred_lambda(
        self,
        node: LambdaExpr,
        function_name: str,
        provenance: CallableProvenance,
    ) -> None:
        if any(declaration.name == function_name for declaration in self._session.module.function_decls):
            return
        parameters = [provenance.lower_source_param(parameter) for parameter in node.params]
        if node.captures:
            parameters.append(IRParam(c_type=CType(text="void*"), name="__btrc_env"))
        function_type = self._session.type_of(node)
        return_type = (
            function_type.generic_args[0]
            if function_type is not None and function_type.base == "__fn_ptr" and function_type.generic_args
            else node.return_type
        )
        self._session.module.function_decls.append(
            IRFunctionDecl(
                name=function_name,
                return_type=CType(text=self._types.render(return_type) if return_type is not None else "void"),
                params=parameters,
                is_static=True,
            )
        )

    def lower_static_initializer(
        self,
        node,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Recursively lower a static initializer through typed plans."""
        materialization, _ = self._plan_static_initializer(node, provenance)
        return self._materialize_static_initializer(
            materialization,
            provenance,
            constant_expression=True,
        )

    def prepare_static_initializer(
        self,
        node,
        target_type: TypeExpr,
        provenance: CallableProvenance,
    ) -> PreparedStaticInitializer:
        """Stabilize side-effectful scalar leaves before a C array declaration."""
        materialization, leaf_plans = self._plan_static_initializer(
            node,
            provenance,
            target_type=target_type,
        )
        leaves = tuple(leaf for leaf, _target in leaf_plans)
        prepared = self._prepare_operand_evaluation(
            leaves,
            provenance,
            operand_targets=tuple(target for _leaf, target in leaf_plans),
            force=self._operand_order.operands_require_order(leaves),
            opaque_context="aggregate initializer",
        )
        canonical_target = self._types.canonical_type(target_type)
        constant_expression = bool(canonical_target and canonical_target.is_static)
        if prepared is None:
            return PreparedStaticInitializer(
                before=(),
                value=self._materialize_static_initializer(
                    materialization,
                    provenance,
                    constant_expression=constant_expression,
                ),
                after=(),
            )
        evaluation, fact_types = prepared
        with self._session.operand_scope(evaluation.values, fact_types, evaluation.ownership):
            value = self._materialize_static_initializer(
                materialization,
                provenance,
                constant_expression=constant_expression,
            )
        before = (
            *evaluation.declarations,
            *(IRExprStmt(expr=expression) for expression in evaluation.before_value),
        )
        after = tuple(IRExprStmt(expr=expression) for expression in evaluation.suffix)
        return PreparedStaticInitializer(before=before, value=value, after=after)

    def _plan_static_initializer(
        self,
        node,
        provenance: CallableProvenance,
        *,
        target_type: TypeExpr | None = None,
    ) -> tuple[StaticInitializerMaterialization, tuple[tuple[object, TypeExpr | None], ...]]:
        """Resolve one recursive initializer tree and its ordered scalar leaves."""
        plan = self._collections.plan_static(node, provenance)
        if plan is None:
            return StaticInitializerMaterialization(source=node, plan=None), ((node, target_type),)
        child_targets: tuple[TypeExpr | None, ...]
        if plan.field_types is not None:
            child_targets = tuple(
                plan.field_types[index] if index < len(plan.field_types) else None
                for index in range(len(node.elements))
            )
        else:
            canonical_target = self._types.canonical_type(target_type)
            element_target = (
                TypeSystem.strip_outer_storage(canonical_target, array=True)
                if canonical_target is not None and canonical_target.is_array
                else None
            )
            child_targets = (element_target,) * len(node.elements)
        child_flow = provenance.plan_evaluation(node.elements)
        children = []
        for index, element in enumerate(node.elements):
            entry = child_flow.entries.get(id(element), child_flow.incoming)
            with provenance.at_flow(entry):
                children.append(
                    self._plan_static_initializer(
                        element,
                        provenance,
                        target_type=child_targets[index],
                    )
                )
        return (
            StaticInitializerMaterialization(
                source=node,
                plan=plan,
                elements=tuple(child for child, _leaf_plans in children),
            ),
            tuple(leaf_plan for _child, leaf_plans in children for leaf_plan in leaf_plans),
        )

    def _materialize_static_initializer(
        self,
        materialization: StaticInitializerMaterialization,
        provenance: CallableProvenance,
        *,
        constant_expression: bool,
    ) -> IRExpr:
        """Build declaration-only initializer IR from stabilized scalar leaves."""
        if materialization.plan is None:
            return (
                self._materialize_static_scalar(materialization.source, provenance)
                if constant_expression
                else self.lower_expr(materialization.source, provenance)
            )
        return self._collections.materialize_static(
            materialization.plan,
            [
                self._materialize_static_initializer(
                    element,
                    provenance,
                    constant_expression=constant_expression,
                )
                for element in materialization.elements
            ],
        )

    def _materialize_static_scalar(
        self,
        node,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Preserve analyzer-approved C constant expressions as structured IR."""
        if isinstance(node, BinaryExpr):
            left = self._materialize_static_scalar(node.left, provenance)
            right = self._materialize_static_scalar(node.right, provenance)
            left_type = self._types.canonical_type(self._session.type_of(node.left))
            right_type = self._types.canonical_type(self._session.type_of(node.right))
            numeric = bool(
                TypeSystem.is_numeric_type(left_type, self._analyzed.enum_table)
                and TypeSystem.is_numeric_type(right_type, self._analyzed.enum_table)
            )
            if numeric and node.op in {"==", "!=", "<", ">", "<=", ">="}:
                return self._types.lower_numeric_comparison(
                    node.op,
                    left,
                    right,
                    left_type,
                    right_type,
                )
            if numeric and node.op in {"+", "-", "*", "/", "%"}:
                return self._types.lower_numeric_operation(
                    node.op,
                    left,
                    right,
                    left_type,
                    right_type,
                )
            return IRBinOp(left=left, op=node.op, right=right)
        if isinstance(node, UnaryExpr):
            operand = self._materialize_static_scalar(node.operand, provenance)
            if node.op == "&":
                return IRAddressOf(expr=operand, source_expression=True)
            if node.op == "*":
                return IRDeref(expr=operand)
            return IRUnaryOp(op=node.op, operand=operand, prefix=node.prefix)
        if isinstance(node, CastExpr):
            return IRCast(
                target_type=CType(text=self._cast_target_type(node.target_type)),
                expr=self._materialize_static_scalar(node.expr, provenance),
            )
        if isinstance(node, TernaryExpr):
            return self._types.lower_typed_ternary(
                self._materialize_static_scalar(node.condition, provenance),
                self._materialize_static_scalar(node.true_expr, provenance),
                self._materialize_static_scalar(node.false_expr, provenance),
                self._session.type_of(node.true_expr),
                self._session.type_of(node.false_expr),
            )
        if isinstance(node, SizeofExpr):
            return self._materialize_static_sizeof(node, provenance)
        if isinstance(node, IndexExpr):
            return self._storage.materialize_index_target(
                self._materialize_static_scalar(node.obj, provenance),
                self._materialize_static_scalar(node.index, provenance),
                self._session.type_of(node.obj),
            )
        if isinstance(node, FieldAccessExpr):
            return self._materialize_static_field_access(node, provenance)
        return self.lower_expr(node, provenance)

    def _materialize_static_sizeof(
        self,
        node: SizeofExpr,
        provenance: CallableProvenance,
    ) -> IRSizeof:
        if isinstance(node.operand, SizeofType):
            return IRSizeof(operand=CType(text=self._types.render(node.operand.type)))
        if isinstance(node.operand, SizeofExprOp):
            expression = node.operand.expr
            expression_type = self._session.type_of(expression)
            if (
                expression_type is not None
                and (not expression_type.is_array)
                and (not isinstance(expression, StringLiteral))
            ):
                return IRSizeof(operand=CType(text=self._types.render(expression_type)))
            return IRSizeof(operand=self._materialize_static_scalar(expression, provenance))
        return IRSizeof(operand=CType(text="void"))

    def _materialize_static_field_access(
        self,
        node: FieldAccessExpr,
        provenance: CallableProvenance,
    ) -> IRExpr:
        if isinstance(node.obj, Identifier) and not self._session.local_is_declared(node.obj.name):
            if node.obj.name in self._analyzed.enum_table and node.field in self._analyzed.enum_table[node.obj.name]:
                return IRVar(name=f"{node.obj.name}_{node.field}")
            if node.obj.name in self._analyzed.rich_enum_table:
                return IRVar(name=f"{node.obj.name}_{node.field}_TAG")
            class_info = self._analyzed.class_table.get(node.obj.name)
            if class_info is not None and node.field in class_info.static_fields:
                return IRVar(name=f"{node.obj.name}_{node.field}")
        obj = self._materialize_static_scalar(node.obj, provenance)
        field = IRFieldAccess(
            obj=obj,
            field=provenance.source_field_c_name(node.obj, node.field),
            arrow=self.receiver_uses_arrow(self._session.type_of(node.obj), explicit=node.arrow),
        )
        return field.record_array_projection(self._session.type_of(node))

    def _cast_target_type(self, target) -> str:
        target_type = self._types.render(target)
        reference_types = {*self._analyzed.class_table, *self._analyzed.interface_table}
        if target.base in reference_types and not target_type.endswith("*"):
            target_type += "*"
        return target_type

    def prepare_value(
        self,
        node,
        target_type,
        provenance: CallableProvenance,
    ):
        """Lower and materialize one target-directed value plan."""
        with self.hosted_result_request(node, target_type, provenance) as plan:
            contextual_type = (
                plan.target_type
                if plan.source_type is None
                and plan.target_type is not None
                and isinstance(node, (BraceInitializer, ListLiteral, MapLiteral, TupleLiteral))
                else None
            )
            with self._session.operand_scope(
                {},
                {id(node): contextual_type} if contextual_type is not None else None,
            ):
                lowered = self.lower_expr(
                    node,
                    provenance,
                )
        return self.materialize_prepared_value(
            plan,
            lowered,
        )

    def prepare_lowered_value(
        self,
        node,
        target_type,
        lowered: IRExpr,
        provenance: CallableProvenance,
    ):
        """Materialize a value whose ordinary expression traversal is complete."""
        plan = self._calls.plan_value(node, target_type, provenance)
        return self.materialize_prepared_value(
            plan,
            lowered,
        )

    @contextmanager
    def hosted_result_request(self, node, target_type, provenance: CallableProvenance):
        """Record one target-directed hosted conversion while ``node`` lowers.

        A hosted ``char*`` result must be adopted or copied inside the call's own
        operand boundary, before any owned operand it aliases is released. The
        request tells that boundary which conversion the consumer needs.
        """

        plan = self._calls.plan_value(node, target_type, provenance)
        requests = self._session.hosted_result_conversion_requests
        key = id(node)
        missing = object()
        previous = requests.get(key, missing)
        if plan.hosted_mode is not None:
            requests[key] = (plan.hosted_mode, plan.target_type)
        try:
            yield plan
        finally:
            if plan.hosted_mode is not None:
                if previous is missing:
                    requests.pop(key, None)
                else:
                    requests[key] = previous

    def materialize_prepared_value(
        self,
        plan: ValuePreparationPlan,
        lowered: IRExpr,
    ):
        """Apply a resolved conversion plan to explicit source IR."""
        if not plan.string_conversion:
            return self._calls.materialize_value(plan, lowered)
        operand = CallOperand(
            node=plan.source,
            type_expr=plan.source_type,
            c_type=self._types.render(plan.source_type),
            owned=plan.lowered_owned,
            lowered=lowered,
        )
        evaluation = self._call_boundary.evaluate([operand])
        converted_call = self._calls.materialize_string_conversion(plan, evaluation.values[id(plan.source)])
        string_type = TypeExpr(base="string")
        converted = self._call_boundary.materialize(
            evaluation,
            converted_call,
            CallResultPlan(
                c_type=self._types.render(string_type),
                type_expr=string_type,
                owned=True,
            ),
        )
        return self._calls.materialize_value(plan, lowered, converted=converted)

    def constructor_cleanup_guard(self, self_declaration: IRVarDecl):
        """Return registration/discard statements around a throwing init call."""
        if not self.program_uses_exceptions():
            return ([], [])
        self._session.require_helper("__btrc_cleanup_mark")
        self._session.require_helper("__btrc_discard_cleanups_to")
        self._session.require_helper("__btrc_arc_abandon")
        mark = self._session.fresh_temp("__btrc_constructor_cleanup")
        before = [
            IRVarDecl(
                c_type=CType(text="int"),
                name=mark,
                init=IRCall(callee="__btrc_cleanup_mark", args=[], helper_ref="__btrc_cleanup_mark"),
            ),
            IRExprStmt(
                expr=self._cleanup_slots.register(
                    self_declaration, IRFunctionRef(name="__btrc_arc_abandon"), direct=True
                )
            ),
        ]
        after = [
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_discard_cleanups_to",
                    args=[IRVar(name=mark)],
                    helper_ref="__btrc_discard_cleanups_to",
                )
            )
        ]
        return (before, after)

    def program_uses_exceptions(self) -> bool:
        """Return the module-wide ownership contract for throwing constructors."""
        return self._program_has_exceptions

    @staticmethod
    def unsupported_node(phase: str, node) -> CodegenError:
        return CodegenError(f"unsupported {phase} node: {type(node).__name__}")

    def lower_expr(self, node, provenance: CallableProvenance) -> IRExpr:
        """Lower an AST expression node to an IRExpr."""
        if node is None:
            return IRLiteral(text="0")
        if self is not None:
            override = self._session.owning_overrides.get(id(node))
            if override is not None:
                return override
        if isinstance(node, IntLiteral):
            return IRLiteral(text=self._types.format_c_integer_literal(node.raw, node.value))
        if isinstance(node, FloatLiteral):
            text = node.raw or str(node.value)
            if self._session.gpu_cpu_index and (not text.endswith(("f", "F"))):
                text += "f"
            return IRLiteral(text=text)
        if isinstance(node, StringLiteral):
            return IRLiteral(text=node.value)
        if isinstance(node, CharLiteral):
            return IRLiteral(text=node.value)
        if isinstance(node, BoolLiteral):
            return IRLiteral(text="true" if node.value else "false")
        if isinstance(node, NullLiteral):
            return IRLiteral(text="NULL")
        if isinstance(node, Identifier):
            return self._lower_identifier(
                node,
                provenance,
            )
        if isinstance(node, SelfExpr):
            return IRVar(name="self")
        if isinstance(node, SuperExpr):
            parent_type = self._session.type_of(node)
            if parent_type is None:
                raise CodegenError("unresolved super expression")
            return IRCast(target_type=CType(text=self._types.render(parent_type)), expr=IRVar(name="self"))
        if isinstance(node, BinaryExpr):
            return self._lower_binary(
                node,
                provenance,
            )
        if isinstance(node, UnaryExpr):
            return self._lower_unary(
                node,
                provenance,
            )
        if isinstance(node, CallExpr):
            if isinstance(node.callee, Identifier) and self._gpu.is_gpu_cpu_builtin(node.callee.name):
                return self._gpu.lower_gpu_cpu_builtin(
                    node.callee.name,
                    node.args,
                    [
                        self.lower_expr(
                            argument,
                            provenance,
                        )
                        for argument in node.args
                    ],
                )
            if self._gpu.is_direct_gpu_call(node, provenance):
                return self._gpu.materialize_direct_gpu_call(
                    node,
                    self.lower_gpu_arguments(node, provenance),
                    provenance,
                )
            if isinstance(node.callee, FieldAccessExpr):
                receiver_type = self._session.type_of(node.callee.obj)
                synchronization = self._concurrency.plan_sync_method(
                    receiver_type,
                    node.callee.field,
                )
                if synchronization is not None:
                    if synchronization.receiver_type.base == "Mutex" and synchronization.method_name in {"get", "set"}:
                        sequenced = self._sequence_operands(
                            [node.callee.obj, *node.args],
                            provenance,
                            materialization=SyncMethodMaterialization(
                                plan=synchronization,
                                receiver=node.callee.obj,
                                arguments=tuple(node.args),
                                argument_targets=tuple(
                                    synchronization.receiver_type.generic_args[0] if index == 0 else None
                                    for index, _argument in enumerate(node.args)
                                )
                                if synchronization.method_name == "set"
                                else tuple(None for _argument in node.args),
                            ),
                            result_type=self._session.type_of(node),
                            result_owned=self._ownership.owns_result(
                                node,
                                provenance=provenance,
                            ),
                            force=True,
                        )
                        if sequenced is not None:
                            return sequenced
                    receiver = self.lower_expr(
                        node.callee.obj,
                        provenance,
                    )
                    arguments = [
                        self.lower_expr(
                            argument,
                            provenance,
                        )
                        for argument in node.args
                    ]
                    return self._concurrency.materialize_sync_method(
                        synchronization,
                        receiver,
                        arguments,
                    )
            if isinstance(node.callee, FieldAccessExpr) and node.callee.optional:
                return self.lower_optional_method_call(
                    node,
                    provenance,
                )
            return self.lower_call_plan(
                self._calls.plan(node),
                provenance,
            )
        if isinstance(node, FieldAccessExpr):
            return self._lower_field_access(
                node,
                provenance,
            )
        if isinstance(node, IndexExpr):
            return self._lower_index(
                node,
                provenance,
            )
        if isinstance(node, AssignExpr):
            result = self._lower_assignment(node, provenance)
            provenance.rebind_assignment(node)
            return result
        if isinstance(node, CastExpr):
            self._callable_boundaries.reject_nonportable_callable_cast(node, provenance)
            return IRCast(
                target_type=CType(text=self._cast_target_type(node.target_type)),
                expr=self.lower_expr(
                    node.expr,
                    provenance,
                ),
            )
        if isinstance(node, SizeofExpr):
            return self._lower_sizeof(
                node,
                provenance,
            )
        if isinstance(node, TernaryExpr):
            branch_ownership = self._ownership.conditional_branch_ownership(node, provenance)
            owns_result = self._ownership.owns_result(node, provenance=provenance)
            condition = self.lower_expr(
                node.condition,
                provenance,
            )
            with provenance.isolated_flow() as true_isolation:
                true_expr = self.lower_expr(
                    node.true_expr,
                    provenance,
                )
            with provenance.isolated_flow() as false_isolation:
                false_expr = self.lower_expr(
                    node.false_expr,
                    provenance,
                )
            assert true_isolation.outgoing is not None
            assert false_isolation.outgoing is not None
            provenance.join_flows(true_isolation.outgoing, false_isolation.outgoing)
            if owns_result:
                true_expr = self._ownership.normalize_branch(
                    node.true_expr,
                    true_expr,
                    provenance,
                    source_owned=branch_ownership[0],
                )
                false_expr = self._ownership.normalize_branch(
                    node.false_expr,
                    false_expr,
                    provenance,
                    source_owned=branch_ownership[1],
                )
            return self._types.lower_typed_ternary(
                condition,
                true_expr,
                false_expr,
                self._session.type_of(node.true_expr),
                self._session.type_of(node.false_expr),
            )
        if isinstance(node, NewExpr):
            instance_type = self._types.resolve_active_type(self._default_arguments.resolve_type(node.type))
            if instance_type is None:
                raise CodegenError("unresolved constructor type")
            return self.lower_call_plan(
                self._calls.plan_new(node, instance_type),
                provenance,
            )
        if isinstance(node, ListLiteral):
            return self._lower_collection_literal(node, provenance)
        if isinstance(node, MapLiteral):
            return self._lower_collection_literal(node, provenance)
        if isinstance(node, FStringLiteral):
            return self.lower_fstring(
                node,
                provenance,
            )
        if isinstance(node, LambdaExpr):
            lambda_id = self._session.fresh_lambda_id()
            function_name = f"__btrc_lambda_{lambda_id}"
            capture_abis = tuple((capture, provenance.return_abi_for_name(capture.name)) for capture in node.captures)
            self._session.pending_lambdas.append(LambdaPlan(node, function_name, capture_abis))
            self._declare_deferred_lambda(node, function_name, provenance)
            return IRFunctionRef(name=function_name)
        if isinstance(node, TupleLiteral):
            return self._lower_aggregate(
                self._collections.plan_tuple(node, provenance),
                node.elements,
                provenance,
            )
        if isinstance(node, SpawnExpr):
            lowered_function = (
                None
                if isinstance(node.fn, LambdaExpr)
                else self.lower_expr(
                    node.fn,
                    provenance,
                )
            )
            return self._concurrency.lower_spawn(
                node,
                lowered_function=lowered_function,
                provenance=provenance,
            )
        if isinstance(node, BraceInitializer):
            return self._lower_aggregate(
                self._collections.plan_brace(node, provenance),
                node.elements,
                provenance,
            )
        raise ExpressionLowerer.unsupported_node("expression", node)

    def _lower_identifier(self, node: Identifier, provenance: CallableProvenance) -> IRExpr:
        """Lower an identifier, handling enum values."""
        name = node.name
        predefined = self._default_arguments.predefined_identifier(node)
        if predefined is not None:
            return IRLiteral(text=predefined)
        if self._session.local_is_declared(name):
            return self._source_identifier_var(node, self._ownership.source_binding_c_name(name, provenance))
        if name in self._source_visible_helpers and (not self._session.local_is_declared(name)):
            self._session.require_helper(name)
            return IRFunctionRef(name=name)
        enum_members = self._session.enum_lowering_members
        if name in enum_members:
            owner = self._session.enum_lowering_owner
            prefix = f"{owner}_" if owner else ""
            return IRVar(name=f"{prefix}{name}")
        for enum_name, values in self._analyzed.enum_table.items():
            if name in values:
                prefix = f"{enum_name}_" if enum_name else ""
                return IRVar(name=f"{prefix}{name}")
        if name in self._analyzed.function_table and (not self._session.local_is_declared(name)):
            return IRFunctionRef(name=provenance.source_function_c_name(name))
        return self._source_identifier_var(node, name)

    def _source_identifier_var(self, node, c_name):
        return IRVar(name=c_name).record_array_value(self._session.type_of(node))

    def _lower_sizeof(self, node: SizeofExpr, provenance: CallableProvenance) -> IRExpr:
        if isinstance(node.operand, SizeofType):
            return IRSizeof(operand=CType(text=self._types.render(node.operand.type)))
        elif isinstance(node.operand, SizeofExprOp):
            expression = node.operand.expr
            expression_type = self._session.type_of(expression)
            if (
                expression_type is not None
                and (not expression_type.is_array)
                and (not isinstance(expression, StringLiteral))
            ):
                return IRSizeof(operand=CType(text=self._types.render(expression_type)))
            self._session.unevaluated_depth += 1
            try:
                return IRSizeof(
                    operand=self.lower_expr(
                        expression,
                        provenance,
                    )
                )
            finally:
                self._session.unevaluated_depth -= 1
        return IRSizeof(operand=CType(text="void"))

    def _lower_field_access(self, node: FieldAccessExpr, provenance: CallableProvenance) -> IRExpr:
        """Lower field access, handling optional chaining and special types."""
        result_type = self._session.type_of(node)
        from src.compiler.python.analyzer.storage import StorageModel

        custom_getter = StorageModel.custom_property_getter(
            self._analyzed.class_table, self._session.type_of(node.obj), node.field
        )
        dependencies = self._ownership.borrowed_projection_owner_operands(node.obj, provenance)
        sequenced = self._sequence_operands(
            [*dependencies, node.obj],
            provenance,
            materialization=FieldAccessMaterialization(node),
            result_type=result_type,
            pin_nodes=[node.obj] if custom_getter else [],
            promote_result=bool(
                self._values.is_managed(result_type) and (not self._ownership.projection_is_owned_call(node))
            ),
        )
        if sequenced is not None:
            return sequenced
        return self._lower_field_access_plain(
            node,
            provenance,
        )

    def _lower_assignment(self, node: AssignExpr, provenance: CallableProvenance) -> IRExpr:
        """Stabilize target owners while preserving the final assignable projection."""
        self._callable_boundaries.reject_assignment(node, provenance)
        if isinstance(node.value, CallExpr) and self._gpu.output_gpu_call_name(node.value, provenance) is not None:
            target_type = self._types.canonical_type(self._session.type_of(node.target))
            target_nodes = (
                self._ownership.assignment_target_operands(node.target, provenance)
                if (
                    target_type is not None
                    and target_type.is_array
                    and isinstance(node.target, (FieldAccessExpr, IndexExpr))
                    and not self._storage.is_static_field_target(node.target)
                )
                else []
            )
            if target_nodes:
                result_type = self._session.type_of(node)
                result_is_owned = self._ownership.owns_result(node, provenance=provenance)
                sequenced = self._sequence_operands(
                    target_nodes,
                    provenance,
                    materialization=AssignmentMaterialization(node),
                    result_type=result_type,
                    result_owned=result_is_owned,
                    promote_result=False,
                    keep_nodes=self._ownership.kept_target_operands(node.target, target_nodes, provenance),
                    force=bool(self._operand_order.operands_require_order([*target_nodes, node.value])),
                    opaque_context="GPU output assignment target",
                )
                if sequenced is not None:
                    return sequenced
            return self._lower_assignment_plain(node, provenance)
        storage_plan = self._storage.plan_store(
            node.target,
            node.value,
            operator=node.op,
            provenance=provenance,
        )
        target_nodes = (
            []
            if storage_plan.kind is StorageKind.STATIC_FIELD
            else self._ownership.assignment_target_operands(node.target, provenance)
        )
        if target_nodes:
            result_type = self._session.type_of(node)
            rhs_supplies_result = self._ownership.assignment_rhs_supplies_owned_result(node, provenance)
            result_is_owned = self._ownership.owns_result(node, provenance=provenance)
            sequenced = self._sequence_operands(
                target_nodes,
                provenance,
                materialization=AssignmentMaterialization(node),
                result_type=result_type,
                keep_nodes=self._ownership.kept_target_operands(node.target, target_nodes, provenance),
                promote_result=bool(
                    self._values.is_managed(result_type) and result_is_owned and not rhs_supplies_result
                ),
                force=bool(
                    isinstance(node.target, (FieldAccessExpr, IndexExpr))
                    and self._operand_order.operands_require_order([*target_nodes, node.value])
                ),
                opaque_context="assignment target",
            )
            if sequenced is not None:
                return sequenced
        return self._lower_assignment_plain(node, provenance)

    def _lower_assignment_plain(self, node: AssignExpr, provenance: CallableProvenance) -> IRExpr:
        """Materialize an assignment after target-owner stabilization."""
        if isinstance(node.value, CallExpr) and self._gpu.output_gpu_call_name(node.value, provenance) is not None:
            target_type = self._session.type_of(node.target)
            target = self.lower_expr(node.target, provenance)
            target_capacity = (
                self.lower_expr(target_type.array_size, provenance)
                if target_type is not None and target_type.array_size is not None
                else None
            )
            return self._gpu.lower_gpu_output_assignment(
                node.value,
                node.target,
                target,
                target_capacity,
                self.lower_gpu_arguments(node.value, provenance),
                provenance,
                result_owned=self._ownership.owns_result(node, provenance=provenance),
            )
        plan = self._storage.plan_store(
            node.target,
            node.value,
            operator=node.op,
            provenance=provenance,
        )
        operation_type = plan.managed_value_type or plan.target_type
        method = self.overloaded_binary_method(operation_type, node.op[:-1]) if node.op != "=" else None
        operator_result_type = self.resolved_operator_result_type(operation_type, method)
        if method is not None and not self._types.concrete_value_compatible(
            operation_type,
            operator_result_type,
        ):
            raise CodegenError(
                f"operator '{node.op[:-1]}' returns '{self._types.render(operator_result_type)}', "
                f"which cannot be stored in compound target '{self._types.render(operation_type)}'"
            )
        rhs_target_type = self.resolved_operator_param_type(operation_type, method) or plan.target_type
        target = self._materialize_storage_target(plan, provenance)
        prepared = self.prepare_value(node.value, rhs_target_type, provenance)
        if node.op == "=":
            value = self._types.upcast_class_pointer(
                rhs_target_type,
                prepared.effective_type,
                prepared.value,
            )
            return self._storage.materialize_store(
                target,
                value,
                value_owned=prepared.owned,
            )
        if method is not None and not self._types.concrete_value_compatible(
            rhs_target_type,
            prepared.effective_type,
        ):
            raise CodegenError(
                f"operator '{node.op[:-1]}' parameter '{self._types.render(rhs_target_type)}' "
                f"cannot accept concrete '{self._types.render(prepared.effective_type)}'"
            )
        right_keep = bool(
            method is not None
            and method.params
            and method.params[0].keep
            and self._values.is_managed(prepared.effective_type)
        )
        update = self._storage.prepare_update(
            target,
            prepared.value,
            prepared.effective_type,
            right_owned=prepared.owned,
            right_keep=right_keep,
        )
        computed, computed_owned = self._compute_storage_update(
            node.op[:-1],
            operation_type,
            prepared.effective_type,
            update.old,
            update.right,
        )
        if operator_result_type is not None:
            computed = self._types.upcast_class_pointer(
                self._types.canonical_type(operation_type),
                operator_result_type,
                computed,
            )
        return self._storage.materialize_update(
            update,
            computed,
            computed_owned=computed_owned,
        )

    def _materialize_storage_target(self, plan, provenance: CallableProvenance):
        """Lower target operands while leaving stabilization and storage shape to StorageLowerer."""
        target = plan.target
        if plan.kind is StorageKind.STATIC_FIELD:
            return self._storage.materialize_target(plan)
        if isinstance(target, IndexExpr):
            receiver, index = self._lower_index_operands(target, provenance)
            return self._storage.materialize_target(
                plan,
                lowered_receiver=receiver,
                lowered_index=index,
            )
        if self._storage.target_requires_receiver(plan):
            assert isinstance(target, FieldAccessExpr)
            return self._storage.materialize_target(
                plan,
                lowered_receiver=self.lower_expr(target.obj, provenance),
            )
        return self._storage.materialize_target(
            plan,
            lowered_target=self.lower_expr(target, provenance),
        )

    def lower_managed_slot_target(
        self,
        source,
        provenance: CallableProvenance,
    ) -> ManagedSlotTarget:
        """Stabilize one physical slot for an ownership-consuming statement."""
        plan = self._storage.plan_store(source, provenance=provenance)
        materialized = self._materialize_storage_target(plan, provenance)
        if plan.kind in {StorageKind.PROPERTY, StorageKind.INDEXED} or materialized.target is None:
            raise CodegenError("ownership operation requires a physical storage target")
        return ManagedSlotTarget(
            source=source,
            type_expr=plan.managed_value_type or plan.target_type,
            slot=materialized.target,
            edge_owner=materialized.receiver if plan.kind is StorageKind.INSTANCE_FIELD else None,
            declarations=tuple(materialized.declarations),
            setup=tuple(materialized.setup),
        )

    def _compute_storage_update(
        self,
        operator: str,
        left_type,
        right_type,
        left: IRExpr,
        right: IRExpr,
    ) -> tuple[IRExpr, bool]:
        """Compute a typed replacement from already-materialized update values."""
        overloaded = self.lower_overloaded_values(left_type, right_type, operator, left, right)
        if overloaded is not None:
            return overloaded, self._values.is_managed(left_type)
        lowered = self._types.lower_typed_binary(
            operator,
            left,
            right,
            left_type,
            right_type,
            allow_unresolved_c_operands=True,
        )
        if lowered is None:
            lowered = IRBinOp(left=left, op=operator, right=right)
        return lowered, bool(operator == "+" and self._values.is_string(left_type))

    def _lower_field_access_plain(self, node: FieldAccessExpr, provenance: CallableProvenance) -> IRExpr:
        """Lower one field access after any owning receiver is stabilized."""
        obj = self.lower_expr(
            node.obj,
            provenance,
        )
        obj_type = self._session.type_of(node.obj)
        field_name = provenance.source_field_c_name(node.obj, node.field)
        if isinstance(node.obj, SelfExpr) and self._session.current_property_backing == node.field:
            return IRFieldAccess(obj=obj, field=f"_prop_{node.field}", arrow=True)
        if (
            obj_type
            and obj_type.base in {"Array", "List", "Map", "Set", "Vector"}
            and self._types.is_direct_generic_instance_reference(obj_type)
            and (node.field in ("len", "length", "size"))
        ):
            if node.optional:
                return self._lower_optional_access(
                    obj,
                    obj_type,
                    self._session.type_of(node),
                    OptionalAccessPlan(field="len"),
                )
            return IRFieldAccess(obj=obj, field="len", arrow=True)
        if (
            isinstance(node.obj, Identifier)
            and node.obj.name in self._analyzed.enum_table
            and (not self._session.local_is_declared(node.obj.name))
            and (node.field in self._analyzed.enum_table[node.obj.name])
        ):
            return IRVar(name=f"{node.obj.name}_{node.field}")
        if (
            isinstance(node.obj, Identifier)
            and node.obj.name in self._analyzed.rich_enum_table
            and (not self._session.local_is_declared(node.obj.name))
        ):
            return IRVar(name=f"{node.obj.name}_{node.field}_TAG")
        if (
            isinstance(node.obj, Identifier)
            and node.obj.name in self._analyzed.class_table
            and (not self._session.local_is_declared(node.obj.name))
        ):
            class_info = self._analyzed.class_table[node.obj.name]
            method = class_info.methods.get(node.field)
            symbol = f"{node.obj.name}_{node.field}"
            if method is not None and method.access == "class":
                return IRFunctionRef(name=symbol)
            return IRVar(name=symbol)
        if obj_type and obj_type.base in self._analyzed.class_table:
            cls_info = self._analyzed.class_table[obj_type.base]
            if obj_type.generic_args and cls_info.generic_params:
                callee_prefix = self._type_identity.specialization_symbol(obj_type.base, obj_type.generic_args)
            else:
                callee_prefix = obj_type.base
            if node.field in cls_info.properties:
                if node.optional:
                    return self._lower_optional_access(
                        obj,
                        obj_type,
                        self._session.type_of(node),
                        OptionalAccessPlan(callee=f"{callee_prefix}_get_{node.field}"),
                    )
                return IRCall(callee=f"{callee_prefix}_get_{node.field}", args=[obj])
        if node.optional:
            return self._lower_optional_access(
                obj,
                obj_type,
                self._session.type_of(node),
                OptionalAccessPlan(field=field_name),
            )
        field = IRFieldAccess(obj=obj, field=field_name, arrow=self.receiver_uses_arrow(obj_type, explicit=node.arrow))
        return field.record_array_projection(self._session.type_of(node))

    def receiver_uses_arrow(self, receiver_type, *, explicit: bool = False) -> bool:
        """Choose C member syntax from the receiver's concrete storage shape."""
        if explicit:
            return True
        resolved = self._types.canonical_type(receiver_type)
        return bool(resolved and (resolved.pointer_depth > 0 or resolved.base in self._analyzed.class_table))

    def _lower_optional_access(
        self,
        receiver,
        receiver_type,
        result_type,
        plan: OptionalAccessPlan,
    ) -> IRExpr:
        """Evaluate one nullable receiver once, then conditionally read its value."""
        name = self._session.fresh_temp("__btrc_optional")
        temporary = IRVar(name=name)
        c_type = self._types.render(receiver_type) if receiver_type is not None else "void*"
        if plan.callee is not None:
            access = IRCall(callee=plan.callee, args=[temporary])
        elif plan.field is not None:
            access = IRFieldAccess(obj=temporary, field=plan.field, arrow=True)
        else:
            raise ValueError("optional access plan requires a field or callee")
        return IRStmtExpr(
            stmts=[IRVarDecl(c_type=CType(text=c_type), name=name)],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(left=temporary, op="=", right=receiver),
                    IRTernary(
                        condition=IRBinOp(left=temporary, op="!=", right=IRLiteral(text="NULL")),
                        true_expr=access,
                        false_expr=self._optional_zero(
                            result_type,
                        ),
                    ),
                ]
            ),
        )

    def _optional_zero(self, result_type):
        return self._types.optional_zero_value(result_type)

    def _lower_index(self, node: IndexExpr, provenance: CallableProvenance) -> IRExpr:
        """Lower index expression: list[i] → List_get(list, i), map[k] → Map_get(map, k)."""
        result_type = self._session.type_of(node)
        projection_call = self._ownership.projection_is_owned_call(node)
        receiver_type = self._session.type_of(node.obj)
        protocol_getter = self._index_protocols.class_info(receiver_type, method="get")
        dependencies = self._ownership.borrowed_projection_owner_operands(node.obj, provenance)
        sequenced = self._sequence_operands(
            [*dependencies, node.obj, node.index],
            provenance,
            materialization=IndexMaterialization(node),
            result_type=result_type,
            pin_nodes=[node.obj] if protocol_getter is not None else [],
            promote_result=bool(self._values.is_managed(result_type) and (not projection_call)),
            result_owned=bool(self._values.is_managed(result_type) and projection_call),
            force=self._operand_order.operands_require_order([*dependencies, node.obj, node.index]),
        )
        if sequenced is not None:
            return sequenced
        return self._lower_index_plain(
            node,
            provenance,
        )

    def _lower_aggregate(
        self,
        plan,
        elements,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Lower aggregate leaves, then materialize their resolved shape."""

        materialization = AggregateMaterialization(plan, tuple(elements))
        sequenced = self._sequence_operands(
            list(elements),
            provenance,
            materialization=materialization,
            result_type=self._session.type_of(plan.source),
            force=self._operand_order.operands_require_order(elements),
        )
        return sequenced if sequenced is not None else self._materialize_sequenced(materialization, provenance)

    def _lower_collection_literal(
        self,
        node: ListLiteral | MapLiteral,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Sequence dynamic collection leaves before retaining them in storage."""
        plan = self._collections.plan_literal(node)
        materialization = CollectionLiteralMaterialization(
            plan,
            self._collections.literal_leaf_targets(plan),
        )
        leaves = list(plan.leaves)
        result_type = self._session.type_of(node)
        sequenced = self._sequence_operands(
            leaves,
            provenance,
            materialization=materialization,
            result_type=result_type,
            result_owned=self._ownership.owns_result(node, provenance=provenance),
            force=self._operand_order.operands_require_order(leaves),
        )
        return sequenced if sequenced is not None else self._materialize_sequenced(materialization, provenance)

    def _lower_index_plain(self, node: IndexExpr, provenance: CallableProvenance) -> IRExpr:
        """Lower one index projection after its receiver is stabilized."""
        obj, index = self._lower_index_operands(node, provenance)
        obj_type = self._session.type_of(node.obj)
        protocol = self._index_protocols.class_info(obj_type, method="get")
        if protocol is not None:
            prefix = (
                self._type_identity.specialization_symbol(obj_type.base, obj_type.generic_args)
                if obj_type.generic_args and protocol.generic_params
                else obj_type.base
            )
            return IRCall(callee=f"{prefix}_get", args=[obj, index])
        return self._storage.materialize_index_target(obj, index, obj_type)

    def _lower_index_operands(
        self,
        node: IndexExpr,
        provenance: CallableProvenance,
    ) -> tuple[IRExpr, IRExpr]:
        """Lower one index receiver and key after any outer stabilization."""
        obj = self.lower_expr(
            node.obj,
            provenance,
        )
        index = self.lower_expr(
            node.index,
            provenance,
        )
        gpu_length = self._gpu.cpu_array_length(node.obj.name) if isinstance(node.obj, Identifier) else None
        if gpu_length is not None:
            self._session.require_helper("__btrc_gpu_index_check")
            index = IRCall(
                callee="__btrc_gpu_index_check",
                args=[index, IRVar(name=gpu_length)],
                helper_ref="__btrc_gpu_index_check",
            )
        return obj, index

    def lower_fstring(self, node: FStringLiteral, provenance: CallableProvenance):
        """Lower a normal f-string through the shared typed implementation."""
        return self.lower_typed_fstring(
            node,
            provenance,
        )

    def lower_typed_fstring(
        self,
        node,
        provenance: CallableProvenance,
    ):
        """Format interpolations once and consume any caller-owned arguments."""
        format_parts = []
        prepared_items = []
        argument_specs = []
        for part in node.parts:
            if isinstance(part, FStringText):
                format_parts.append(part.text.replace("%", "%%"))
                continue
            if not isinstance(part, FStringExpr):
                continue
            expression = part.expression
            source_type = self._types.canonical_type(self._session.type_of(expression))
            target_type = TypeExpr(base="string") if self._types.has_to_string(source_type) else source_type
            prepared = self.prepare_value(
                expression,
                target_type,
                provenance,
            )
            spec = "%s" if prepared.converted else self._types.format_spec(source_type)
            if source_type is None:
                spec = ExpressionLowerer._untracked_format(expression, spec)
            c_type = (
                self._types.render(prepared.effective_type)
                if prepared.effective_type is not None
                else "char*"
                if spec == "%s"
                else "int"
            )
            prepared_items.append((expression, prepared, c_type))
            argument_specs.append((expression, prepared.effective_type, spec, len(format_parts)))
            format_parts.append(spec)
        format_text = "".join(format_parts)
        if not prepared_items:
            return IRLiteral(text=f'"{format_text}"')
        prepared_pairs = [(expression, prepared) for expression, prepared, _c_type in prepared_items]
        pins = self._calls.prepared_value_pin_flags(prepared_pairs)
        operands = [
            CallOperand(
                node=expression,
                type_expr=prepared.effective_type,
                c_type=c_type,
                pin=pins[index],
                owned=prepared.owned,
                lowered=prepared.value,
            )
            for index, (expression, prepared, c_type) in enumerate(prepared_items)
        ]
        self._session.require_helper("__btrc_string_alloc")
        string_type = TypeExpr(base="string")

        def build(overrides):
            arguments = []
            formats = list(format_parts)
            for expression, value_type, spec, part_index in argument_specs:
                adapted = self._calls.adapt_printf_arg(
                    overrides[id(expression)],
                    value_type,
                    spec,
                )
                formats[part_index] = adapted.format_spec
                arguments.append(adapted.value)
            fmt = IRLiteral(text=f'''"{"".join(formats)}"''')
            length = self._session.fresh_temp("__fstr_len")
            buffer = self._session.fresh_temp("__fstr_buf")
            declarations = [
                IRVarDecl(c_type=CType(text="int"), name=length),
                IRVarDecl(c_type=CType(text="char*"), name=buffer),
            ]
            for declaration in declarations:
                self._session.record_declaration(declaration)
            size = IRBinOp(
                left=IRCast(target_type=CType(text="size_t"), expr=IRVar(name=length)),
                op="+",
                right=IRLiteral(text="1"),
            )
            sequence = [
                IRBinOp(
                    left=IRVar(name=length),
                    op="=",
                    right=IRCall(
                        callee="snprintf", args=[IRLiteral(text="NULL"), IRLiteral(text="0"), fmt, *arguments]
                    ),
                ),
                IRBinOp(
                    left=IRVar(name=buffer),
                    op="=",
                    right=IRCall(
                        callee="__btrc_string_alloc", args=[IRVar(name=length)], helper_ref="__btrc_string_alloc"
                    ),
                ),
                IRCall(callee="snprintf", args=[IRVar(name=buffer), size, fmt, *arguments]),
                IRVar(name=buffer),
            ]
            return IRStmtExpr(stmts=declarations, result=IRCommaExpr(expressions=sequence))

        evaluation = self._call_boundary.evaluate(operands)
        call = build(evaluation.values)
        return self._call_boundary.materialize(
            evaluation,
            call,
            CallResultPlan(c_type="char*", type_expr=string_type, owned=True),
        )

    @staticmethod
    def _untracked_format(expression, fallback):
        if isinstance(expression, (FStringLiteral, StringLiteral)):
            return "%s"
        if isinstance(expression, CallExpr) and isinstance(expression.callee, FieldAccessExpr):
            if expression.callee.field in {
                "capitalize",
                "join",
                "repeat",
                "replace",
                "reverse",
                "split",
                "str",
                "substring",
                "toLower",
                "toString",
                "toUpper",
                "trim",
            }:
                return "%s"
        return fallback or "%d"

    def operator_rhs_keep(self, left_type, operator: str, right_type) -> bool:
        """Whether an overloaded operator's RHS needs a call-duration keep."""
        left_type = self._types.canonical_type(left_type)
        if not self._values.is_managed(right_type) or left_type is None:
            return False
        magic = {
            "+": "__add__",
            "-": "__sub__",
            "*": "__mul__",
            "/": "__div__",
            "%": "__mod__",
            "==": "__eq__",
            "!=": "__ne__",
            "<": "__lt__",
            ">": "__gt__",
            "<=": "__le__",
            ">=": "__ge__",
        }.get(operator)
        class_info = self._analyzed.class_table.get(left_type.base)
        method = class_info.methods.get(magic) if class_info is not None and magic else None
        return bool(method is not None and method.params and method.params[0].keep)

    def _lower_binary(self, node: BinaryExpr, provenance: CallableProvenance) -> IRExpr:
        """Lower a binary expression, handling special operators."""
        if node.op == "+":
            flattened = self.lower_long_string_concat(
                node,
                provenance,
            )
            if flattened is not None:
                return flattened
        prepared_overload = self._lower_prepared_overload(
            node,
            provenance,
        )
        if prepared_overload is not None:
            return prepared_overload
        if node.op not in {"??", "&&", "||"}:
            left_type = self._session.type_of(node.left)
            right_type = self._session.type_of(node.right)
            keep_nodes = [node.right] if self.operator_rhs_keep(left_type, node.op, right_type) else []
            pin_nodes = (
                [node.left]
                if self.overloaded_binary_method(left_type, node.op) is not None and self._values.is_managed(left_type)
                else []
            )
            sequenced = self._sequence_operands(
                [node.left, node.right],
                provenance,
                materialization=BinaryMaterialization(node),
                result_type=self._session.type_of(node),
                keep_nodes=keep_nodes,
                pin_nodes=pin_nodes,
                force=self._operand_order.operands_require_order([node.left, node.right]),
                allow_trailing_opaque=True,
                opaque_context=f"operator '{node.op}'",
            )
            if sequenced is not None:
                return sequenced
        return self._lower_binary_plain(
            node,
            provenance,
        )

    @staticmethod
    def _is_optional_value_expression(expression) -> bool:
        if isinstance(expression, FieldAccessExpr):
            return expression.optional
        return (
            isinstance(expression, CallExpr)
            and isinstance(expression.callee, FieldAccessExpr)
            and expression.callee.optional
        )

    def _lower_binary_plain(self, node: BinaryExpr, provenance: CallableProvenance) -> IRExpr:
        """Lower one binary operation after owned operands are stabilized."""
        branch_ownership = self._ownership.conditional_branch_ownership(node, provenance) if node.op == "??" else ()
        owns_result = bool(node.op == "??" and self._ownership.owns_result(node, provenance=provenance))
        if node.op in {"??", "&&", "||"}:
            left = self.lower_expr(
                node.left,
                provenance,
            )
            skipped_flow = provenance.snapshot()
            with provenance.isolated_flow() as right_isolation:
                right = self.lower_expr(
                    node.right,
                    provenance,
                )
            assert right_isolation.outgoing is not None
            provenance.join_flows(skipped_flow, right_isolation.outgoing)
        else:
            left = self.lower_expr(
                node.left,
                provenance,
            )
            right = self.lower_expr(
                node.right,
                provenance,
            )
        if owns_result:
            left = self._ownership.normalize_branch(
                node.left,
                left,
                provenance,
                source_owned=branch_ownership[0],
            )
            right = self._ownership.normalize_branch(
                node.right,
                right,
                provenance,
                source_owned=branch_ownership[1],
            )
        left_type = self._session.type_of(node.left)
        right_type = self._session.type_of(node.right)
        op = node.op
        overloaded = self.lower_overloaded_values(
            left_type,
            right_type,
            op,
            left,
            right,
        )
        if overloaded is not None:
            return overloaded
        lowered = self._types.lower_typed_binary(
            op,
            left,
            right,
            left_type,
            right_type,
            allow_unresolved_c_operands=True,
            left_is_optional_value=self._is_optional_value_expression(node.left),
        )
        if lowered is not None:
            return lowered
        return IRBinOp(left=left, op=op, right=right)

    def lower_overloaded_values(self, left_type, right_type, op: str, left: IRExpr, right: IRExpr) -> IRExpr | None:
        """Lower one class operation from already-resolved operand types."""
        left_type = self._types.canonical_type(left_type)
        right_type = self._types.canonical_type(right_type)
        method = self.overloaded_binary_method(left_type, op)
        if method is None:
            return None
        if method.params:
            parameter_type = self.resolved_operator_param_type(left_type, method)
            right = self._types.upcast_class_pointer(parameter_type, right_type, right)
        class_name = (
            self._type_identity.specialization_symbol(left_type.base, left_type.generic_args)
            if left_type.generic_args
            else left_type.base
        )
        return IRCall(callee=f"{class_name}_{ExpressionLowerer._operator_method_name(op)}", args=[left, right])

    def overloaded_binary_method(self, left_type, op: str):
        """Return the source method implementing an overloaded binary operator."""
        left_type = self._types.canonical_type(left_type)
        magic = ExpressionLowerer._operator_method_name(op)
        if not magic or not left_type:
            return None
        cls_info = self._analyzed.class_table.get(left_type.base)
        if cls_info is None:
            return None
        return cls_info.methods.get(magic)

    def resolved_operator_param_type(self, left_type, method):
        """Resolve an overload RHS type against its concrete receiver."""
        if method is None or not method.params:
            return None
        return self._resolved_operator_signature_type(left_type, method, method.params[0].type)

    def resolved_operator_result_type(self, left_type, method):
        """Resolve an overload result type against its concrete receiver."""
        if method is None:
            return None
        return self._resolved_operator_signature_type(left_type, method, method.return_type)

    def _resolved_operator_signature_type(self, left_type, method, declared_type):
        """Apply receiver substitutions to one declared overload signature type."""
        left_type = self._types.canonical_type(left_type)
        if left_type is None or declared_type is None:
            return None
        resolved = declared_type
        cls = self._analyzed.class_table.get(left_type.base) if left_type else None
        if cls and cls.generic_params and left_type.generic_args:
            resolved = self._types.substitute_concrete_type(
                resolved,
                dict(zip(cls.generic_params, left_type.generic_args)),
            )
        return self._types.canonical_type(resolved)

    def _lower_prepared_overload(self, node, provenance: CallableProvenance):
        """Lower an overload whose RHS needs target-directed conversion."""
        left_type = self._session.type_of(node.left)
        right_type = self._session.type_of(node.right)
        method = self.overloaded_binary_method(left_type, node.op)
        expected = self.resolved_operator_param_type(left_type, method)
        if expected is None:
            return None
        if not self._calls.requires_string_conversion(expected, right_type):
            return None
        left = self.prepare_value(
            node.left,
            left_type,
            provenance,
        )
        right = self.prepare_value(
            node.right,
            expected,
            provenance,
        )
        operands = [
            CallOperand(
                node=node.left,
                type_expr=left.effective_type,
                c_type=self._types.render(left.effective_type),
                pin=bool(
                    self._ownership.borrowed_value_can_be_pinned(node.left)
                    and self._values.is_managed(left.effective_type)
                    and (not left.owned)
                ),
                owned=left.owned,
                lowered=left.value,
            ),
            CallOperand(
                node=node.right,
                type_expr=right.effective_type,
                c_type=self._types.render(right.effective_type),
                keep=bool(method.params[0].keep),
                owned=right.owned,
                lowered=right.value,
            ),
        ]
        evaluation = self._call_boundary.evaluate(operands)
        result_type = self._session.type_of(node)
        call = self.lower_overloaded_values(
            left.effective_type,
            right.effective_type,
            node.op,
            evaluation.values[id(node.left)],
            evaluation.values[id(node.right)],
        )
        return self._call_boundary.materialize(
            evaluation,
            call,
            CallResultPlan(
                c_type=self._types.render(result_type),
                type_expr=result_type,
                owned=self._ownership.owns_result(node, provenance=provenance),
            ),
        )

    @staticmethod
    def _operator_method_name(op: str) -> str | None:
        return {
            "+": "__add__",
            "-": "__sub__",
            "*": "__mul__",
            "/": "__div__",
            "%": "__mod__",
            "==": "__eq__",
            "!=": "__ne__",
            "<": "__lt__",
            ">": "__gt__",
            "<=": "__le__",
            ">=": "__ge__",
        }.get(op)

    def _lower_unary(self, node: UnaryExpr, provenance: CallableProvenance) -> IRExpr:
        if node.op == "&":
            self._callable_boundaries.reject_address_escape(node.operand, provenance)
        if node.op in {"++", "--"} and isinstance(node.operand, (FieldAccessExpr, IndexExpr)):
            target_nodes = [node.operand.obj]
            if isinstance(node.operand, IndexExpr):
                target_nodes.append(node.operand.index)
            result_type = self._session.type_of(node)
            sequenced = self._sequence_operands(
                target_nodes,
                provenance,
                materialization=UnaryMaterialization(node),
                result_type=result_type,
                promote_result=bool(self._values.is_managed(result_type)),
            )
            if sequenced is not None:
                return sequenced
        if node.op not in {"++", "--", "&", "*"}:
            sequenced = self._sequence_operands(
                [node.operand],
                provenance,
                materialization=UnaryMaterialization(node),
                result_type=self._session.type_of(node),
            )
            if sequenced is not None:
                return sequenced
        return self._lower_unary_plain(
            node,
            provenance,
        )

    def _lower_unary_plain(self, node: UnaryExpr, provenance: CallableProvenance) -> IRExpr:
        op = node.op
        if op in {"++", "--"}:
            plan = self._storage.plan_store(node.operand, operator=op, provenance=provenance)
            target = self._materialize_storage_target(plan, provenance)
            operation_type = plan.managed_value_type or plan.target_type
            one_type = (
                operation_type
                if operation_type is not None and TypeSystem.is_known_integer_typedef_name(operation_type.base)
                else TypeExpr(base="int")
            )
            operator = "+" if op == "++" else "-"
            update = self._storage.prepare_update(
                target,
                IRLiteral(text="1"),
                one_type,
                right_owned=False,
            )
            computed, computed_owned = self._compute_storage_update(
                operator,
                operation_type,
                one_type,
                update.old,
                update.right,
            )
            return self._storage.materialize_update(
                update,
                computed,
                computed_owned=computed_owned,
                yield_old=not node.prefix,
            )
        operand = self.lower_expr(
            node.operand,
            provenance,
        )
        if op == "&":
            return IRAddressOf(expr=operand, source_expression=True)
        if op == "*":
            return IRDeref(expr=operand)
        if op == "-" and node.prefix:
            operand_type = self._types.canonical_type(self._session.type_of(node.operand))
            if operand_type and operand_type.base in self._analyzed.class_table:
                cls_info = self._analyzed.class_table[operand_type.base]
                if "__neg__" in cls_info.methods:
                    if operand_type.generic_args:
                        cls_c_name = self._type_identity.specialization_symbol(
                            operand_type.base, operand_type.generic_args
                        )
                    else:
                        cls_c_name = operand_type.base
                    return IRCall(callee=f"{cls_c_name}___neg__", args=[operand])
        return IRUnaryOp(op=op, operand=operand, prefix=node.prefix)

    def lower_optional_method_call(
        self,
        node: CallExpr,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Sequence one optional receiver before lazily lowering its guarded call."""
        if not isinstance(node.callee, FieldAccessExpr) or not node.callee.optional:
            raise ValueError("optional-call lowering requires an optional field callee")
        result_type = self._session.type_of(node)
        sequenced = self._sequence_operands(
            [node.callee.obj],
            provenance,
            materialization=OptionalMethodCallMaterialization(node),
            result_type=result_type,
            result_owned=self._values.is_managed(result_type),
            force=True,
        )
        if sequenced is not None:
            return sequenced
        return self._lower_optional_method_call_plain(node, provenance)

    def _lower_optional_method_call_plain(
        self,
        node: CallExpr,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Materialize a guarded call whose receiver lifetime is already bounded."""
        assert isinstance(node.callee, FieldAccessExpr) and node.callee.optional
        receiver_node = node.callee.obj
        receiver_type = self._session.type_of(receiver_node)
        declaration = IRVarDecl(
            c_type=CType(text=self._types.render(receiver_type) if receiver_type is not None else "void*"),
            name=self._session.fresh_temp("__btrc_optional_receiver"),
        )
        self._session.record_declaration(declaration)
        receiver = IRVar(name=declaration.name)
        plain_callee = replace(node.callee, optional=False)
        plain_call = replace(node, callee=plain_callee)
        result_type = self._session.type_of(node)
        plain_types = {
            id(plain_callee): self._session.type_of(node.callee),
            id(plain_call): result_type,
        }
        receiver_value = self.lower_expr(
            receiver_node,
            provenance,
        )
        skipped_flow = provenance.snapshot()
        with (
            provenance.isolated_flow() as executed,
            self._session.operand_scope(
                {id(receiver_node): receiver},
                plain_types,
                {id(receiver_node): False},
            ),
        ):
            guarded = self.lower_call_plan(
                self._calls.plan(plain_call),
                provenance,
            )
        assert executed.outgoing is not None
        provenance.join_flows(skipped_flow, executed.outgoing)
        return IRStmtExpr(
            stmts=[declaration],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(
                        left=receiver,
                        op="=",
                        right=receiver_value,
                    ),
                    IRTernary(
                        condition=IRBinOp(
                            left=receiver,
                            op="!=",
                            right=IRLiteral(text="NULL"),
                        ),
                        true_expr=guarded,
                        false_expr=self._types.optional_zero_value(result_type),
                    ),
                ]
            ),
        )

    def lower_long_string_concat(self, node, provenance: CallableProvenance):
        """Lower a long left-associated chain as one flat comma sequence."""
        leaves = self._left_chain_leaves(node)
        if len(leaves) < _FLAT_CHAIN_MIN_TERMS:
            return None
        result_type = self._session.type_of(node)
        c_type = self._types.render(result_type)
        declarations: list[IRVarDecl] = []
        sequence = []
        values = []
        leaf_types = []
        owned = []
        source_flow = provenance.plan_evaluation(leaves)
        for leaf in leaves:
            leaf_type = self._session.type_of(leaf) or result_type
            declaration = self._temporary("__btrc_concat_part", c_type)
            declarations.append(declaration)
            value = IRVar(name=declaration.name)
            values.append(value)
            leaf_types.append(leaf_type)
            entry = source_flow.entries.get(id(leaf), source_flow.incoming)
            with provenance.at_flow(entry):
                owned.append(self._ownership.lowered_result_is_owned(leaf, provenance=provenance))
        initial_pins = self._operand_order.source_order_pin_flags(leaves[:2], leaf_types[:2], owned[:2])
        accumulator_decl = self._temporary("__btrc_concat_acc", c_type)
        next_decl = self._temporary("__btrc_concat_next", c_type)
        result_decl = self._temporary("__btrc_concat_result", c_type)
        declarations.extend([accumulator_decl, next_decl, result_decl])
        accumulator = IRVar(name=accumulator_decl.name)
        next_value = IRVar(name=next_decl.name)
        result = IRVar(name=result_decl.name)
        self._evaluate_leaf(
            leaves[0],
            leaf_types[0],
            declarations[0],
            values[0],
            owned[0],
            initial_pins[0],
            declarations,
            sequence,
            provenance,
        )
        self._evaluate_leaf(
            leaves[1],
            leaf_types[1],
            declarations[1],
            values[1],
            owned[1],
            False,
            declarations,
            sequence,
            provenance,
        )
        sequence.append(IRBinOp(left=accumulator, op="=", right=self._concat_call(values[0], values[1])))
        self._register_cleanup(accumulator_decl, result_type, declarations, sequence, "__btrc_concat_acc_cleanup")
        self._release_leaf(values[0], leaf_types[0], bool(owned[0] or initial_pins[0]), sequence)
        self._release_leaf(values[1], leaf_types[1], owned[1], sequence)
        for index in range(2, len(values)):
            leaf = values[index]
            leaf_type = leaf_types[index]
            self._evaluate_leaf(
                leaves[index],
                leaf_type,
                declarations[index],
                leaf,
                owned[index],
                False,
                declarations,
                sequence,
                provenance,
            )
            sequence.append(IRBinOp(left=next_value, op="=", right=self._concat_call(accumulator, leaf)))
            sequence.extend(
                [
                    self._lifetime.release_value(accumulator, result_type),
                    IRBinOp(left=accumulator, op="=", right=IRLiteral(text="NULL")),
                ]
            )
            self._release_leaf(leaf, leaf_type, owned[index], sequence)
            sequence.extend(
                [
                    IRBinOp(left=accumulator, op="=", right=next_value),
                    IRBinOp(left=next_value, op="=", right=IRLiteral(text="NULL")),
                ]
            )
        sequence.extend(
            [
                IRBinOp(left=result, op="=", right=accumulator),
                IRBinOp(left=accumulator, op="=", right=IRLiteral(text="NULL")),
                result,
            ]
        )
        return IRStmtExpr(stmts=declarations, result=IRCommaExpr(expressions=sequence))

    def _left_chain_leaves(self, node):
        rights = []
        cursor = node
        while self._is_scalar_concat(cursor):
            rights.append(cursor.right)
            cursor = cursor.left
        rights.reverse()
        return [cursor, *rights]

    def _is_scalar_concat(self, node) -> bool:
        if not isinstance(node, BinaryExpr) or node.op != "+":
            return False
        types = self._analyzed.node_types
        return all(self._values.is_string(types.get(id(value))) for value in (node, node.left, node.right))

    def _temporary(self, prefix: str, c_type: str) -> IRVarDecl:
        declaration = IRVarDecl(
            c_type=CType(text=c_type), name=self._session.fresh_temp(prefix), init=IRLiteral(text="NULL")
        )
        self._session.function_declarations.append(declaration)
        return declaration

    def _register_cleanup(self, declaration, type_expr, declarations, sequence, prefix):
        cleanup_declarations, cleanup_expressions = self._lifetime.cleanup_registration(
            declaration, type_expr, prefix, active=self._cleanup_scope.exception_cleanup_active()
        )
        declarations.extend(cleanup_declarations)
        sequence.extend(cleanup_expressions)

    def _evaluate_leaf(
        self,
        node,
        type_expr,
        declaration,
        value,
        owned,
        pinned,
        declarations,
        sequence,
        provenance: CallableProvenance,
    ) -> None:
        sequence.append(
            IRBinOp(
                left=value,
                op="=",
                right=self.lower_expr(
                    node,
                    provenance,
                ),
            )
        )
        if pinned:
            sequence.append(self._lifetime.retain_value(value, type_expr))
        if owned or pinned:
            self._register_cleanup(declaration, type_expr, declarations, sequence, "__btrc_concat_part_cleanup")

    def _release_leaf(self, value, type_expr, owned: bool, sequence) -> None:
        if not owned:
            return
        sequence.extend(
            [self._lifetime.release_value(value, type_expr), IRBinOp(left=value, op="=", right=IRLiteral(text="NULL"))]
        )

    def _concat_call(self, left, right):
        self._session.require_helper("__btrc_strcat")
        self._session.require_helper("__btrc_str_track")
        return IRCall(
            callee="__btrc_str_track",
            args=[IRCall(callee="__btrc_strcat", args=[left, right], helper_ref="__btrc_strcat")],
            helper_ref="__btrc_str_track",
        )
