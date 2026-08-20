"""Cohesive storage IR lowering owner."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.storage import StorageModel
from src.compiler.python.analyzer.types import IndexedProtocolResolver, TypeIdentity, TypeShapeError
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRCall,
    IRCommaExpr,
    IRDeref,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionRef,
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
    FieldAccessExpr,
    Identifier,
    IndexExpr,
    LambdaExpr,
    SelfExpr,
    TypeExpr,
    VarDeclStmt,
)

from .types import CodegenError, CTypeLowerer

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
class ArrayBound:
    """One declared array extent, evaluated exactly once.

    ``physical`` is the extent C storage is declared with; a runtime bound is
    clamped so an empty logical array still declares a valid one-element VLA.
    ``logical`` is the unclamped extent GPU dispatch and iteration must use, and
    is ``None`` when the bound is a C constant expression that needs no temp.
    """

    setup: tuple[IRStmt, ...]
    physical: IRExpr
    logical: IRExpr | None


@dataclass(frozen=True, slots=True)
class StoragePlan:
    target: object
    value: object | None
    operator: str
    target_type: TypeExpr | None
    value_type: TypeExpr | None
    managed_value_type: TypeExpr | None
    kind: StorageKind
    receiver_type: TypeExpr | None = None
    index_type: TypeExpr | None = None
    storage_field: str | None = None
    getter: str | None = None
    setter: str | None = None


class StorageKind(Enum):
    """Semantic storage shapes with distinct load/store contracts."""

    DIRECT = auto()
    OWNED_SLOT = auto()
    STATIC_FIELD = auto()
    INSTANCE_FIELD = auto()
    PROPERTY = auto()
    INDEXED = auto()


@dataclass(slots=True)
class MaterializedStorageTarget:
    """One stabilized storage target reused by its load and store."""

    plan: StoragePlan
    target: IRExpr | None
    receiver: IRExpr | None
    index: IRExpr | None
    declarations: list[IRVarDecl]
    setup: list[IRExpr]


@dataclass(slots=True)
class MaterializedStorageUpdate:
    """A stabilized read/RHS pair awaiting its typed computation."""

    target: MaterializedStorageTarget
    right_type: object
    managed: bool
    old: IRVar
    right: IRVar
    replacement: IRVar
    replacement_decl: IRVarDecl
    sequence: list[IRExpr]
    right_owned: bool
    right_keep: bool


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
        self._type_identity = TypeIdentity()
        self._index_protocols = IndexedProtocolResolver(self._type_identity, analyzed.class_table)

    def plan_store(
        self,
        target,
        value=None,
        *,
        operator="=",
        provenance: CallableProvenance,
    ) -> StoragePlan:
        """Classify one source target without evaluating any operand."""
        target_type = self._session.type_of(target)
        value_type = self._session.type_of(value) if value is not None else None
        receiver_type = None
        index_type = None
        storage_field = None
        getter = None
        setter = None
        kind = StorageKind.DIRECT

        if isinstance(target, FieldAccessExpr) and not target.optional:
            static_symbol = self._static_field_symbol(target)
            if static_symbol is not None:
                kind = StorageKind.STATIC_FIELD
                storage_field = static_symbol
            else:
                receiver_type = self._types.resolve_active_type(
                    self._types.canonical_type(self._session.type_of(target.obj))
                )
                class_info = self._analyzed.class_table.get(receiver_type.base) if receiver_type is not None else None
                property_decl = class_info.properties.get(target.field) if class_info is not None else None
                backing_property = bool(
                    property_decl is not None
                    and isinstance(target.obj, SelfExpr)
                    and self._session.current_property_backing == target.field
                    and StorageModel.property_needs_backing(property_decl)
                )
                if property_decl is not None and not backing_property:
                    if not property_decl.has_setter:
                        raise CodegenError(f"Property '{target.field}' has no setter")
                    if operator != "=" and not property_decl.has_getter:
                        raise CodegenError(f"Property '{target.field}' has no getter")
                    prefix = self._class_prefix(receiver_type, class_info)
                    kind = StorageKind.PROPERTY
                    getter = f"{prefix}_get_{target.field}" if operator != "=" else None
                    setter = f"{prefix}_set_{target.field}"
                else:
                    field_decl = class_info.fields.get(target.field) if class_info is not None else None
                    managed_instance_field = bool(
                        self._values.is_managed(target_type)
                        and class_info is not None
                        and (backing_property or (field_decl is not None and field_decl.access != "class"))
                    )
                    if managed_instance_field:
                        kind = StorageKind.INSTANCE_FIELD
                        storage_field = f"_prop_{target.field}" if backing_property else target.field

        elif isinstance(target, IndexExpr):
            receiver_type = self._types.resolve_active_type(
                self._types.canonical_type(self._session.type_of(target.obj))
            )
            index_type = self._types.resolve_active_type(self._session.type_of(target.index))
            protocol = self._index_protocols.resolve(receiver_type)
            if protocol is not None:
                if protocol.setter is None:
                    raise CodegenError(f"Type '{receiver_type.base}' has no indexed setter")
                if operator != "=" and protocol.getter is None:
                    raise CodegenError(f"Type '{receiver_type.base}' has no indexed getter")
                prefix = self._class_prefix(receiver_type, protocol.class_info)
                kind = StorageKind.INDEXED
                getter = f"{prefix}_get" if operator != "=" else None
                setter = f"{prefix}_set"
                # The setter's declared key governs the index, so a class key
                # converts to the collection's key type instead of being stored
                # with its own source type.
                index_type = (
                    self.resolved_indexed_type(protocol.setter.params[0].type, receiver_type, protocol.class_info)
                    or index_type
                )

        managed_value_type = self._owned_identifier_slot(target, target_type, provenance)
        if managed_value_type is not None:
            kind = StorageKind.OWNED_SLOT
        elif kind is StorageKind.STATIC_FIELD:
            managed_value_type = target_type if self._values.is_managed(target_type) else None
        elif kind is StorageKind.INSTANCE_FIELD:
            managed_value_type = target_type
        return StoragePlan(
            target=target,
            value=value,
            operator=operator,
            target_type=target_type,
            value_type=value_type,
            managed_value_type=managed_value_type,
            kind=kind,
            receiver_type=receiver_type,
            index_type=index_type,
            storage_field=storage_field,
            getter=getter,
            setter=setter,
        )

    def resolved_indexed_type(self, declared, receiver_type, class_info) -> TypeExpr | None:
        """Resolve one indexed method's declared type against its receiver."""

        if declared is None or receiver_type is None:
            return None
        parameters = getattr(class_info, "generic_params", None) or ()
        arguments = receiver_type.generic_args or ()
        if not parameters or len(parameters) != len(arguments):
            return self._types.canonical_type(declared)
        substitutions = dict(zip(parameters, arguments, strict=True))
        try:
            resolved = self._type_identity.substitute(
                declared,
                substitutions,
                reference_resolver=self._types.canonical_type,
            )
        except TypeShapeError as error:
            raise CodegenError(str(error)) from error
        return self._types.canonical_type(resolved)

    def target_requires_receiver(self, plan: StoragePlan) -> bool:
        return bool(
            plan.kind in {StorageKind.INSTANCE_FIELD, StorageKind.PROPERTY, StorageKind.INDEXED}
            or isinstance(plan.target, IndexExpr)
        )

    def is_static_field_target(self, target) -> bool:
        """Whether a source target denotes one class-owned static field."""
        return self._static_field_symbol(target) is not None

    def materialize_target(
        self,
        plan: StoragePlan,
        *,
        lowered_target: IRExpr | None = None,
        lowered_receiver: IRExpr | None = None,
        lowered_index: IRExpr | None = None,
    ) -> MaterializedStorageTarget:
        """Evaluate a target's receiver/key once and retain its assignable shape."""
        declarations: list[IRVarDecl] = []
        setup: list[IRExpr] = []
        receiver = None
        index = None
        target = lowered_target

        if plan.kind is StorageKind.STATIC_FIELD:
            if plan.storage_field is None:
                raise ValueError("static field storage requires its lowered symbol")
            target = IRVar(name=plan.storage_field)

        if self.target_requires_receiver(plan):
            if lowered_receiver is None or plan.receiver_type is None:
                raise ValueError("receiver-backed storage requires a typed lowered receiver")
            direct_array_binding = bool(
                isinstance(lowered_receiver, IRVar)
                and plan.receiver_type.is_array
                and lowered_receiver.array_storage_known
                and lowered_receiver.array_storage_root == lowered_receiver.name
            )
            if direct_array_binding:
                receiver = lowered_receiver.record_array_stabilization(
                    lowered_receiver,
                    plan.receiver_type,
                )
            else:
                receiver_decl = self._temporary(plan.receiver_type, "__btrc_storage_receiver")
                declarations.append(receiver_decl)
                receiver = IRVar(name=receiver_decl.name).record_array_stabilization(
                    lowered_receiver,
                    plan.receiver_type,
                )
                setup.append(IRBinOp(left=receiver, op="=", right=lowered_receiver))

        if isinstance(plan.target, IndexExpr):
            if lowered_index is None or plan.index_type is None:
                raise ValueError("indexed storage requires a typed lowered index")
            index_decl = self._temporary(plan.index_type, "__btrc_storage_index")
            declarations.append(index_decl)
            index = IRVar(name=index_decl.name)
            setup.append(IRBinOp(left=index, op="=", right=lowered_index))
            if plan.kind is StorageKind.DIRECT:
                assert receiver is not None
                target = self.materialize_index_target(receiver, index, plan.receiver_type)
        elif plan.kind is StorageKind.INSTANCE_FIELD:
            assert receiver is not None and plan.storage_field is not None
            target = IRFieldAccess(obj=receiver, field=plan.storage_field, arrow=True)

        if (
            plan.kind
            in {
                StorageKind.DIRECT,
                StorageKind.OWNED_SLOT,
                StorageKind.STATIC_FIELD,
                StorageKind.INSTANCE_FIELD,
            }
            and target is None
        ):
            raise ValueError("physical storage requires an assignable IR target")
        return MaterializedStorageTarget(plan, target, receiver, index, declarations, setup)

    def materialize_store(
        self,
        target: MaterializedStorageTarget,
        lowered_value: IRExpr,
        *,
        value_owned: bool = False,
    ) -> IRExpr:
        """Perform one simple store and yield the language assignment value."""
        plan = target.plan
        self._reject_owned_shallow_store(plan, value_owned=value_owned)
        if plan.kind in {StorageKind.OWNED_SLOT, StorageKind.STATIC_FIELD} and plan.managed_value_type is not None:
            assert target.target is not None
            stored = self._lifetime.replace_managed_slot(
                target.target,
                plan.managed_value_type,
                lowered_value,
                value_owned=value_owned,
            )
        elif plan.kind is StorageKind.INSTANCE_FIELD:
            assert target.target is not None and target.receiver is not None
            value_type = plan.managed_value_type
            if value_type is None:
                raise CodegenError("managed instance field has no semantic value type")
            if self._values.is_arc(value_type):
                stored = self._materialize_arc_field_store(
                    target,
                    lowered_value,
                    value_type,
                    value_owned=value_owned,
                )
            else:
                stored = self._lifetime.replace_managed_slot(
                    target.target,
                    value_type,
                    lowered_value,
                    value_owned=value_owned,
                )
        elif plan.kind in {StorageKind.PROPERTY, StorageKind.INDEXED}:
            stored = self._materialize_virtual_store(target, lowered_value, value_owned=value_owned)
        else:
            assert target.target is not None
            stored = IRBinOp(left=target.target, op="=", right=lowered_value)
        return self._wrap_target(target, [stored])

    def _materialize_arc_field_store(
        self,
        target: MaterializedStorageTarget,
        lowered_value: IRExpr,
        value_type: TypeExpr,
        *,
        value_owned: bool,
    ) -> IRExpr:
        """Publish one protected caller reference into a persistent ARC edge."""
        assert target.target is not None
        value_decl = self._temporary(value_type, "__btrc_store_value", managed=True)
        target.declarations.append(value_decl)
        value = IRVar(name=value_decl.name)
        sequence = [IRBinOp(left=value, op="=", right=lowered_value)]
        if not value_owned:
            sequence.append(self._lifetime.retain_value(value, value_type))
        self._lifetime.protect_temporary(
            value_decl,
            value_type,
            target.declarations,
            sequence,
            "__btrc_store_value_cleanup",
        )
        sequence.extend(self._publish_protected_arc_field(target, value, value_type))
        sequence.append(target.target)
        return IRCommaExpr(expressions=sequence)

    def _reject_owned_shallow_store(self, plan: StoragePlan, *, value_owned: bool) -> None:
        """Keep caller-owned values out of physical storage that cannot retain them."""
        if (
            not value_owned
            or plan.kind is not StorageKind.DIRECT
            or not self._values.is_managed(plan.target_type)
            or not self._is_shallow_projection(plan)
        ):
            return
        raise CodegenError(
            "caller-owned temporary cannot be stored in a shallow aggregate; "
            "bind the owner to a local and store only its borrowed reference"
        )

    def _is_shallow_projection(self, plan: StoragePlan) -> bool:
        if isinstance(plan.target, IndexExpr):
            return True
        if not isinstance(plan.target, FieldAccessExpr):
            return False
        receiver = plan.receiver_type
        if receiver is None:
            return False
        struct_name = receiver.base.removeprefix("struct ")
        return bool(receiver.base == "Tuple" or struct_name in self._analyzed.struct_table)

    def prepare_update(
        self,
        target: MaterializedStorageTarget,
        lowered_right: IRExpr,
        right_type,
        *,
        right_owned: bool,
        right_keep: bool = False,
    ) -> MaterializedStorageUpdate:
        """Read a stabilized target and evaluate its RHS exactly once."""
        plan = target.plan
        value_type = plan.managed_value_type or plan.target_type
        if value_type is None:
            raise CodegenError("cannot update storage with an unresolved target type")
        right_type = right_type or plan.value_type or value_type
        managed = self._values.is_managed(value_type)
        old_decl = self._temporary(value_type, "__btrc_update_old", managed=managed)
        right_decl = self._temporary(
            right_type,
            "__btrc_update_rhs",
            managed=self._values.is_managed(right_type),
        )
        replacement_decl = self._temporary(value_type, "__btrc_update_new", managed=managed)
        target.declarations.extend([old_decl, right_decl, replacement_decl])
        old = IRVar(name=old_decl.name)
        right = IRVar(name=right_decl.name)
        replacement = IRVar(name=replacement_decl.name)
        sequence = [IRBinOp(left=old, op="=", right=self.materialize_load(target))]

        if managed:
            sequence.append(self._lifetime.retain_value(old, value_type))
            self._lifetime.protect_temporary(
                old_decl,
                value_type,
                target.declarations,
                sequence,
                "__btrc_update_old_cleanup",
            )
        sequence.append(IRBinOp(left=right, op="=", right=lowered_right))
        if right_owned:
            self._lifetime.protect_temporary(
                right_decl,
                right_type,
                target.declarations,
                sequence,
                "__btrc_update_rhs_cleanup",
            )
        if right_keep and not right_owned:
            sequence.append(self._lifetime.retain_value(right, right_type))
        return MaterializedStorageUpdate(
            target=target,
            right_type=right_type,
            managed=managed,
            old=old,
            right=right,
            replacement=replacement,
            replacement_decl=replacement_decl,
            sequence=sequence,
            right_owned=right_owned,
            right_keep=right_keep,
        )

    def materialize_update(
        self,
        update: MaterializedStorageUpdate,
        computed: IRExpr,
        *,
        computed_owned: bool,
        yield_old: bool = False,
    ) -> IRExpr:
        """Store one typed computation and yield prefix/postfix semantics."""
        target = update.target
        value_type = target.plan.managed_value_type or target.plan.target_type
        if value_type is None:
            raise CodegenError("cannot materialize an update with an unresolved target type")
        sequence = update.sequence
        sequence.append(IRBinOp(left=update.replacement, op="=", right=computed))

        if update.managed:
            if not computed_owned:
                sequence.append(self._lifetime.retain_value(update.replacement, value_type))
            self._lifetime.protect_temporary(
                update.replacement_decl,
                value_type,
                target.declarations,
                sequence,
                "__btrc_update_new_cleanup",
            )
            sequence.extend(self._commit_managed_update(target, update.replacement))
        else:
            sequence.extend(self._store_operations(target, update.replacement))

        if update.right_owned or update.right_keep:
            sequence.extend(
                self._lifetime.release_and_clear(
                    update.right,
                    update.right_type,
                    target.declarations,
                    self._types.render(update.right_type),
                )
            )
        if update.managed:
            sequence.extend(
                self._lifetime.release_and_clear(
                    update.old,
                    value_type,
                    target.declarations,
                    self._types.render(value_type),
                )
            )
        sequence.append(
            update.old
            if yield_old
            else target.target
            if update.managed and target.target is not None
            else update.replacement
        )
        return self._wrap_target(target, sequence)

    def materialize_load(self, target: MaterializedStorageTarget) -> IRExpr:
        plan = target.plan
        if plan.kind is StorageKind.PROPERTY:
            assert plan.getter is not None and target.receiver is not None
            return IRCall(callee=plan.getter, args=[target.receiver])
        if plan.kind is StorageKind.INDEXED:
            assert plan.getter is not None and target.receiver is not None and target.index is not None
            return IRCall(callee=plan.getter, args=[target.receiver, target.index])
        if target.target is None:
            raise ValueError("physical storage load requires an assignable target")
        return target.target

    def _commit_managed_update(
        self,
        target: MaterializedStorageTarget,
        replacement: IRVar,
    ) -> list[IRExpr]:
        plan = target.plan
        value_type = plan.managed_value_type or plan.target_type
        if value_type is None:
            raise CodegenError("cannot commit an update with an unresolved target type")
        if plan.kind is StorageKind.INSTANCE_FIELD and self._values.is_arc(value_type):
            assert target.target is not None and target.receiver is not None
            return self._publish_protected_arc_field(target, replacement, value_type)
        if plan.kind in {StorageKind.OWNED_SLOT, StorageKind.STATIC_FIELD, StorageKind.INSTANCE_FIELD}:
            assert target.target is not None
            current_decl = self._temporary(value_type, "__btrc_update_current", managed=True)
            target.declarations.append(current_decl)
            current = IRVar(name=current_decl.name)
            sequence = [
                IRBinOp(left=current, op="=", right=target.target),
                IRBinOp(left=target.target, op="=", right=replacement),
                IRBinOp(left=replacement, op="=", right=IRLiteral(text="NULL")),
            ]
            sequence.extend(
                self._lifetime.release_and_clear(
                    current,
                    value_type,
                    target.declarations,
                    self._types.render(value_type),
                )
            )
            return sequence
        raise CodegenError("managed compound updates require owned physical storage")

    def _publish_protected_arc_field(
        self,
        target: MaterializedStorageTarget,
        replacement: IRVar,
        value_type: TypeExpr,
    ) -> list[IRExpr]:
        """Copy a caller-owned reference into an edge, then relinquish the caller."""
        assert target.target is not None and target.receiver is not None
        sequence = [
            self._lifetime.replace_edge_value(
                target.target,
                replacement,
                value_type,
                target.receiver,
                adopt=False,
            )
        ]
        sequence.extend(
            self._lifetime.release_and_clear(
                replacement,
                value_type,
                target.declarations,
                self._types.render(value_type),
            )
        )
        return sequence

    def _store_operations(
        self,
        target: MaterializedStorageTarget,
        value: IRExpr,
    ) -> list[IRExpr]:
        plan = target.plan
        if plan.kind is StorageKind.PROPERTY:
            assert plan.setter is not None and target.receiver is not None
            return [IRCall(callee=plan.setter, args=[target.receiver, value])]
        if plan.kind is StorageKind.INDEXED:
            assert plan.setter is not None and target.receiver is not None and target.index is not None
            return [IRCall(callee=plan.setter, args=[target.receiver, target.index, value])]
        assert target.target is not None
        return [IRBinOp(left=target.target, op="=", right=value)]

    def _materialize_virtual_store(
        self,
        target: MaterializedStorageTarget,
        lowered_value: IRExpr,
        *,
        value_owned: bool,
    ) -> IRExpr:
        plan = target.plan
        managed = self._values.is_managed(plan.target_type)
        value_decl = self._temporary(plan.target_type, "__btrc_store_value", managed=managed)
        target.declarations.append(value_decl)
        value = IRVar(name=value_decl.name)
        sequence = [IRBinOp(left=value, op="=", right=lowered_value)]
        if managed and not value_owned:
            # The setter may release whatever the value was borrowed from, so
            # the store owns its own reference and hands it back +1.
            sequence.append(self._lifetime.retain_value(value, plan.target_type))
        if managed:
            self._lifetime.protect_temporary(
                value_decl,
                plan.target_type,
                target.declarations,
                sequence,
                "__btrc_store_value_cleanup",
            )
        sequence.extend(self._store_operations(target, value))
        if managed:
            handoff_decl = self._temporary(plan.target_type, "__btrc_store_result", managed=True)
            target.declarations.append(handoff_decl)
            handoff = IRVar(name=handoff_decl.name)
            sequence.extend(
                [
                    IRBinOp(left=handoff, op="=", right=value),
                    IRBinOp(left=value, op="=", right=IRLiteral(text="NULL")),
                    handoff,
                ]
            )
        else:
            sequence.append(value)
        return IRCommaExpr(expressions=sequence)

    def _wrap_target(
        self,
        target: MaterializedStorageTarget,
        operations: list[IRExpr],
    ) -> IRExpr:
        expressions = [*target.setup, *operations]
        result = expressions[0] if len(expressions) == 1 else IRCommaExpr(expressions=expressions)
        if not target.declarations:
            return result
        return IRStmtExpr(stmts=target.declarations, result=result)

    @staticmethod
    def materialize_index_target(
        receiver: IRExpr,
        index: IRExpr,
        receiver_type,
    ) -> IRIndex:
        """Build a physical indexed storage target from stabilized operands."""
        return IRIndex(obj=receiver, index=index).record_index_storage(receiver_type)

    def _owned_identifier_slot(
        self,
        target,
        target_type: TypeExpr | None,
        provenance: CallableProvenance,
    ) -> TypeExpr | None:
        """Return the managed domain of one exact local or defined-global slot."""
        if not isinstance(target, Identifier):
            return None
        registered_type = self._ownership.managed_local_value_type(target.name, provenance)
        if registered_type is not None:
            concrete = self._types.resolve_active_type(registered_type)
            if concrete is None or not self._values.is_managed(concrete):
                raise CodegenError("registered managed slot has an unmanaged semantic type")
            return concrete
        if self._session.local_is_declared(target.name):
            return None
        concrete = self._types.resolve_active_type(target_type)
        if concrete is None or not self._values.is_managed(concrete):
            return None
        return concrete if target.name in self._analyzed.defined_global_names else None

    def _static_field_symbol(self, target) -> str | None:
        """Return the C symbol for a class-designated static source field."""
        if not isinstance(target, FieldAccessExpr) or not isinstance(target.obj, Identifier):
            return None
        class_name = target.obj.name
        if self._session.local_is_declared(class_name):
            return None
        class_info = self._analyzed.class_table.get(class_name)
        if class_info is None or target.field not in class_info.static_fields:
            return None
        return f"{class_name}_{target.field}"

    def _temporary(self, type_expr, prefix: str, *, managed: bool = False) -> IRVarDecl:
        declaration = IRVarDecl(
            c_type=CType(text=self._types.render(type_expr)),
            name=self._session.fresh_temp(prefix),
            init=IRLiteral(text="NULL") if managed else None,
        )
        self._session.record_declaration(declaration)
        return declaration

    def _class_prefix(self, receiver_type: TypeExpr, class_info) -> str:
        if receiver_type.generic_args and class_info.generic_params:
            return self._type_identity.specialization_symbol(receiver_type.base, receiver_type.generic_args)
        return receiver_type.base

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
        initializer_type: TypeExpr | None = None,
        initializer_owned: bool | None = None,
        array_size: IRExpr | None,
        logical_length: IRExpr | None = None,
    ) -> list[IRStmt]:
        """Materialize a declaration from values lowered by the statement owner."""
        source = plan.source
        captured_callable = self._materialize_captured_callable_declaration(
            plan,
            provenance,
            initializer,
        )
        if captured_callable is not None:
            return captured_callable
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
        self.declare_c_binding(source.name, is_array=is_array, logical_length=logical_length)
        self._ownership.declare_local_ownership(source.name, provenance, c_name=plan.c_name)
        provenance.bind_local(source.name, source.type, source.initializer)
        result: list[IRStmt] = [declaration]
        if external:
            result.append(StorageLowerer.mark_external_declaration_used(plan.c_name))
            return result
        source_type = initializer_type or self._session.type_of(source.initializer)
        managed_type = (
            source.type
            if self._values.is_managed(source.type)
            else source_type
            if self._values.is_managed(source_type)
            else None
        )
        if managed_type is not None:
            runtime_type = self._values.runtime_name(managed_type)
            owns_initializer = (
                initializer_owned
                if initializer_owned is not None
                else bool(
                    source.initializer is not None
                    and self._ownership.lowered_result_is_owned(source.initializer, provenance=provenance)
                )
            )
            if source.initializer is not None and not owns_initializer:
                result.append(IRExprStmt(expr=self._lifetime.retain_value(IRVar(name=plan.c_name), managed_type)))
            self._ownership.register_managed_var(
                source.name,
                runtime_type,
                managed_type,
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

    def _materialize_captured_callable_declaration(
        self,
        plan: VariableDeclarationPlan,
        provenance: CallableProvenance,
        initializer: IRExpr | None,
    ) -> list[IRStmt] | None:
        """Represent one non-escaping captured lambda as a stack environment."""
        source = plan.source
        lambda_expr = source.initializer
        if not isinstance(lambda_expr, LambdaExpr) or not lambda_expr.captures:
            return None
        if not isinstance(initializer, IRFunctionRef):
            raise CodegenError("captured lambda declaration requires one lifted function reference")

        environment_name = f"__{plan.c_name}_env"
        environment_declaration = IRVarDecl(
            c_type=CType(text=f"struct {initializer.name}_env"),
            name=environment_name,
        )
        self._session.record_declaration(environment_declaration)
        self.declare_c_binding(source.name, is_array=False)
        self._ownership.declare_local_ownership(
            source.name,
            provenance,
            c_name=plan.c_name,
        )
        provenance.bind_captured_local(
            source.name,
            source.type,
            lambda_expr,
            function_name=initializer.name,
            variable_name=environment_name,
        )

        result: list[IRStmt] = [environment_declaration]
        environment = IRVar(name=environment_name)
        for capture in lambda_expr.captures:
            field_name = provenance.source_binding_c_name(capture.name)
            binding_name = self._ownership.source_binding_c_name(capture.name, provenance)
            result.append(
                IRAssign(
                    target=IRFieldAccess(obj=environment, field=field_name, arrow=False),
                    value=IRVar(name=binding_name),
                )
            )
        return result

    def validate_declaration_initializer(self, plan: VariableDeclarationPlan) -> None:
        """Reject initialized VLA storage that has no supported materialization."""
        source = plan.source
        type_expr = source.type
        if (
            type_expr is not None
            and type_expr.is_array
            and type_expr.array_size is not None
            and source.initializer is not None
            and id(type_expr.array_size) not in self._analyzed.constant_array_bound_ids
        ):
            raise CodegenError(f"Variable '{source.name}' is a variable-length array and cannot have an initializer")

    def materialize_array_size(
        self,
        plan: VariableDeclarationPlan,
        lowered_size: IRExpr,
    ) -> IRExpr:
        """Preserve C constant bounds and guard only runtime-sized storage."""
        if id(plan.array_size) in self._analyzed.constant_array_bound_ids:
            return lowered_size
        return self.safe_array_size(lowered_size)

    def materialize_array_bound(
        self,
        plan: VariableDeclarationPlan,
        lowered_size: IRExpr,
    ) -> ArrayBound:
        """Evaluate a declared bound once, then clamp only its C storage extent.

        A runtime bound may call an effectful function, so it is bound to a typed
        local before the array declaration reads it. Constant bounds stay direct
        so C keeps a constant-expression array rather than a VLA.
        """

        if id(plan.array_size) in self._analyzed.constant_array_bound_ids:
            return ArrayBound(setup=(), physical=lowered_size, logical=None)
        declaration = IRVarDecl(
            c_type=CType(text=self._array_bound_c_type(plan)),
            name=self._session.fresh_temp("__btrc_array_bound"),
            init=lowered_size,
        )
        self._session.record_declaration(declaration)
        bound = IRVar(name=declaration.name)
        return ArrayBound(
            setup=(declaration,),
            physical=self.safe_array_size(bound),
            logical=bound,
        )

    def materialize_dispatch_length(self, length: IRExpr) -> ArrayBound:
        """Bind a GPU result's dispatch length so it can be read more than once.

        The declaration clamps the length for C storage while chained dispatch
        and iteration keep the unclamped value, so an empty result stays empty
        instead of inheriting its one-element physical capacity.
        """

        if isinstance(length, (IRVar, IRLiteral)):
            return ArrayBound(setup=(), physical=self.safe_array_size(length), logical=length)
        declaration = IRVarDecl(
            c_type=CType(text="int"),
            name=self._session.fresh_temp("__gpu_output_length"),
            init=length,
        )
        self._session.record_declaration(declaration)
        bound = IRVar(name=declaration.name)
        return ArrayBound(
            setup=(declaration,),
            physical=self.safe_array_size(bound),
            logical=bound,
        )

    def _array_bound_c_type(self, plan: VariableDeclarationPlan) -> str:
        """Render the declared bound's own scalar type so nothing is truncated."""

        bound_type = self._session.type_of(plan.array_size)
        if bound_type is None or bound_type.pointer_depth or bound_type.is_array:
            return "int"
        return self._types.render(bound_type)

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
