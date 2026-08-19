"""Cohesive ownership IR lowering owner."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.analyzer.storage import StorageModel
from src.compiler.python.analyzer.types import IndexedProtocolResolver, TypeIdentity, TypeShapeError, TypeSystem
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCleanupSlot,
    IRCommaExpr,
    IRCompoundLiteral,
    IRDeref,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionRef,
    IRGlobalDecl,
    IRIf,
    IRInitializerList,
    IRLiteral,
    IRParam,
    IRReturn,
    IRStmt,
    IRStmtExpr,
    IRStructField,
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
    Identifier,
    IndexExpr,
    IntLiteral,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    NullLiteral,
    ReturnStmt,
    SelfExpr,
    SizeofExpr,
    SpawnExpr,
    StringLiteral,
    SuperExpr,
    TernaryExpr,
    TupleLiteral,
    TypeExpr,
    UnaryExpr,
)

from .types import CodegenError, CTypeLowerer

if TYPE_CHECKING:
    from .session import LoweringSession

ARC_HEADER_FIELD = "__arc"
_MANAGED_REGISTER = "__btrc_register_cleanup"
_DIRECT_REGISTER = "__btrc_register_direct_cleanup"
BUILTIN_COLLECTION_LAYOUTS = {
    "Vector": (1, frozenset({"data", "len"})),
    "Array": (1, frozenset({"data", "len"})),
    "List": (1, frozenset({"head", "tail", "len"})),
    "Map": (2, frozenset({"keys", "values", "occupied", "cap"})),
    "Set": (1, frozenset({"keys", "occupied", "cap"})),
}
STRING_RUNTIME_NAME = "__btrc_managed_string"
MUTEX_RUNTIME_NAME = "__btrc_managed_mutex"


@dataclass(frozen=True, slots=True)
class ManagedReleasePlan:
    """Analyzed release operation awaiting operand materialization."""

    source: object
    type_expr: TypeExpr | None
    managed: bool


@dataclass(frozen=True, slots=True)
class ReturnPlan:
    """Return ownership facts awaiting an explicitly lowered source value."""

    source: object | None
    return_type: TypeExpr | None
    return_c_type: str
    returned_local: str | None


class CleanupSlotRegistry:
    """Own typed cleanup/access adapters for one generated translation unit."""

    def __init__(self, session: LoweringSession) -> None:
        self.module = session.module
        self._session = session
        self._take_adapters: dict[str, str] = {}
        self._arc_slot_adapters: dict[str, str] = {}
        self._mutex_value_adapters: dict[str, str] = {}
        self._definitions: list[IRFunctionDef] = []
        self._finalized = False

    def register(self, declaration, cleanup_fn, *, visitor=None, direct: bool = False) -> IRCall:
        """Build a registration that clears a slot through its exact type."""
        if not isinstance(declaration, IRVarDecl):
            raise TypeError("cleanup registration requires its IRVarDecl")
        if declaration.is_static or declaration.is_extern or declaration.array_size is not None:
            raise ValueError(f"cleanup slot {declaration.name!r} must be an automatic pointer object")
        take_function = self._ensure_take_adapter(declaration.c_type)
        proposed = IRCleanupSlot(name=declaration.name, c_type=declaration.c_type, take_function=take_function)
        metadata = declaration.cleanup_slot
        if metadata is not None and metadata != proposed:
            raise ValueError(f"cleanup slot {declaration.name!r} has conflicting typed metadata")
        if metadata is None:
            metadata = proposed
            declaration.cleanup_slot = metadata
        declaration.is_volatile = True
        helper = _DIRECT_REGISTER if direct else _MANAGED_REGISTER
        self._session.require_helper(helper)
        args = [
            IRCast(target_type=CType(text="void*"), expr=IRAddressOf(expr=IRVar(name=declaration.name))),
            IRFunctionRef(name=take_function),
            cleanup_fn,
        ]
        if not direct:
            if visitor is None:
                raise ValueError("managed cleanup registration requires a visitor expression")
            args.append(visitor)
        return IRCall(callee=helper, args=args, helper_ref=helper, cleanup_slot=metadata)

    def require_declaration(self, statements, name: str) -> IRVarDecl:
        """Resolve the innermost declaration preceding a registration."""
        for statement in reversed(statements):
            if isinstance(statement, IRVarDecl) and statement.name == name:
                return statement
        raise ValueError(f"cleanup registration for {name!r} has no preceding IRVarDecl")

    def finalize(self) -> None:
        """Place typed adapters before every function that references them."""
        if not self._definitions:
            return
        if self._finalized:
            raise ValueError("cleanup take adapters were finalized more than once")
        self.module.function_defs[0:0] = self._definitions
        self._finalized = True

    def ensure_arc_slot_adapter(self, slot_type: CType) -> str:
        """Return an exact-typed transactional callback for one ARC slot."""
        existing = self._arc_slot_adapters.get(slot_type.text)
        if existing is not None:
            return existing
        name = f"__btrc_arc_slot_access_{len(self._arc_slot_adapters) + 1}"
        self._arc_slot_adapters[slot_type.text] = name
        self._definitions.append(self._delete_slot_adapter(name, slot_type))
        return name

    def ensure_mutex_value_adapter(self, value_type: CType) -> str:
        """Return an exact-typed load callback for opaque Mutex storage."""
        existing = self._mutex_value_adapters.get(value_type.text)
        if existing is not None:
            return existing
        name = f"__btrc_mutex_value_access_{len(self._mutex_value_adapters) + 1}"
        self._mutex_value_adapters[value_type.text] = name
        self._definitions.append(self._mutex_value_adapter(name, value_type))
        return name

    def _ensure_take_adapter(self, slot_type: CType) -> str:
        existing = self._take_adapters.get(slot_type.text)
        if existing is not None:
            return existing
        name = f"__btrc_cleanup_take_{len(self._take_adapters) + 1}"
        self._take_adapters[slot_type.text] = name
        self._definitions.append(self._take_adapter(name, slot_type))
        return name

    def _take_adapter(self, name: str, slot_type: CType) -> IRFunctionDef:
        typed_slot_type = CType(text=f"{slot_type} volatile*")
        typed_slot = IRVar(name="typed_slot")
        return IRFunctionDef(
            name=name,
            return_type=CType(text="void*"),
            params=[IRParam(c_type=CType(text="void*"), name="raw_slot")],
            body=IRBlock(
                stmts=[
                    IRVarDecl(
                        c_type=typed_slot_type,
                        name="typed_slot",
                        init=IRCast(target_type=typed_slot_type, expr=IRVar(name="raw_slot")),
                    ),
                    IRVarDecl(c_type=slot_type, name="value", init=IRDeref(expr=typed_slot)),
                    IRAssign(target=IRDeref(expr=typed_slot), value=IRLiteral(text="NULL")),
                    IRReturn(value=IRCast(target_type=CType(text="void*"), expr=IRVar(name="value"))),
                ]
            ),
            is_static=True,
        )

    def _delete_slot_adapter(self, name: str, slot_type: CType) -> IRFunctionDef:
        typed_slot_type = CType(text=f"{slot_type} volatile*")
        typed_slot = IRVar(name="typed_slot")
        current = IRVar(name="current")
        return IRFunctionDef(
            name=name,
            return_type=CType(text="void*"),
            params=[
                IRParam(c_type=CType(text="volatile void*"), name="raw_slot"),
                IRParam(c_type=CType(text="void*"), name="expected"),
                IRParam(c_type=CType(text="void*"), name="replacement"),
                IRParam(c_type=CType(text="int"), name="replace_if_equal"),
            ],
            body=IRBlock(
                stmts=[
                    IRVarDecl(
                        c_type=typed_slot_type,
                        name="typed_slot",
                        init=IRCast(target_type=typed_slot_type, expr=IRVar(name="raw_slot")),
                    ),
                    IRVarDecl(c_type=slot_type, name="current", init=IRDeref(expr=typed_slot)),
                    IRIf(
                        condition=IRBinOp(
                            left=IRVar(name="replace_if_equal"),
                            op="&&",
                            right=IRBinOp(
                                left=current, op="==", right=IRCast(target_type=slot_type, expr=IRVar(name="expected"))
                            ),
                        ),
                        then_block=IRBlock(
                            stmts=[
                                IRAssign(
                                    target=IRDeref(expr=typed_slot),
                                    value=IRCast(target_type=slot_type, expr=IRVar(name="replacement")),
                                )
                            ]
                        ),
                    ),
                    IRReturn(value=IRCast(target_type=CType(text="void*"), expr=current)),
                ]
            ),
            is_static=True,
        )

    def _mutex_value_adapter(self, name: str, value_type: CType) -> IRFunctionDef:
        storage_type = CType(text=f"{value_type} const*")
        return IRFunctionDef(
            name=name,
            return_type=CType(text="void*"),
            params=[IRParam(c_type=CType(text="const void*"), name="raw_storage")],
            body=IRBlock(
                stmts=[
                    IRReturn(
                        value=IRCast(
                            target_type=CType(text="void*"),
                            expr=IRDeref(expr=IRCast(target_type=storage_type, expr=IRVar(name="raw_storage"))),
                        )
                    )
                ]
            ),
            is_static=True,
        )


@dataclass(frozen=True)
class DirectVisitAction:
    """A managed slot whose target must join the collector candidate graph."""

    emitted_name: str


class CycleMetadata:
    """Own cycle graph queries and one lowering run's emitted classifications."""

    def __init__(self, analyzed: AnalyzedProgram, values: ManagedValueSemantics, type_identity: TypeIdentity) -> None:
        self._analyzed = analyzed
        self._values = values
        self._type_identity = type_identity
        self._visitor_types: set[str] = set()
        self._emitted_may_cycle: dict[str, bool] = {}
        self._may_cycle_cache: dict[str, bool] = {}

    def visitor_symbol(self, emitted_name: str) -> str:
        return f"__btrc_arc_visit_{emitted_name}"

    def generic_instance_needs_visitor(
        self, base: str, arguments: list[TypeExpr], seen: set[tuple] | None = None
    ) -> bool:
        """Whether a concrete generic representation owns managed slots."""
        info = self._analyzed.class_table.get(base)
        if info is None or not info.generic_params:
            return False
        key = self._type_identity.generic_instance_key(base, arguments)
        seen = set() if seen is None else seen
        if key in seen:
            return False
        seen.add(key)
        try:
            if base in BUILTIN_COLLECTION_LAYOUTS:
                arity, _fields = BUILTIN_COLLECTION_LAYOUTS[base]
                if len(arguments) != arity:
                    return False
                return base == "List" or any(self.visit_action(argument, seen) is not None for argument in arguments)
            substitutions = dict(zip(info.generic_params, arguments))
            return any(
                (
                    field.type is not None
                    and self._type_has_visit_action(self._substitute_type(field.type, substitutions), seen)
                    for _name, field in info.instance_storage
                )
            )
        finally:
            seen.remove(key)

    def visitor_for(self, type_expr: TypeExpr) -> str | None:
        """Return the concrete cycle visitor for a managed source type."""
        type_expr = self._values.canonical(type_expr) or type_expr
        if self._values.is_mutex(type_expr):
            return "__btrc_mutex_arc_visit"
        if not self.type_needs_visitor(type_expr, set()):
            return None
        emitted = (
            self._type_identity.specialization_symbol(type_expr.base, type_expr.generic_args)
            if type_expr.generic_args
            else type_expr.base
        )
        return self.visitor_symbol(emitted)

    def register_visitor(self, emitted_name: str) -> None:
        self._visitor_types.add(emitted_name)

    def emitted_has_visitor(self, emitted_name: str) -> bool:
        """Check metadata without confusing a source method named ``visit``."""
        if emitted_name == MUTEX_RUNTIME_NAME:
            return True
        if emitted_name in self._visitor_types:
            return True
        info = self.lookup_class_info(emitted_name)
        return bool(
            info is not None and (not info.generic_params) and self.type_needs_visitor(TypeExpr(base=info.name), set())
        )

    def emitted_visitor_symbol(self, emitted_name: str) -> str | None:
        if emitted_name == MUTEX_RUNTIME_NAME:
            return "__btrc_mutex_arc_visit"
        if not self.emitted_has_visitor(emitted_name):
            return None
        return self.visitor_symbol(emitted_name)

    def emitted_may_cycle(self, emitted_name: str) -> bool:
        """Whether an emitted representation can join a retain cycle."""
        if emitted_name in self._emitted_may_cycle:
            return self._emitted_may_cycle[emitted_name]
        info = self._analyzed.class_table.get(emitted_name)
        if info is not None and (not info.generic_params):
            return self.type_may_cycle(TypeExpr(base=emitted_name))
        return True

    def visit_action(self, type_expr: TypeExpr, seen: set[tuple] | None = None) -> DirectVisitAction | None:
        """Return one typed heap edge, or ``None`` for unmanaged storage."""
        type_expr = self._values.canonical(type_expr) or type_expr
        if type_expr.is_array:
            return None
        if self._values.is_mutex(type_expr):
            return DirectVisitAction(MUTEX_RUNTIME_NAME)
        if not self._values.is_class(type_expr):
            return None
        info = self._analyzed.class_table.get(type_expr.base)
        if info is None:
            return None
        emitted = (
            self._type_identity.specialization_symbol(type_expr.base, type_expr.generic_args)
            if type_expr.generic_args
            else type_expr.base
        )
        return DirectVisitAction(emitted)

    def type_needs_visitor(self, type_expr: TypeExpr, seen: set[tuple] | None = None) -> bool:
        """Whether this concrete representation has managed outgoing edges."""
        type_expr = self._values.canonical(type_expr) or type_expr
        if type_expr.is_array:
            return False
        if self._values.is_mutex(type_expr):
            return True
        if not self._values.is_class(type_expr):
            return False
        info = self._analyzed.class_table.get(type_expr.base)
        if info is None:
            return False
        if type_expr.generic_args:
            return self.generic_instance_needs_visitor(type_expr.base, list(type_expr.generic_args), seen)
        return any(
            (
                getattr(field, "type", None) is not None and self._type_has_visit_action(field.type, set())
                for _name, field in info.instance_storage
            )
        )

    def type_may_cycle(self, type_expr: TypeExpr) -> bool:
        """Return whether any runtime value of this type may join a cycle."""
        return any(self._concrete_type_may_cycle(candidate) for candidate in self._runtime_type_candidates(type_expr))

    def lookup_class_info(self, class_name: str):
        """Look up class metadata by source or concrete specialization name."""
        info = self._analyzed.class_table.get(class_name)
        if info is not None:
            return info
        for source_name, candidate in self._analyzed.class_table.items():
            if class_name.startswith(f"btrc_{source_name}"):
                return candidate
        return None

    def _concrete_type_may_cycle(self, type_expr: TypeExpr) -> bool:
        type_expr = self._values.canonical(type_expr) or type_expr
        if not self._values.is_arc(type_expr):
            return False
        info = self._analyzed.class_table.get(type_expr.base)
        if info is not None and info.generic_params and (not type_expr.generic_args):
            return True
        root = self._emitted_name(type_expr)
        cached = self._may_cycle_cache.get(root)
        if cached is not None:
            return cached
        visited: set[str] = set()
        stack = self._outgoing_managed_types(type_expr)
        while stack:
            current = stack.pop()
            emitted = self._emitted_name(current)
            if emitted == root:
                self._may_cycle_cache[root] = True
                return True
            if emitted in visited:
                continue
            visited.add(emitted)
            stack.extend(self._outgoing_managed_types(current))
        self._may_cycle_cache[root] = False
        return False

    def _outgoing_managed_types(self, type_expr: TypeExpr) -> list[TypeExpr]:
        type_expr = self._values.canonical(type_expr) or type_expr
        if not self._values.is_arc(type_expr):
            return []
        if self._values.is_mutex(type_expr):
            payload = type_expr.generic_args[0]
            if not self._values.is_arc(payload):
                return []
            return self._runtime_type_candidates(payload)
        info = self._analyzed.class_table[type_expr.base]
        arguments = list(type_expr.generic_args)
        if arguments and type_expr.base in BUILTIN_COLLECTION_LAYOUTS:
            candidates = (
                [TypeExpr(base="ListNode", generic_args=[arguments[0]])] if type_expr.base == "List" else arguments
            )
            return [
                runtime_type
                for candidate in candidates
                if self._values.is_arc(candidate)
                for runtime_type in self._runtime_type_candidates(candidate)
            ]
        substitutions = dict(zip(info.generic_params, arguments))
        candidates = (
            [
                self._substitute_type(field.type, substitutions)
                for _name, field in info.instance_storage
                if field.type is not None
            ]
            if substitutions
            else [field.type for _name, field in info.instance_storage if field.type is not None]
        )
        outgoing = []
        for candidate in candidates:
            if self._values.is_arc(candidate):
                outgoing.extend(self._runtime_type_candidates(candidate))
        return outgoing

    def _runtime_type_candidates(self, static_type: TypeExpr) -> list[TypeExpr]:
        candidates = [static_type]
        if static_type.generic_args or static_type.base not in self._analyzed.class_table:
            return candidates
        candidates.extend(
            TypeExpr(base=name)
            for name in self._analyzed.class_table
            if name != static_type.base and self._is_subclass(name, static_type.base)
        )
        return candidates

    def _is_subclass(self, child: str, parent: str) -> bool:
        current = child
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            info = self._analyzed.class_table.get(current)
            current = info.parent if info is not None else None
            if current == parent:
                return True
        return False

    def _substitute_type(self, type_expr: TypeExpr, substitutions: dict[str, TypeExpr]) -> TypeExpr:
        try:
            result = self._type_identity.substitute(type_expr, substitutions, reference_resolver=self._values.canonical)
        except TypeShapeError as error:
            raise CodegenError(str(error)) from error
        if result is None:
            raise CodegenError("cycle metadata requires a concrete field type")
        return result

    def _type_has_visit_action(self, type_expr: TypeExpr, seen: set[tuple]) -> bool:
        return self.visit_action(type_expr, seen) is not None

    def _emitted_name(self, type_expr: TypeExpr) -> str:
        if type_expr.generic_args:
            return self._type_identity.specialization_symbol(type_expr.base, type_expr.generic_args)
        return type_expr.base


@dataclass
class ManagedLocal:
    """A local owner and whether releasing it may expose an unreachable cycle."""

    name: str
    type_name: str
    cycle_seed: bool
    c_name: str | None = None
    cleanup_kind: str = "arc"

    def mark_cycle_seed(self) -> None:
        """Conservatively dirty this live ARC alias after graph mutation."""
        if self.cleanup_kind == "arc":
            self.cycle_seed = True


class ManagedValueSemantics:
    """Own managed-domain classification and concrete runtime names."""

    def __init__(
        self,
        analyzed: AnalyzedProgram,
        type_identity: TypeIdentity,
        types: CTypeLowerer,
    ) -> None:
        self._analyzed = analyzed
        self._type_identity = type_identity
        self._types = types

    def canonical(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        return self._types.canonical_type(type_expr)

    def is_string(self, type_expr: TypeExpr | None) -> bool:
        return self._type_identity.is_scalar_string(self.canonical(type_expr))

    def is_class(self, type_expr: TypeExpr | None) -> bool:
        canonical = self.canonical(type_expr)
        depth = (
            canonical.pointer_depth - int(TypeSystem.nullable_collapses_reference_layer(canonical)) if canonical else 0
        )
        return bool(
            canonical is not None
            and (not canonical.is_array)
            and (depth <= 1)
            and (canonical.base in self._analyzed.class_table)
        )

    def is_mutex(self, type_expr: TypeExpr | None) -> bool:
        canonical = self.canonical(type_expr)
        depth = (
            canonical.pointer_depth
            - int(TypeSystem.nullable_collapses_reference_layer(canonical, base_is_reference=True))
            if canonical
            else 0
        )
        return bool(
            canonical is not None
            and (not canonical.is_array)
            and (depth == 0)
            and (canonical.base == "Mutex")
            and (len(canonical.generic_args or ()) == 1)
        )

    def is_arc(self, type_expr: TypeExpr | None) -> bool:
        return self.is_class(type_expr) or self.is_mutex(type_expr)

    def is_managed(self, type_expr: TypeExpr | None) -> bool:
        return self.is_string(type_expr) or self.is_arc(type_expr)

    def runtime_name(self, type_expr: TypeExpr) -> str:
        """Return the concrete ownership-bookkeeping name for a value."""
        if self.is_string(type_expr):
            return STRING_RUNTIME_NAME
        if self.is_mutex(type_expr):
            return MUTEX_RUNTIME_NAME
        canonical = self.canonical(type_expr)
        if canonical is None:
            raise ValueError("managed runtime names require a concrete type")
        info = self._analyzed.class_table.get(canonical.base)
        if canonical.generic_args and info is not None and info.generic_params:
            return self._type_identity.specialization_symbol(canonical.base, canonical.generic_args)
        return canonical.base

    def cleanup_destroy_symbol(self, emitted_name: str) -> str:
        if emitted_name == STRING_RUNTIME_NAME:
            return "__btrc_string_release_cleanup"
        if emitted_name == MUTEX_RUNTIME_NAME:
            return "__btrc_mutex_arc_destroy"
        return f"{emitted_name}_destroy"

    def destroy_symbol(self, type_expr: TypeExpr) -> str:
        """Return the terminal destroy callback for one managed value type."""
        if self.is_string(type_expr):
            return "__btrc_string_release_cleanup"
        if self.is_mutex(type_expr):
            return "__btrc_mutex_arc_destroy"
        return f"{self.runtime_name(type_expr)}_destroy"

    def emitted_value_c_type(self, emitted_name: str) -> str:
        """Return the exact C value type stored by lexical ownership state."""
        if emitted_name == STRING_RUNTIME_NAME:
            return "const char*"
        if emitted_name == MUTEX_RUNTIME_NAME:
            return "__btrc_mutex_val_t*"
        return f"struct {emitted_name}*"


class CleanupScope(Protocol):
    """The lexical cleanup contract used by one retained domain owner."""

    def exception_cleanup_active(self) -> bool: ...

    def mark_cleanup_registration(self) -> None: ...


class CallableBodyFacts(Protocol):
    """Per-body callable facts consumed by ownership decisions."""

    def call_returns_owned(self, expression, effect=None) -> bool: ...

    def conditional_branch_entries(self, expression): ...

    def at_flow(self, state): ...

    def source_binding_c_name(self, name: str) -> str: ...


class CleanupScopeState:
    """Own lexical exception-cleanup markers for one lowering session."""

    def __init__(
        self,
        session: LoweringSession,
        *,
        cross_function_enabled: bool,
    ) -> None:
        self._session = session
        self._cross_function_enabled = cross_function_enabled
        self._markers: list[str | None] = []
        self._active_markers: set[str] = set()
        self._control_depths: list[int] = []

    @contextmanager
    def isolated(self):
        """Isolate marker state while lowering a lifted function body."""
        previous = (self._markers, self._active_markers, self._control_depths)
        self._markers = []
        self._active_markers = set()
        self._control_depths = []
        try:
            yield
        finally:
            self._markers, self._active_markers, self._control_depths = previous

    def push_control_context(self) -> None:
        self._control_depths.append(len(self._markers))

    def pop_control_context(self) -> None:
        if self._control_depths:
            self._control_depths.pop()

    def push(self) -> str | None:
        marker = self._session.fresh_temp("__btrc_cleanup_scope") if self.exception_cleanup_active() else None
        self._markers.append(marker)
        return marker

    def pop(self) -> None:
        if not self._markers:
            return
        marker = self._markers.pop()
        if marker is not None:
            self._active_markers.discard(marker)

    def mark_cleanup_registration(self) -> None:
        if not self._markers:
            return
        marker = self._markers[-1]
        if marker is not None:
            self._active_markers.add(marker)

    def is_active(self, marker: str | None) -> bool:
        return marker is not None and marker in self._active_markers

    def exception_cleanup_active(self) -> bool:
        return self._session.in_try_depth > 0 or self._cross_function_enabled

    def control_marker(self, targets: set[str]) -> str | None:
        for index in range(len(self._session.control_context) - 1, -1, -1):
            if self._session.control_context[index] not in targets:
                continue
            depth = self._control_depths[index]
            return next(
                (marker for marker in self._markers[depth:] if self.is_active(marker)),
                None,
            )
        return None

    def return_marker(self) -> str | None:
        return next(
            (marker for marker in self._markers if self.is_active(marker)),
            None,
        )

    def entry(self, marker: str | None) -> list[IRStmt]:
        if marker is None:
            return []
        self._session.require_helper("__btrc_cleanup_mark")
        return [
            IRVarDecl(
                c_type=CType(text="int"),
                name=marker,
                init=IRCall(
                    callee="__btrc_cleanup_mark",
                    args=[],
                    helper_ref="__btrc_cleanup_mark",
                ),
            )
        ]

    def exit(self, marker: str | None) -> list[IRStmt]:
        if marker is None:
            return []
        self._session.require_helper("__btrc_discard_cleanups_to")
        return [
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_discard_cleanups_to",
                    args=[IRVar(name=marker)],
                    helper_ref="__btrc_discard_cleanups_to",
                )
            )
        ]


class ManagedLifetimeLowerer:
    """Lower every managed-value lifetime transition for one lexical context."""

    def __init__(
        self,
        *,
        context: LoweringSession,
        analyzed: AnalyzedProgram,
        values: ManagedValueSemantics,
        cycles: CycleMetadata,
        cleanup_slots: CleanupSlotRegistry,
        cleanup_scope: CleanupScope,
        types: CTypeLowerer,
    ) -> None:
        self._session = context
        self._analyzed = analyzed
        self._values = values
        self._cycles = cycles
        self._cleanup_slots = cleanup_slots
        self._cleanup_scope = cleanup_scope
        self._types = types

    def require_helper(self, name: str) -> None:
        self._session.require_helper(name)

    def retain_value(self, value, type_expr):
        helper = "__btrc_string_retain" if self._values.is_string(type_expr) else "__btrc_arc_retain"
        self._session.require_helper(helper)
        return IRCall(callee=helper, args=[value], helper_ref=helper)

    def retain_edge_value(self, value, type_expr, owner):
        if self._values.is_string(type_expr):
            return self.retain_value(value, type_expr)
        helper = "__btrc_arc_retain_edge"
        self._session.require_helper(helper)
        return IRCall(callee=helper, args=[value, owner], helper_ref=helper)

    def adopt_edge_value(self, value, type_expr, owner):
        if self._values.is_string(type_expr):
            return self._no_op()
        helper = "__btrc_arc_adopt_edge"
        self._session.require_helper(helper)
        return IRCall(callee=helper, args=[value, owner], helper_ref=helper)

    def unlink_edge_value(self, value, type_expr, owner=None):
        if self._values.is_string(type_expr):
            return self._no_op()
        helper = "__btrc_arc_unlink_edge"
        self._session.require_helper(helper)
        return IRCall(
            callee=helper, args=[value, owner if owner is not None else IRLiteral(text="NULL")], helper_ref=helper
        )

    def replace_edge_value(self, slot, replacement, type_expr, owner, *, adopt: bool):
        """Replace one persistent class edge as one topology transaction."""
        if not self._values.is_arc(type_expr):
            raise ValueError("transactional edge replacement requires an ARC type")
        access = self._cleanup_slots.ensure_arc_slot_adapter(CType(text=self._types.render(type_expr)))
        helper = "__btrc_arc_replace_edge"
        self._session.require_helper(helper)
        return IRCall(
            callee=helper,
            helper_ref=helper,
            args=[
                IRCast(target_type=CType(text="volatile void*"), expr=IRAddressOf(expr=slot)),
                IRFunctionRef(name=access),
                replacement,
                owner,
                self.arc_type_descriptor(type_expr),
                IRLiteral(text="1" if adopt else "0"),
            ],
        )

    def release_value(self, value, type_expr):
        if self._values.is_string(type_expr):
            helper = "__btrc_string_release"
            self._session.require_helper(helper)
            return IRCall(callee=helper, args=[value], helper_ref=helper)
        helper = "__btrc_arc_release" if self._cycles.type_may_cycle(type_expr) else "__btrc_arc_release_acyclic"
        self._session.require_helper(helper)
        return IRCall(callee=helper, args=[value, self.arc_type_descriptor(type_expr)], helper_ref=helper)

    def release_edge_value(self, value, type_expr, replacement=None):
        if self._values.is_string(type_expr):
            return self.release_value(value, type_expr)
        helper = "__btrc_arc_release_edge"
        self._session.require_helper(helper)
        return IRCall(
            callee=helper,
            helper_ref=helper,
            args=[
                value,
                self.arc_type_descriptor(type_expr),
                replacement if replacement is not None else IRLiteral(text="NULL"),
            ],
        )

    def release_emitted_value(self, value, emitted_name: str):
        if emitted_name == STRING_RUNTIME_NAME:
            helper = "__btrc_string_release"
            self._session.require_helper(helper)
            return IRCall(callee=helper, args=[value], helper_ref=helper)
        helper = (
            "__btrc_arc_release" if self.emitted_release_can_enqueue(emitted_name) else "__btrc_arc_release_acyclic"
        )
        self._session.require_helper(helper)
        return IRCall(callee=helper, args=[value, self.emitted_type_descriptor(emitted_name)], helper_ref=helper)

    def release_scope(self, managed, *, force: bool = True) -> list[IRStmt]:
        """Clear and release every owner leaving one lexical scope."""
        statements: list[IRStmt] = []
        for local in reversed(managed):
            local_c_name = local.c_name or local.name
            if local.cleanup_kind == "thread":
                self._session.require_helper("__btrc_thread_free")
                statements.append(
                    IRExprStmt(
                        expr=IRCall(
                            callee="__btrc_thread_free",
                            args=[self._take_thread_handle(IRVar(name=local_c_name))],
                            helper_ref="__btrc_thread_free",
                        )
                    )
                )
                continue
            value_decl = IRVarDecl(
                c_type=CType(text=self._values.emitted_value_c_type(local.type_name)),
                name=self._session.fresh_temp("__btrc_scope_released"),
                init=IRVar(name=local_c_name),
            )
            self._session.record_declaration(value_decl)
            statements.extend(
                [
                    value_decl,
                    IRAssign(target=IRVar(name=local_c_name), value=IRLiteral(text="NULL")),
                    IRExprStmt(expr=self.release_emitted_value(IRVar(name=value_decl.name), local.type_name)),
                ]
            )
        emitted_names = [
            local.type_name
            for local in managed
            if local.cleanup_kind == "arc" and local.type_name != STRING_RUNTIME_NAME
        ]
        flush = (
            self.flush_release_batch(emitted_names=emitted_names)
            if force
            else self.poll_release_batch(emitted_names=emitted_names)
        )
        if flush is not None:
            statements.append(IRExprStmt(expr=flush))
        return statements

    def arc_type_descriptor(self, type_expr):
        """Build the copied runtime descriptor for one concrete managed type."""
        if self._values.is_mutex(type_expr):
            self._session.require_helper("__btrc_mutex_arc_type")
            return IRAddressOf(expr=IRVar(name="__btrc_mutex_arc_descriptor"))
        visitor = self._cycles.visitor_for(type_expr)
        return IRAddressOf(
            expr=IRCompoundLiteral(
                c_type=CType(text="__btrc_arc_type"),
                fields=[
                    ("visit", IRFunctionRef(name=visitor) if visitor else IRLiteral(text="NULL")),
                    ("destroy", IRFunctionRef(name=self._values.destroy_symbol(type_expr))),
                    ("hook", IRLiteral(text="NULL")),
                    ("guard", IRLiteral(text="NULL")),
                    ("raise", IRLiteral(text="NULL")),
                ],
            )
        )

    def emitted_type_descriptor(self, emitted_name: str):
        if emitted_name == MUTEX_RUNTIME_NAME:
            self._session.require_helper("__btrc_mutex_arc_type")
            return IRAddressOf(expr=IRVar(name="__btrc_mutex_arc_descriptor"))
        visitor = self._cycles.emitted_visitor_symbol(emitted_name)
        return IRAddressOf(
            expr=IRCompoundLiteral(
                c_type=CType(text="__btrc_arc_type"),
                fields=[
                    ("visit", IRFunctionRef(name=visitor) if visitor else IRLiteral(text="NULL")),
                    ("destroy", IRFunctionRef(name=f"{emitted_name}_destroy")),
                    ("hook", IRLiteral(text="NULL")),
                    ("guard", IRLiteral(text="NULL")),
                    ("raise", IRLiteral(text="NULL")),
                ],
            )
        )

    def poll_released_values(self, *type_exprs):
        return self.release_batch_boundary(
            type_exprs=[value for value in type_exprs if self._values.is_arc(value)], force=False
        )

    def flush_released_values(self, *type_exprs):
        return self.release_batch_boundary(
            type_exprs=[value for value in type_exprs if self._values.is_arc(value)], force=True
        )

    def poll_release_batch(self, *, type_exprs=(), emitted_names=()):
        return self.release_batch_boundary(
            type_exprs=type_exprs,
            emitted_names=emitted_names,
            force=False,
        )

    def flush_release_batch(self, *, type_exprs=(), emitted_names=()):
        return self.release_batch_boundary(
            type_exprs=type_exprs,
            emitted_names=emitted_names,
            force=True,
        )

    def release_batch_boundary(self, *, type_exprs=(), emitted_names=(), force: bool):
        can_enqueue = any(self._cycles.type_may_cycle(item) for item in type_exprs) or any(
            self.emitted_release_can_enqueue(item) for item in emitted_names
        )
        if not can_enqueue:
            return None
        helper = "__btrc_flush_cycles" if force else "__btrc_poll_cycles"
        self._session.require_helper(helper)
        if not force:
            self._session.require_helper("__btrc_flush_cycles")
        return IRCall(callee=helper, args=[], helper_ref=helper)

    def emitted_release_can_enqueue(self, emitted_name: str) -> bool:
        if emitted_name == MUTEX_RUNTIME_NAME:
            return True
        return self._cycles.emitted_may_cycle(emitted_name)

    def cleanup_registration(self, declaration, type_expr, prefix, *, active: bool | None = None):
        """Build one exception cleanup registration guarded by a local flag."""
        if active is None:
            active = self._cleanup_scope.exception_cleanup_active()
        if not active:
            return ([], [])
        self._cleanup_scope.mark_cleanup_registration()
        flag_decl = IRVarDecl(
            c_type=CType(text="bool"), name=self._session.fresh_temp(prefix), init=IRLiteral(text="false")
        )
        self._session.record_declaration(flag_decl)
        flag = IRVar(name=flag_decl.name)
        emitted_name = self._values.runtime_name(type_expr)
        destroy = self._values.cleanup_destroy_symbol(emitted_name)
        string_cleanup = emitted_name == STRING_RUNTIME_NAME
        if string_cleanup:
            self._session.require_helper(destroy)
        visitor = None if string_cleanup else self._visitor_expression(type_expr)
        register = self._cleanup_slots.register(
            declaration, IRFunctionRef(name=destroy), visitor=visitor, direct=string_cleanup
        )
        register_once = IRTernary(
            condition=flag,
            true_expr=IRLiteral(text="0"),
            false_expr=IRCommaExpr(
                expressions=[register, IRBinOp(left=flag, op="=", right=IRLiteral(text="true")), IRLiteral(text="0")]
            ),
        )
        return ([flag_decl], [register_once])

    def register_named_cleanup(self, var_name: str, emitted_name: str, statements: list[IRStmt]) -> None:
        """Register one named managed local with the active cleanup scope."""
        if not self._cleanup_scope.exception_cleanup_active():
            return
        self._cleanup_scope.mark_cleanup_registration()
        declaration = self._cleanup_slots.require_declaration(statements, var_name)
        destroy = self._values.cleanup_destroy_symbol(emitted_name)
        if emitted_name == STRING_RUNTIME_NAME:
            self._session.require_helper(destroy)
            statements.append(
                IRExprStmt(expr=self._cleanup_slots.register(declaration, IRFunctionRef(name=destroy), direct=True))
            )
            return
        visitor_name = self._cycles.emitted_visitor_symbol(emitted_name)
        if emitted_name == MUTEX_RUNTIME_NAME:
            self._session.require_helper("__btrc_mutex_arc_type")
        visitor = IRFunctionRef(name=visitor_name) if visitor_name else IRLiteral(text="NULL")
        statements.append(
            IRExprStmt(expr=self._cleanup_slots.register(declaration, IRFunctionRef(name=destroy), visitor=visitor))
        )

    def register_direct_cleanup(self, var_name: str, cleanup_fn: str, statements: list[IRStmt]) -> None:
        if not self._cleanup_scope.exception_cleanup_active():
            return
        self._cleanup_scope.mark_cleanup_registration()
        declaration = self._cleanup_slots.require_declaration(statements, var_name)
        self._session.require_helper(cleanup_fn)
        statements.append(
            IRExprStmt(expr=self._cleanup_slots.register(declaration, IRFunctionRef(name=cleanup_fn), direct=True))
        )

    def protect_temporary(
        self, declaration, type_expr, declarations, prefix, flag_prefix, *, active: bool | None = None
    ) -> None:
        cleanup_decls, cleanup_exprs = self.cleanup_registration(declaration, type_expr, flag_prefix, active=active)
        declarations.extend(cleanup_decls)
        prefix.extend(cleanup_exprs)

    def release_and_clear(self, value, type_expr, declarations, c_type) -> list:
        saved_decl = IRVarDecl(c_type=CType(text=c_type), name=self._session.fresh_temp("__btrc_released_operand"))
        self._session.record_declaration(saved_decl)
        declarations.append(saved_decl)
        saved = IRVar(name=saved_decl.name)
        expressions = [
            IRBinOp(left=saved, op="=", right=value),
            IRBinOp(left=value, op="=", right=IRLiteral(text="NULL")),
            self.release_value(saved, type_expr),
        ]
        poll = self.poll_release_batch(type_exprs=[type_expr] if self._values.is_arc(type_expr) else [])
        if poll is not None:
            expressions.append(poll)
        return expressions

    def _visitor_expression(self, type_expr):
        visitor = self._cycles.visitor_for(type_expr)
        if self._values.is_mutex(type_expr):
            self._session.require_helper("__btrc_mutex_arc_type")
        return IRFunctionRef(name=visitor) if visitor else IRLiteral(text="NULL")

    def _take_thread_handle(self, value):
        """Move one addressable thread handle before runtime disposal."""
        slot_name = self._session.fresh_temp("__btrc_thread_slot")
        handle_name = self._session.fresh_temp("__btrc_thread_handle")
        slot = IRVar(name=slot_name)
        handle = IRVar(name=handle_name)
        return IRStmtExpr(
            stmts=[
                IRVarDecl(c_type=CType(text="__btrc_thread_t* volatile*"), name=slot_name),
                IRVarDecl(c_type=CType(text="__btrc_thread_t*"), name=handle_name),
            ],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(left=slot, op="=", right=IRAddressOf(expr=value)),
                    IRBinOp(left=handle, op="=", right=IRDeref(expr=slot)),
                    IRBinOp(left=IRDeref(expr=slot), op="=", right=IRLiteral(text="NULL")),
                    handle,
                ]
            ),
        )

    def _no_op(self):
        return IRCast(target_type=CType(text="void"), expr=IRLiteral(text="0"))


class OwnershipOperandOrder:
    """Compute stabilization pins and concrete temporary value types."""

    def __init__(
        self,
        context: LoweringSession,
        analyzed: AnalyzedProgram,
        values: ManagedValueSemantics,
        types: CTypeLowerer,
        ownership: OwnershipLowerer,
    ) -> None:
        self._session = context
        self._analyzed = analyzed
        self._values = values
        self._types = types
        self._ownership = ownership

    def has_effect(self, node) -> bool:
        """Whether evaluating ``node`` can change a later operand."""
        return self._ownership.has_observable_effect(node)

    def operands_require_order(self, nodes) -> bool:
        """Whether C's unspecified operand order can change semantics."""
        effects = [self.has_effect(node) for node in nodes]
        for left_index, left in enumerate(nodes):
            for right_index in range(left_index + 1, len(nodes)):
                right = nodes[right_index]
                if effects[left_index] and (not self._ownership.reorder_inert(right)):
                    return True
                if effects[right_index] and (not self._ownership.reorder_inert(left)):
                    return True
        return False

    def source_order_pin_flags(self, nodes, type_exprs, owned) -> list[bool]:
        effects = [self.has_effect(node) for node in nodes]
        return [
            bool(
                OwnershipLowerer.borrowed_value_can_be_pinned(nodes[index])
                and (not owned[index])
                and self._values.is_managed(type_exprs[index])
                and any(effects[index + 1 :])
            )
            for index in range(len(nodes))
        ]

    def operand_c_type(self, node, type_expr):
        if isinstance(node, Identifier) and any(node.name in values for values in self._analyzed.enum_table.values()):
            return "int"
        return self._types.render(type_expr)


class OwnershipLowerer:
    """Own ownership lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        index_protocols: IndexedProtocolResolver,
        values: ManagedValueSemantics,
        cycles: CycleMetadata,
        lifetime: ManagedLifetimeLowerer,
        cleanup_scope: CleanupScopeState,
        *,
        program_has_exceptions: bool,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._index_protocols = index_protocols
        self._values = values
        self._cycles = cycles
        self._lifetime = lifetime
        self._cleanup_scope = cleanup_scope
        self.program_has_exceptions = bool(program_has_exceptions)
        self._normalizing_void_main = False
        self._init_ownership_state()

    def plan_release(self, source: object) -> ManagedReleasePlan:
        type_expr = self._session.type_of(source)
        return ManagedReleasePlan(
            source=source,
            type_expr=type_expr,
            managed=self._values.is_managed(type_expr),
        )

    def materialize_release(
        self,
        plan: ManagedReleasePlan,
        lowered: IRExpr,
    ) -> list[IRStmt]:
        if not plan.managed:
            return [IRExprStmt(expr=IRCall(callee="free", args=[lowered]))]
        result = [IRExprStmt(expr=self._lifetime.release_value(lowered, plan.type_expr))]
        flush = self._lifetime.flush_released_values(plan.type_expr)
        if flush is not None:
            result.append(IRExprStmt(expr=flush))
        return result

    def materialize(self, plan, lowered):
        return lowered

    def owns_result(
        self,
        expression,
        *,
        provenance: CallableBodyFacts,
        call_effect: object | None = None,
    ) -> bool:
        """Whether evaluating ``expression`` produces caller-owned +1."""
        if isinstance(expression, NewExpr):
            return self._values.is_managed(self._session.type_of(expression))
        if isinstance(expression, (BraceInitializer, ListLiteral, MapLiteral)):
            result_type = self._session.type_of(expression)
            return bool(result_type and result_type.base in self._analyzed.class_table)
        if isinstance(expression, CastExpr):
            return self._values.is_managed(self._session.type_of(expression)) and self.owns_result(
                expression.expr, provenance=provenance
            )
        if isinstance(expression, FStringLiteral):
            return any(isinstance(part, FStringExpr) for part in expression.parts)
        if isinstance(expression, AssignExpr):
            return self._assignment_owns_result(expression, provenance)
        if isinstance(expression, (FieldAccessExpr, IndexExpr)):
            result_type = self._session.type_of(expression)
            custom_getter = self._custom_getter(expression)
            return bool(
                self._values.is_managed(result_type)
                and (
                    self.projection_is_owned_call(expression)
                    or custom_getter
                    or self.owns_result(expression.obj, provenance=provenance)
                )
            )
        if isinstance(expression, TernaryExpr):
            return self._conditional_result_is_owned(
                expression, (expression.true_expr, expression.false_expr), provenance
            )
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return self._conditional_result_is_owned(expression, (expression.left, expression.right), provenance)
        if isinstance(expression, BinaryExpr):
            result_type = self._session.type_of(expression)
            if self._is_string_concat(expression, result_type):
                return True
            return self._overloaded_result_is_owned(expression, expression.left, expression.op)
        if isinstance(expression, UnaryExpr):
            return self._overloaded_result_is_owned(expression, expression.operand, expression.op, unary=True)
        if not isinstance(expression, CallExpr):
            return False
        result_type = self._session.type_of(expression)
        if not self._values.is_managed(result_type):
            return False
        if self._values.is_string(result_type):
            return self._string_call_owns_result(expression, provenance, call_effect)
        return provenance.call_returns_owned(expression, call_effect)

    def normalize_branch(self, expression, lowered, provenance: CallableBodyFacts):
        """Promote a selected borrowed branch when its conditional yields +1."""
        if isinstance(expression, NullLiteral) or self.owns_result(expression, provenance=provenance):
            return lowered
        type_expr = self._session.type_of(expression)
        if not self._values.is_managed(type_expr):
            return lowered
        from ..nodes import CType, IRBinOp, IRCommaExpr, IRStmtExpr, IRVar, IRVarDecl

        declaration = IRVarDecl(
            c_type=CType(text=self._types.render(type_expr)), name=self._session.fresh_temp("__btrc_promoted_branch")
        )
        self._session.record_declaration(declaration)
        value = IRVar(name=declaration.name)
        return IRStmtExpr(
            stmts=[declaration],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(left=value, op="=", right=lowered),
                    self._lifetime.retain_value(value, type_expr),
                    value,
                ]
            ),
        )

    def projection_is_owned_call(self, expression) -> bool:
        """Whether a projection invokes a managed-return source callable."""
        receiver_type = self._session.type_of(expression.obj)
        if receiver_type is None:
            return False
        if isinstance(expression, IndexExpr):
            return self._index_protocols.class_info(receiver_type, method="get") is not None
        return bool(self._custom_getter(expression))

    def _assignment_owns_result(self, expression: AssignExpr, provenance: CallableBodyFacts) -> bool:
        result_type = self._session.type_of(expression)
        target = expression.target
        rhs_owned = self._virtual_assignment_owns(target, expression.value, provenance)
        return bool(
            self._values.is_managed(result_type)
            and (
                (
                    isinstance(target, (FieldAccessExpr, IndexExpr))
                    and (
                        self.owns_result(target.obj, provenance=provenance)
                        or self._assignment_pins_borrowed_target(target, provenance)
                    )
                )
                or (expression.op == "=" and rhs_owned)
            )
        )

    def _assignment_pins_borrowed_target(self, target, provenance: CallableBodyFacts) -> bool:
        operands = self.assignment_target_operands(target, provenance)
        return bool(self.kept_target_operands(target, operands, provenance))

    def _virtual_assignment_owns(self, target, value, provenance: CallableBodyFacts) -> bool:
        if not self._virtual_assignment_target(target):
            return False
        if self._values.is_managed(self._session.type_of(target)) or self.owns_result(value, provenance=provenance):
            return True
        target_type = self._types.canonical_type(self._session.type_of(target))
        source_type = self._types.canonical_type(self._session.type_of(value))
        return self._values.is_string(target_type) and self._types.has_to_string(source_type)

    def _virtual_assignment_target(self, target) -> bool:
        if isinstance(target, IndexExpr):
            return self._index_protocols.class_info(self._session.type_of(target.obj), method="set") is not None
        if not isinstance(target, FieldAccessExpr):
            return False
        receiver_type = self._session.type_of(target.obj)
        class_info = self._analyzed.class_table.get(receiver_type.base) if receiver_type else None
        prop = class_info.properties.get(target.field) if class_info else None
        if prop is None:
            return False
        return not (
            isinstance(target.obj, SelfExpr)
            and self._session.current_property_backing == target.field
            and StorageModel.property_needs_backing(prop)
        )

    def _conditional_result_is_owned(self, expression, branches, provenance: CallableBodyFacts) -> bool:
        result_type = self._session.type_of(expression)
        branch_ownership = []
        for branch, entry in provenance.conditional_branch_entries(expression):
            with provenance.at_flow(entry):
                branch_ownership.append(self.owns_result(branch, provenance=provenance))
        return bool(
            self._values.is_managed(result_type)
            and any(branch_ownership)
            and all(
                (
                    owned or isinstance(branch, NullLiteral) or self._values.is_managed(self._session.type_of(branch))
                    for branch, owned in zip(branches, branch_ownership)
                )
            )
        )

    def _is_string_concat(self, expression: BinaryExpr, result_type) -> bool:
        if expression.op != "+" or not self._values.is_string(result_type):
            return False
        return self._values.is_string(self._session.type_of(expression.left)) and self._values.is_string(
            self._session.type_of(expression.right)
        )

    def _string_call_owns_result(
        self,
        expression: CallExpr,
        provenance: CallableBodyFacts,
        call_effect: object | None = None,
    ) -> bool:
        if provenance.call_returns_owned(expression, call_effect):
            return True
        callee = expression.callee
        if isinstance(callee, Identifier):
            return callee.name in {"__btrc_str_track", "__btrc_string_adopt", "__btrc_string_alloc"}
        if not isinstance(callee, FieldAccessExpr):
            return False
        receiver_type = self._session.type_of(callee.obj)
        if self._values.is_string(receiver_type):
            from src.compiler.python.analyzer.types import STRING_METHODS

            method = STRING_METHODS.get(callee.field)
            return bool(method and method.tracked)
        if callee.field != "toString" or receiver_type is None:
            return False
        return bool(
            receiver_type.base != "bool"
            and receiver_type.base not in self._analyzed.enum_table
            and (receiver_type.base not in self._analyzed.rich_enum_table)
        )

    def _custom_getter(self, expression):
        if not isinstance(expression, FieldAccessExpr):
            return None
        from src.compiler.python.analyzer.storage import StorageModel

        return StorageModel.custom_property_getter(
            self._analyzed.class_table, self._session.type_of(expression.obj), expression.field
        )

    def _overloaded_result_is_owned(self, expression, operand, operator: str, *, unary: bool = False) -> bool:
        result_type = self._session.type_of(expression)
        expression_type = self._session.type_of(operand)
        if expression_type is None:
            return False
        class_info = self._analyzed.class_table.get(expression_type.base)
        magic = {"+": "__add__", "-": "__sub__", "*": "__mul__", "/": "__div__", "%": "__mod__"}.get(operator)
        if unary:
            magic = "__neg__" if operator == "-" else None
        return bool(
            result_type is not None
            and result_type.base in self._analyzed.class_table
            and (class_info is not None)
            and (magic in class_info.methods)
        )

    def _init_ownership_state(self) -> None:
        self._managed_vars_stack: list[list[ManagedLocal]] = []
        self._session.local_ownership_scopes: list[dict[str, str | None]] = []
        self._local_c_name_scopes: list[dict[str, str]] = []
        self._loop_scope_depths: list[int] = []
        self._session.control_context = []
        self._control_managed_depths: list[int] = []
        self._session.in_try_depth = 0
        self._session.in_trycatch_depth = 0
        self._session.function_declarations = []

    @contextmanager
    def isolated_function_state(self, return_c_type: str, return_type):
        """Isolate lexical ownership state for a lifted function body."""
        owner_state = (
            self._managed_vars_stack,
            self._local_c_name_scopes,
            self._loop_scope_depths,
            self._control_managed_depths,
        )
        session_state = (
            self._session.local_ownership_scopes,
            self._session.control_context,
            self._session.in_try_depth,
            self._session.in_trycatch_depth,
            self._session.function_declarations,
            self._session.current_return_c_type,
            self._session.current_return_type,
            self._session.current_return_owned,
            self._session.owning_overrides,
            self._session.type_overrides,
            self._session.c_array_scopes,
        )
        self._managed_vars_stack = []
        self._local_c_name_scopes = []
        self._loop_scope_depths = []
        self._control_managed_depths = []
        self._session.local_ownership_scopes = []
        self._session.control_context = []
        self._session.in_try_depth = 0
        self._session.in_trycatch_depth = 0
        self._session.function_declarations = []
        self._session.current_return_c_type = return_c_type
        self._session.current_return_type = return_type
        self._session.current_return_owned = True
        self._session.owning_overrides = {}
        self._session.type_overrides = {}
        self._session.c_array_scopes = []
        try:
            with self._cleanup_scope.isolated():
                yield
        finally:
            (
                self._managed_vars_stack,
                self._local_c_name_scopes,
                self._loop_scope_depths,
                self._control_managed_depths,
            ) = owner_state
            (
                self._session.local_ownership_scopes,
                self._session.control_context,
                self._session.in_try_depth,
                self._session.in_trycatch_depth,
                self._session.function_declarations,
                self._session.current_return_c_type,
                self._session.current_return_type,
                self._session.current_return_owned,
                self._session.owning_overrides,
                self._session.type_overrides,
                self._session.c_array_scopes,
            ) = session_state

    def push_control_context(self, kind: str) -> None:
        self._session.control_context.append(kind)
        self._control_managed_depths.append(len(self._managed_vars_stack))
        self._cleanup_scope.push_control_context()

    def pop_control_context(self) -> None:
        if self._session.control_context:
            self._session.control_context.pop()
            self._control_managed_depths.pop()
            self._cleanup_scope.pop_control_context()

    def exited_try_depth(self, targets: set[str]) -> int:
        """Return try frames crossed before the nearest control target."""
        depth = 0
        for kind in reversed(self._session.control_context):
            if kind in targets:
                return depth
            if kind == "try":
                depth += 1
        return 0

    def get_control_managed_vars(self, targets: set[str]) -> list[ManagedLocal]:
        """Return managed locals exited by the nearest control target."""
        for index in range(len(self._session.control_context) - 1, -1, -1):
            if self._session.control_context[index] not in targets:
                continue
            scope_depth = self._control_managed_depths[index]
            result: list[ManagedLocal] = []
            for scope in self._managed_vars_stack[scope_depth:]:
                result.extend(scope)
            return result
        return []

    def push_managed_scope(self) -> None:
        self._managed_vars_stack.append([])

    def pop_managed_scope(self) -> list[ManagedLocal]:
        if self._managed_vars_stack:
            return self._managed_vars_stack.pop()
        return []

    def register_managed_var(
        self,
        var_name: str,
        class_type: str,
        provenance: CallableBodyFacts,
        *,
        cycle_seed: bool,
    ) -> None:
        if self._managed_vars_stack:
            self._managed_vars_stack[-1].append(
                ManagedLocal(
                    var_name,
                    class_type,
                    cycle_seed,
                    c_name=self.source_binding_c_name(var_name, provenance),
                )
            )

    def register_thread_var(self, var_name: str, provenance: CallableBodyFacts) -> None:
        """Register one unique joinable owner for structured scope cleanup."""
        if self._managed_vars_stack:
            self._managed_vars_stack[-1].append(
                ManagedLocal(
                    var_name,
                    "",
                    False,
                    c_name=self.source_binding_c_name(var_name, provenance),
                    cleanup_kind="thread",
                )
            )

    def local_cleanup_kind(self, var_name: str, provenance: CallableBodyFacts) -> str | None:
        c_name = self.source_binding_c_name(var_name, provenance)
        for scope in reversed(self._managed_vars_stack):
            for local in reversed(scope):
                if (local.c_name or local.name) == c_name:
                    return local.cleanup_kind
        return None

    def push_local_ownership_scope(self) -> None:
        self._session.local_ownership_scopes.append({})
        self._local_c_name_scopes.append({})

    def pop_local_ownership_scope(self) -> None:
        if self._session.local_ownership_scopes:
            self._session.local_ownership_scopes.pop()
            self._local_c_name_scopes.pop()

    def next_source_binding_c_name(self, var_name: str, provenance: CallableBodyFacts) -> str:
        """Allocate a C identity without making the source binding visible."""
        c_name = provenance.source_binding_c_name(var_name)
        active_c_names = {active_name for scope in self._local_c_name_scopes for active_name in scope.values()}
        if c_name in active_c_names:
            c_name = self._session.fresh_temp(c_name)
        return c_name

    def declare_local_ownership(
        self,
        var_name: str,
        provenance: CallableBodyFacts,
        class_type: str | None = None,
        *,
        c_name: str | None = None,
    ) -> str:
        if self._session.local_ownership_scopes:
            self._session.local_ownership_scopes[-1][var_name] = class_type
            current_names = self._local_c_name_scopes[-1]
            if var_name not in current_names:
                if c_name is None:
                    c_name = self.next_source_binding_c_name(var_name, provenance)
                current_names[var_name] = c_name
            return current_names[var_name]
        return c_name or self.next_source_binding_c_name(var_name, provenance)

    def source_binding_c_name(self, var_name: str, provenance: CallableBodyFacts) -> str:
        """Return the active declaration-specific C name for a source local."""
        for scope in reversed(self._local_c_name_scopes):
            if var_name in scope:
                return scope[var_name]
        return provenance.source_binding_c_name(var_name)

    def managed_local_type(self, var_name: str) -> str | None:
        for scope in reversed(self._session.local_ownership_scopes):
            if var_name in scope:
                return scope[var_name]
        return None

    def unregister_managed_var(self, var_name: str, provenance: CallableBodyFacts) -> None:
        """Stop automatic destruction after an explicit free/delete."""
        c_name = self.source_binding_c_name(var_name, provenance)
        for scope in self._managed_vars_stack:
            scope[:] = [local for local in scope if (local.c_name or local.name) != c_name]
        for scope in reversed(self._session.local_ownership_scopes):
            if var_name in scope:
                scope[var_name] = None
                break

    def get_all_managed_vars(self) -> list[ManagedLocal]:
        result: list[ManagedLocal] = []
        for scope in self._managed_vars_stack:
            result.extend(scope)
        return result

    def mark_borrowed_cycle_seeds(self) -> None:
        """Invalidate the cycle proof of every live lexical ARC alias."""
        for scope in self._managed_vars_stack:
            for local in scope:
                local.mark_cycle_seed()

    def push_loop_scope(self) -> None:
        self._loop_scope_depths.append(len(self._managed_vars_stack))

    def pop_loop_scope(self) -> None:
        if self._loop_scope_depths:
            self._loop_scope_depths.pop()

    @staticmethod
    def descriptor_symbol(emitted_name: str) -> str:
        """Return the interned descriptor symbol for one concrete C type."""
        return f"__btrc_{emitted_name}_arc_type"

    def arc_header_field(self) -> IRStructField:
        """Return the mandatory first field for a managed representation."""
        self._session.require_helper("__btrc_arc_callback_types")
        self._session.module.runtime_roots.add("__btrc_arc_callback_types")
        return IRStructField(c_type=CType(text="__btrc_arc_header"), name=ARC_HEADER_FIELD)

    @staticmethod
    def arc_header_member(value, member: str):
        """Project one member from a pointer's embedded ARC header."""
        header = IRFieldAccess(obj=value, field=ARC_HEADER_FIELD, arrow=True)
        return IRFieldAccess(obj=header, field=member, arrow=False)

    @staticmethod
    def arc_header_initialization(emitted_name: str, self_name: str = "self"):
        """Initialize refcounts and concrete metadata before user constructor code."""
        self_value = IRVar(name=self_name)
        return [
            IRAssign(target=OwnershipLowerer.arc_header_member(self_value, "rc"), value=IRLiteral(text="1")),
            IRAssign(target=OwnershipLowerer.arc_header_member(self_value, "edge_rc"), value=IRLiteral(text="0")),
            IRAssign(
                target=OwnershipLowerer.arc_header_member(self_value, "live_witness"), value=IRLiteral(text="NULL")
            ),
            IRAssign(
                target=OwnershipLowerer.arc_header_member(self_value, "type"),
                value=OwnershipLowerer.descriptor_pointer(emitted_name),
            ),
            IRAssign(target=OwnershipLowerer.arc_header_member(self_value, "incoming"), value=IRLiteral(text="NULL")),
            IRAssign(
                target=OwnershipLowerer.arc_header_member(self_value, "deferred_next"), value=IRLiteral(text="NULL")
            ),
            IRAssign(target=OwnershipLowerer.arc_header_member(self_value, "suppress_hook"), value=IRLiteral(text="0")),
            IRAssign(
                target=OwnershipLowerer.arc_header_member(self_value, "state"), value=IRVar(name="__BTRC_ARC_LIVE")
            ),
        ]

    @staticmethod
    def descriptor_pointer(emitted_name: str):
        return IRAddressOf(expr=IRVar(name=OwnershipLowerer.descriptor_symbol(emitted_name)))

    def emit_arc_descriptor(self, emitted_name: str, visitor_name: str | None, hook_name: str | None = None) -> None:
        """Emit one process-lifetime descriptor for a concrete managed type."""
        emitted = self._session.arc_descriptor_types
        if emitted_name in emitted:
            return
        emitted.add(emitted_name)
        self._session.require_helper("__btrc_arc_callback_types")
        self._session.module.runtime_roots.add("__btrc_arc_callback_types")
        raise_name = None
        guard_name = None
        if hook_name is not None:
            guard_name = "__btrc_arc_guard_hook"
            raise_name = "__btrc_throw"
            self._session.require_helper(guard_name)
            self._session.require_helper(raise_name)
            declaration = IRFunctionDecl(
                name=hook_name,
                return_type=CType(text="void"),
                params=[IRParam(c_type=CType(text="void*"), name="object")],
                is_static=True,
            )
            if declaration not in self._session.module.function_decls:
                self._session.module.function_decls.append(declaration)
        elif self.program_has_exceptions:
            raise_name = "__btrc_throw"
            self._session.require_helper(raise_name)
        self._session.module.global_decls.append(
            IRGlobalDecl(
                c_type=CType(text="const __btrc_arc_type"),
                name=OwnershipLowerer.descriptor_symbol(emitted_name),
                init=IRInitializerList(
                    elements=[
                        IRFunctionRef(name=visitor_name) if visitor_name is not None else IRLiteral(text="NULL"),
                        IRFunctionRef(name=f"{emitted_name}_destroy"),
                        IRFunctionRef(name=hook_name) if hook_name is not None else IRLiteral(text="NULL"),
                        IRFunctionRef(name=guard_name) if guard_name is not None else IRLiteral(text="NULL"),
                        IRFunctionRef(name=raise_name) if raise_name is not None else IRLiteral(text="NULL"),
                    ]
                ),
            )
        )

    def plan_return(self, node: ReturnStmt, provenance: CallableBodyFacts) -> ReturnPlan:
        """Capture return ownership facts before expression materialization."""
        returned_local = None
        return_type = self._types.canonical_type(self._session.current_return_type)
        if isinstance(node.value, Identifier):
            if self.managed_local_type(node.value.name) is not None:
                returned_local = node.value.name
            if (
                return_type is not None
                and return_type.base == "Thread"
                and self.local_cleanup_kind(node.value.name, provenance) == "thread"
            ):
                returned_local = node.value.name
        return ReturnPlan(
            source=node.value,
            return_type=self._session.current_return_type,
            return_c_type=self._session.current_return_c_type,
            returned_local=returned_local,
        )

    def materialize_return(
        self,
        plan: ReturnPlan,
        value: IRExpr | None,
        provenance: CallableBodyFacts,
        *,
        effective_type: TypeExpr | None = None,
        owned: bool = False,
        converted: bool = False,
    ) -> list[IRStmt]:
        """Materialize a return from a value lowered by the expression owner."""
        if plan.source is None:
            return [
                *self._lifetime.release_scope(self.get_all_managed_vars()),
                *self._emit_return_try_pop(),
                *self._emit_return_cleanup_discard(),
                IRReturn(value=None),
            ]
        if value is None:
            raise ValueError("non-void return materialization requires a value")
        value = self._types.upcast_class_pointer(plan.return_type, effective_type, value)
        managed_value_type = self._values.is_managed(plan.return_type)
        managed_return = managed_value_type and self._session.current_return_owned
        owned_value = bool(managed_return and managed_value_type and owned)
        returned_local = plan.returned_local
        if returned_local is not None and converted:
            returned_local = None
        if returned_local is not None and managed_return:
            owned_value = True
        returned_c_name = self.source_binding_c_name(returned_local, provenance) if returned_local is not None else None
        release_stmts = self._lifetime.release_scope(
            [local for local in self.get_all_managed_vars() if (local.c_name or local.name) != returned_c_name]
        )
        promote_borrowed = managed_return and (not owned_value)
        try_pop = self._emit_return_try_pop()
        cleanup_discard = self._emit_return_cleanup_discard()
        if not release_stmts and (not try_pop) and (not cleanup_discard) and (not promote_borrowed):
            return [IRReturn(value=self._maybe_launder_return(value))]
        temporary = IRVarDecl(
            c_type=CType(text=plan.return_c_type), name=self._session.fresh_temp("__btrc_ret"), init=value
        )
        result = IRVar(name=temporary.name)
        promote = []
        if promote_borrowed:
            promote.append(IRExprStmt(expr=self._lifetime.retain_value(result, plan.return_type)))
        prefix = [temporary, *promote]
        if managed_return and returned_local is None:
            runtime_type = self._values.runtime_name(plan.return_type)
            self._lifetime.register_named_cleanup(temporary.name, runtime_type, prefix)
            cleanup_discard = self._emit_return_cleanup_discard()
        return [*prefix, *release_stmts, *try_pop, *cleanup_discard, IRReturn(value=self._maybe_launder_return(result))]

    def _emit_return_try_pop(self) -> list[IRStmt]:
        """Discard cleanups and pop try levels bypassed by a return."""
        return self._emit_try_pop(self._session.in_try_depth)

    def _emit_return_cleanup_discard(self) -> list[IRStmt]:
        """Forget this function's registered slots after ordinary ARC release."""
        return self._cleanup_scope.exit(self._cleanup_scope.return_marker())

    def _emit_try_pop(self, depth: int) -> list[IRStmt]:
        """Discard cleanup registrations and pop ``depth`` active try frames."""
        if depth <= 0:
            return []
        stmts: list[IRStmt] = []
        if self._session.uses_any_helper({"__btrc_register_cleanup", "__btrc_register_direct_cleanup"}):
            self._session.require_helper("__btrc_discard_cleanups")
            level = IRVar(name="__btrc_try_top")
            if depth > 1:
                level = IRBinOp(left=level, op="-", right=IRLiteral(text=str(depth - 1)))
            stmts.append(
                IRExprStmt(
                    expr=IRCall(callee="__btrc_discard_cleanups", args=[level], helper_ref="__btrc_discard_cleanups")
                )
            )
        stmts.extend(OwnershipLowerer._pop_try_frames(depth))
        return stmts

    def materialize_try_exit(self, depth: int) -> list[IRStmt]:
        """Materialize cleanup and try-frame exit for an outward jump."""
        return self._emit_try_pop(depth)

    @staticmethod
    def _pop_try_frames(depth: int) -> list[IRStmt]:
        if depth <= 0:
            return []
        top = IRVar(name="__btrc_try_top")
        expression = (
            IRUnaryOp(op="--", operand=top, prefix=False)
            if depth == 1
            else IRBinOp(left=top, op="-=", right=IRLiteral(text=str(depth)))
        )
        return [IRExprStmt(expr=expression)]

    def _maybe_launder_return(self, value):
        """Prevent setjmp branch folding for managed returns inside try/catch."""
        if self._session.in_trycatch_depth <= 0:
            return value
        return_type = self._session.current_return_type
        if not self._values.is_managed(return_type):
            return value
        self._session.require_helper("__btrc_launder")
        laundered = IRCall(callee="__btrc_launder", args=[value], helper_ref="__btrc_launder")
        return IRCast(target_type=CType(text=self._session.current_return_c_type), expr=laundered)

    def assignment_target_operands(self, target, provenance: CallableBodyFacts) -> list:
        """Collect target dependencies in source evaluation order.

        A receiver selected for stabilization is kept as one operand.  Otherwise
        raw field/index projections are followed until a receiver whose lifetime
        matters is reached.  This preserves lvalue shape while allowing the outer
        ownership boundary to evaluate each dependency exactly once.
        """
        if isinstance(target, FieldAccessExpr):
            return self._receiver_operands(target.obj, provenance)
        if isinstance(target, IndexExpr):
            return [*self._receiver_operands(target.obj, provenance), target.index]
        return [target]

    def borrowed_projection_owner_operands(
        self,
        expression,
        provenance: CallableBodyFacts,
        *,
        overridden_ids: frozenset[int] = frozenset(),
    ) -> list:
        """Return owned receivers backing an otherwise borrowed projection."""
        if self._overridden(expression, overridden_ids) or self.owns_result(expression, provenance=provenance):
            return []
        if not isinstance(expression, (FieldAccessExpr, IndexExpr)):
            return []
        receiver = expression.obj
        if not self._overridden(receiver, overridden_ids) and self.owns_result(receiver, provenance=provenance):
            return [receiver]
        return self.borrowed_projection_owner_operands(receiver, provenance, overridden_ids=overridden_ids)

    def kept_target_operands(self, target, operands, provenance: CallableBodyFacts) -> tuple:
        """Return borrowed managed operands that must outlive target evaluation."""
        if not isinstance(target, (FieldAccessExpr, IndexExpr)):
            return ()
        return tuple(
            operand
            for operand in operands
            if not isinstance(operand, (SelfExpr, SuperExpr))
            and self._values.is_managed(self._session.type_of(operand))
            and (not self.owns_result(operand, provenance=provenance))
        )

    def property_projection(self, target) -> bool:
        """Whether a field-shaped expression is implemented by a getter."""
        if not isinstance(target, FieldAccessExpr):
            return False
        receiver_type = self._session.type_of(target.obj)
        if receiver_type is None:
            return False
        class_info = self._analyzed.class_table.get(receiver_type.base)
        return bool(class_info is not None and target.field in class_info.properties)

    def _receiver_operands(self, receiver, provenance: CallableBodyFacts) -> list:
        if (
            self.owns_result(receiver, provenance=provenance)
            or self._values.is_managed(self._session.type_of(receiver))
            or self.property_projection(receiver)
        ):
            return [receiver]
        return self.assignment_target_operands(receiver, provenance)

    def _overridden(self, expression, overridden_ids: frozenset[int]) -> bool:
        return bool(id(expression) in overridden_ids or id(expression) in self._session.owning_overrides)

    @staticmethod
    def borrowed_value_can_be_pinned(node) -> bool:
        """Whether a borrowed expression may be retained for local stabilization."""
        return not isinstance(node, (SelfExpr, SuperExpr))

    def has_observable_effect(self, node) -> bool:
        """Whether evaluating ``node`` can change a later operand's value."""
        if node is None:
            return False
        if isinstance(node, Identifier):
            if self._enum_constant_identifier(node):
                return False
            return self._session.type_of(node) is None
        if isinstance(
            node,
            (
                AssignExpr,
                BraceInitializer,
                CallExpr,
                FStringLiteral,
                LambdaExpr,
                ListLiteral,
                MapLiteral,
                NewExpr,
                SpawnExpr,
            ),
        ):
            return True
        if isinstance(node, UnaryExpr):
            return node.op in {"++", "--"} or self.has_observable_effect(node.operand)
        if isinstance(node, BinaryExpr):
            return self.has_observable_effect(node.left) or self.has_observable_effect(node.right)
        if isinstance(node, TernaryExpr):
            return any(self.has_observable_effect(child) for child in (node.condition, node.true_expr, node.false_expr))
        if isinstance(node, CastExpr):
            return self.has_observable_effect(node.expr)
        if isinstance(node, TupleLiteral):
            return any(self.has_observable_effect(child) for child in node.elements)
        if isinstance(node, FieldAccessExpr):
            if node.optional or self.has_observable_effect(node.obj):
                return True
            receiver_type = self._canonical_receiver_type(self._session.type_of(node.obj))
            class_info = self._analyzed.class_table.get(receiver_type.base) if receiver_type is not None else None
            return bool(class_info is not None and node.field in class_info.properties)
        if isinstance(node, IndexExpr):
            if self.has_observable_effect(node.obj):
                return True
            if self.has_observable_effect(node.index):
                return True
            receiver_type = self._canonical_receiver_type(self._session.type_of(node.obj))
            return bool(receiver_type is not None and self._index_protocols.class_info(receiver_type, method="get"))
        return False

    def reorder_inert(self, node) -> bool:
        """Whether evaluating ``node`` cannot observe or change sibling state."""
        if isinstance(node, (BoolLiteral, CharLiteral, FloatLiteral, IntLiteral, NullLiteral, StringLiteral)):
            return True
        if isinstance(node, Identifier):
            return self._enum_constant_identifier(node)
        if isinstance(node, CastExpr):
            return self.reorder_inert(node.expr)
        if isinstance(node, SizeofExpr):
            return True
        if isinstance(node, UnaryExpr) and node.op in {"+", "-", "!", "~"}:
            return self.reorder_inert(node.operand)
        return False

    def _canonical_receiver_type(self, type_expr):
        return self._types.canonical_type(type_expr)

    def _enum_constant_identifier(self, node) -> bool:
        enum_table = self._analyzed.enum_table
        return any(node.name in values for values in enum_table.values())

    @staticmethod
    def reject_opaque_ordering(node, context: str, *, typed_declaration: bool = False) -> None:
        """Reject an opaque C value that cannot be sequenced without guessing its type."""
        remedy = "cast it explicitly"
        if typed_declaration:
            remedy += " or provide a typed declaration"
        raise CodegenError(
            f"opaque C operand at {node.line}:{node.col} precedes an ordered sibling in {context}; {remedy}"
        )

    def materialize_discarded_value(
        self,
        value: IRExpr,
        value_type: TypeExpr,
    ) -> list[IRStmt]:
        """Release one caller-owned result discarded by a statement."""
        temporary = IRVarDecl(
            c_type=CType(text=self._types.render(value_type)),
            name=self._session.fresh_temp("__btrc_discarded"),
            init=value,
        )
        self._session.record_declaration(temporary)
        target = IRVar(name=temporary.name)
        expressions = [self._lifetime.release_value(target, value_type)]
        flush = self._lifetime.poll_release_batch(type_exprs=[value_type] if self._values.is_arc(value_type) else [])
        if flush is not None:
            expressions.append(flush)
        return [
            temporary,
            IRExprStmt(expr=IRCommaExpr(expressions=expressions)),
        ]
