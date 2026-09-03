"""Managed ownership, borrows, cycles, and raw projections."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import TYPE_CHECKING

from src.compiler.python.abi.declarations import ALIAS_EXACT, RETURN_ALIAS
from src.compiler.python.abi.hosted import HOSTED_ABI
from src.compiler.python.analyzer.program import DeclarationIndex
from src.compiler.python.frontend.sources import CompilerStdlibSource
from src.compiler.python.syntax.ast.generated import (
    AssignExpr,
    BinaryExpr,
    BraceInitializer,
    CallExpr,
    CastExpr,
    DeleteStmt,
    FieldAccessExpr,
    FStringExpr,
    FStringLiteral,
    Identifier,
    IndexExpr,
    KeepStmt,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    NullLiteral,
    ReleaseStmt,
    ReturnStmt,
    SelfExpr,
    SpawnExpr,
    StringLiteral,
    SuperExpr,
    TernaryExpr,
    ThrowStmt,
    TupleLiteral,
    UnaryExpr,
    VarDeclStmt,
)

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalysisSession
    from src.compiler.python.analyzer.storage import StorageModel
    from src.compiler.python.analyzer.types import TypeSystem


class CallableValueSemantics:
    """Classify callable values that require a receiver or closure environment."""

    def __init__(self, session: AnalysisSession, index: DeclarationIndex, types: TypeSystem) -> None:
        self.session = session
        self.index = index
        self.types = types

    def type_of(self, expression):
        return self.session.node_types.get(id(expression))

    def _canonicalize(self, type_expr):
        return self.types.canonical_type(type_expr)

    def _identifier_is_local(self, identifier: Identifier) -> bool:
        return self.session.scope.lookup(identifier.name) is not None

    def _identifier_is_storage(self, identifier: Identifier) -> bool:
        symbol = self.session.scope.lookup(identifier.name)
        return bool(symbol is not None and symbol.kind != "function")

    def _identifier_requires_environment(self, identifier: Identifier) -> bool:
        symbol = self.session.scope.lookup(identifier.name)
        return bool(symbol is not None and symbol.captures_environment)

    def requires_environment(self, expression: object | None) -> bool:
        """Whether ``expression`` cannot be represented by a bare ``__fn_ptr``."""
        if isinstance(expression, LambdaExpr):
            return bool(expression.captures)
        if isinstance(expression, Identifier):
            return self._identifier_requires_environment(expression)
        if isinstance(expression, FieldAccessExpr):
            return self._is_bound_instance_method(expression)
        if isinstance(expression, CastExpr):
            return self.requires_environment(expression.expr)
        if isinstance(expression, UnaryExpr) and expression.op in {"&", "*"}:
            return self.requires_environment(expression.operand)
        if isinstance(expression, AssignExpr):
            return self.requires_environment(expression.value)
        if isinstance(expression, TernaryExpr):
            return bool(
                self.requires_environment(expression.true_expr) or self.requires_environment(expression.false_expr)
            )
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return bool(self.requires_environment(expression.left) or self.requires_environment(expression.right))
        return False

    def contains_environment(self, expected_type: object | None, value: object | None) -> bool:
        """Whether a contextual callable slot loses required runtime state."""
        if value is None:
            return False
        expected = self._canonicalize(expected_type)
        if expected is None:
            return self.requires_environment(value)
        if self.is_callable(expected):
            return self.requires_environment(value)
        slots = self.literal_slots(expected, value)
        if slots is not None:
            return any((self.contains_environment(slot_type, element) for slot_type, element in slots))
        return self.requires_environment(value)

    def literal_slots(self, expected_type: object, value: object):
        """Return contextual aggregate slots, or ``None`` for a scalar value."""
        expected = self._canonicalize(expected_type)
        if expected is None:
            return None
        if isinstance(value, (BraceInitializer, ListLiteral)):
            if expected.is_array:
                element_type = self.types.strip_outer_storage(expected, array=True)
                return ((element_type, element) for element in value.elements)
            if expected.base in {"Array", "List", "Set", "Vector"} and len(expected.generic_args) == 1:
                return ((expected.generic_args[0], element) for element in value.elements)
            if expected.base == "Tuple":
                return zip(expected.generic_args, value.elements)
            declaration = self.struct_declaration(expected)
            if declaration is not None:
                return zip((field.type for field in declaration.fields), value.elements)
        if isinstance(value, TupleLiteral) and expected.base == "Tuple":
            return zip(expected.generic_args, value.elements)
        if isinstance(value, MapLiteral) and expected.base == "Map" and (len(expected.generic_args) == 2):
            key_type, value_type = expected.generic_args
            return (slot for entry in value.entries for slot in ((key_type, entry.key), (value_type, entry.value)))
        return None

    def struct_declaration(self, expected_type: object):
        """Return a complete by-value struct declaration for ``expected_type``."""
        expected = self._canonicalize(expected_type)
        if expected is None or expected.pointer_depth > 0:
            return None
        declaration = self.index.struct_table.get(expected.base.removeprefix("struct "))
        if declaration is None or declaration.is_forward:
            return None
        return declaration

    def is_callable(self, type_expr: object | None) -> bool:
        """Whether a type is one scalar bare function-pointer value."""
        resolved = self._canonicalize(type_expr)
        return bool(
            resolved is not None
            and resolved.base in {"__fn_ptr", "__realtime_fn_ptr"}
            and (resolved.pointer_depth == 0)
            and (not resolved.is_array)
        )

    def is_storage_expression(self, expression: object) -> bool:
        if isinstance(expression, Identifier):
            return self._identifier_is_storage(expression)
        if isinstance(expression, (FieldAccessExpr, IndexExpr)):
            return True
        return bool(isinstance(expression, UnaryExpr) and expression.op == "*")

    def _is_bound_instance_method(self, expression: FieldAccessExpr) -> bool:
        receiver = expression.obj
        if isinstance(receiver, Identifier) and (not self._identifier_is_local(receiver)):
            static_owner = self.index.class_table.get(receiver.name)
            if static_owner is not None:
                method = static_owner.methods.get(expression.field)
                return bool(method is not None and method.access != "class")
        receiver_type = self._canonicalize(self.type_of(receiver))
        if receiver_type is None:
            return False
        class_info = self.index.class_table.get(receiver_type.base)
        if class_info is not None:
            if expression.field in class_info.fields or expression.field in class_info.properties:
                return False
            method = class_info.methods.get(expression.field)
            if method is not None:
                return method.access != "class"
        interface_info = self.index.interface_table.get(receiver_type.base)
        if interface_info is not None and expression.field in interface_info.methods:
            return True
        return bool(
            (receiver_type.base == "Thread" and expression.field == "join")
            or (receiver_type.base == "Mutex" and expression.field in {"get", "set", "destroy"})
            or receiver_type.base == "string"
        )


@dataclass(frozen=True)
class RawProjectionLeaf:
    """A field/index projection that produces, or is addressed as, a raw view."""

    expression: object
    direct_storage: bool = False


@dataclass(frozen=True)
class RawProjectionBranch:
    """One lazily selected arm of a conditional carrier."""

    label: str
    expression: object
    carrier: RawProjectionCarrier | None


@dataclass(frozen=True)
class RawProjectionChoice:
    """A carrier whose backing storage depends on a runtime branch."""

    expression: object
    branches: tuple[RawProjectionBranch, ...]


@dataclass(frozen=True)
class ConsumptionArgumentPlan:
    """Source arguments paired with the parameters they bind for ownership policy."""

    arguments: tuple[object, ...]
    bindings: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class MutexDestroyReceiverPlan:
    """Already-analyzed receiver facts needed by Mutex ownership policy."""

    standalone: bool
    optional: bool
    indirect: bool
    stable_storage: bool
    mutable: bool


_RUNTIME_COLLECTION_BASES = frozenset({"Array", "List", "Map", "Set", "Vector"})
_NON_CARRYING_BINARY_OPS = {"==", "!=", "<", "<=", ">", ">=", "&&", "||"}
_LOCATION_FIELDS = frozenset({"line", "col", "source_file"})
_MANAGED_RUNTIME_BASES = frozenset({"string", "Mutex", "Thread", "Vector", "List", "Map", "Set", "Array"})
_NON_CARRYING_BINARY_OPS = frozenset({"==", "!=", "<", "<=", ">", ">=", "&&", "||"})
_CONDITIONAL_STORAGE_ERROR = "Conditional raw projection call arguments require branch-local backing storage"
RawProjectionCarrier = RawProjectionLeaf | RawProjectionChoice


class OwnershipAnalyzer:
    """Managed ownership, borrows, cycles, and raw projections."""

    def __init__(
        self,
        session: AnalysisSession,
        index: DeclarationIndex,
        types: TypeSystem,
        storage: StorageModel,
        callable_values: CallableValueSemantics,
    ) -> None:
        self.session = session
        self.index = index
        self.storage = storage
        self.types = types
        self._callable_values = callable_values
        self._raw_borrow_proof_local_names: frozenset[str] | None = None
        self._raw_borrow_effect_cache: dict[tuple[int, int, str | None], bool] = {}
        self._raw_borrow_effect_visiting: set[tuple[int, int, str | None]] = set()
        self._raw_borrow_owner_cache: dict[int, object] | None = None

    def begin(self) -> None:
        """Reset the ownership facts owned by one analysis invocation."""
        self._raw_borrow_proof_local_names = None
        self._raw_borrow_effect_cache.clear()
        self._raw_borrow_effect_visiting.clear()
        self._raw_borrow_owner_cache = None

    def type_of(self, expression):
        """Read a type fact produced by ExpressionAnalyzer."""
        return self.session.node_types.get(id(expression))

    def callable_value_requires_environment(self, expression: object | None) -> bool:
        """Whether a callable value requires a receiver or closure environment."""
        return self._callable_values.requires_environment(expression)

    def validate_callable_storage(self, type_expr, initializer, explicit_type: bool, line: int, col: int) -> bool:
        """Validate one callable-bearing storage initialization."""
        allow_direct_local = not explicit_type and isinstance(initializer, LambdaExpr)
        return self.validate_callable_value(type_expr, initializer, line, col, allow_direct_local=allow_direct_local)

    def validate_environment_callable_reassignment(self, expression) -> bool:
        """Reject mutation of a local whose closure environment replaced its slot."""
        if expression.op != "=" or not isinstance(expression.target, Identifier):
            return False
        symbol = self.session.scope.lookup(expression.target.name)
        if symbol is None or not symbol.captures_environment:
            return False
        self.session.error(
            "An environment-bearing callable local cannot be reassigned; closure values are not yet a tagged runtime representation",
            expression.line,
            expression.col,
        )
        return True

    def validate_callable_value(
        self, expected, value, line: int, col: int, *, allow_direct_local: bool = False
    ) -> bool:
        """Reject closure or managed-return callable ABI erasure at a value boundary."""
        if self._reject_unproven_realtime_function(expected, value, line, col):
            return True
        if allow_direct_local and isinstance(value, LambdaExpr):
            return False
        if self._callable_values.contains_environment(expected, value):
            self.session.error(
                "A capturing lambda or other environment-requiring callable value cannot escape through a bare __fn_ptr; a tagged closure representation is required",
                line,
                col,
            )
            return True
        if not self._managed_callable_value_is_erased(expected, value):
            return False
        self.session.error(
            "Managed-return callable cannot cross an erased or opaque value boundary; preserve its typed __fn_ptr ownership ABI",
            line,
            col,
        )
        return True

    def _reject_unproven_realtime_function(self, expected, value, line: int, col: int) -> bool:
        """Keep RealtimeFunction construction at direct proven roots or exact copies."""
        canonical = self.types.canonical_type(expected)
        if canonical is None:
            return False
        slots = self._callable_values.literal_slots(canonical, value)
        if slots is not None:
            rejected = False
            for slot_type, element in slots:
                rejected = self._reject_unproven_realtime_function(
                    slot_type,
                    element,
                    getattr(element, "line", line),
                    getattr(element, "col", col),
                ) or rejected
            return rejected
        if canonical.base != "__realtime_fn_ptr" or canonical.pointer_depth != 0 or canonical.is_array:
            return False
        actual = self.types.canonical_type(self.type_of(value))
        exact_copy = bool(
            actual is not None
            and actual.base == "__realtime_fn_ptr"
            and self.types.types_compatible(canonical, actual)
            and not isinstance(value, CastExpr)
        )
        direct_declaration = self.index.function_table.get(value.name) if isinstance(value, Identifier) else None
        symbol = self.session.scope.lookup(value.name) if isinstance(value, Identifier) else None
        direct_root = bool(
            direct_declaration is not None
            and (symbol is None or symbol.kind == "function")
            and direct_declaration.is_realtime
            and self.types.types_compatible(canonical, self.types.function_value_type(direct_declaration))
        )
        if exact_copy or direct_root:
            return False
        self.session.error(
            "RealtimeFunction value must be a direct named @realtime function or an exact RealtimeFunction copy",
            getattr(value, "line", line),
            getattr(value, "col", col),
        )
        return True

    def addresses_callable_storage(self, expression: object | None) -> bool:
        """Whether taking this address exposes managed-return callable storage."""
        return bool(
            expression is not None
            and self._callable_values.is_storage_expression(expression)
            and self.is_managed_return_callable_type(self.types.canonical_type(self.type_of(expression)))
        )

    def is_managed_return_callable_type(self, type_expr) -> bool:
        """Whether a callable's return value crosses the managed ownership ABI."""
        signature = self.types.function_pointer_signature(type_expr)
        return bool(signature and self.is_managed_result_type(signature[0]))

    def _managed_callable_value_is_erased(self, expected, value) -> bool:
        addressed = value
        while isinstance(addressed, CastExpr):
            addressed = addressed.expr
        if (
            isinstance(addressed, UnaryExpr)
            and addressed.op == "&"
            and self.addresses_callable_storage(addressed.operand)
        ):
            return False
        return self._erases_managed_callable_value(expected, value)

    def _erases_managed_callable_value(self, expected, value) -> bool:
        if value is None:
            return False
        expected = self.types.canonical_type(expected)
        if expected is not None and expected.base == "bool" and expected.pointer_depth == 0:
            return False
        if expected is not None and self.is_managed_return_callable_type(expected):
            return False
        slots = self._callable_values.literal_slots(expected, value) if expected is not None else None
        if slots is not None:
            return any(self._erases_managed_callable_value(slot_type, element) for slot_type, element in slots)
        return self._contains_managed_callable_value(value)

    def _contains_managed_callable_value(self, expression) -> bool:
        if expression is None:
            return False
        if self.is_managed_return_callable_type(self.types.canonical_type(self.type_of(expression))):
            return True
        if isinstance(expression, CastExpr):
            return self._contains_managed_callable_value(expression.expr)
        if isinstance(expression, UnaryExpr) and expression.op in {"&", "*"}:
            return self._contains_managed_callable_value(expression.operand)
        if isinstance(expression, AssignExpr):
            return self._contains_managed_callable_value(expression.value)
        if isinstance(expression, TernaryExpr):
            return self._contains_managed_callable_value(expression.true_expr) or self._contains_managed_callable_value(
                expression.false_expr
            )
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return self._contains_managed_callable_value(expression.left) or self._contains_managed_callable_value(
                expression.right
            )
        if isinstance(expression, (BraceInitializer, ListLiteral, TupleLiteral)):
            return any(self._contains_managed_callable_value(element) for element in expression.elements)
        if isinstance(expression, MapLiteral):
            return any(
                self._contains_managed_callable_value(entry.key) or self._contains_managed_callable_value(entry.value)
                for entry in expression.entries
            )
        return False

    def hosted_call_bypasses_source_definition(self, call) -> bool:
        """Whether canonical stdlib code must bind a hosted ABI symbol."""
        if not isinstance(call.callee, Identifier):
            return False
        return self.hosted_name_bypasses_source_definition(call.callee.name)

    def hosted_name_bypasses_source_definition(self, name: str) -> bool:
        declaration = self.index.function_table.get(name)
        if declaration is None or declaration.body is None or not HOSTED_ABI.owned_name(name):
            return False
        return CompilerStdlibSource.authenticated(self.session.current_source_file) and (
            not CompilerStdlibSource.authenticated(getattr(declaration, "source_file", None))
        )

    def hosted_call_uses_owned_symbol(self, call, *, local_names=None) -> bool:
        if not isinstance(call.callee, Identifier):
            return False
        return self.hosted_name_uses_owned_symbol(call.callee.name, local_names=local_names)

    def hosted_name_uses_owned_symbol(self, name: str, *, local_names=None) -> bool:
        if not HOSTED_ABI.owned_name(name):
            return False
        if local_names is None:
            symbol = self.session.scope.lookup(name)
            if symbol is not None and symbol.kind != "function":
                return False
        elif name in local_names:
            return False
        declaration = self.index.function_table.get(name)
        return bool(
            declaration is None or declaration.body is None or self.hosted_name_bypasses_source_definition(name)
        )

    def hosted_function_value_uses_owned_symbol(self, name: str) -> bool:
        return HOSTED_ABI.function_owned_name(name) and self.hosted_name_uses_owned_symbol(name)

    def validate_consuming_arguments(self, declaration, plan: ConsumptionArgumentPlan, label) -> None:
        transferred = self.owned_transfer_param_indices(declaration)
        if not transferred:
            return
        supplied = set()
        for parameter_index, argument_index in plan.bindings:
            supplied.add(parameter_index)
            if parameter_index not in transferred or argument_index >= len(plan.arguments):
                continue
            argument = plan.arguments[argument_index]
            if not self.expression_produces_owned_result(argument):
                self.session.error(
                    f"Argument to consuming parameter '{declaration.params[parameter_index].name}' of '{label}()' must be a fresh caller-owned managed value",
                    getattr(argument, "line", 0),
                    getattr(argument, "col", 0),
                )
        for parameter_index in transferred - supplied:
            parameter = declaration.params[parameter_index]
            if parameter.default is None or not self.expression_produces_owned_result(parameter.default):
                self.session.error(
                    f"Default for consuming parameter '{parameter.name}' of '{label}()' must produce a fresh managed value",
                    parameter.line,
                    parameter.col,
                )

    def _runtime_managed_names(self, type_expr) -> set[str]:
        if type_expr is None or type_expr.is_array or type_expr.pointer_depth > 1:
            return set()
        names = {name for name in self.index.class_table if self.types.is_subclass(name, type_expr.base)}
        for argument in type_expr.generic_args:
            names.update(self._runtime_managed_names(argument))
        return names

    def compute_cyclable_flags(self):
        """Mark classes that can participate in reference cycles.

        A class is cyclable iff it can reach *itself* by following class-typed
        field references (directly via a self field, or transitively through a
        chain of classes that loops back). That, and only that, is what lets a
        live instance sit in a retain cycle. Visitor emission is a separate,
        exact-layout question: acyclic owners still need visitors so a collector
        can traverse through them.

        Note this is NOT the same as "references a cyclable class": a class that
        merely points *into* someone else's cycle (e.g. ``D`` with a field of
        cyclable type ``C`` where nothing points back to ``D``) is never itself
        part of a cycle and must stay non-cyclable. The per-class reachability
        search below already computes the transitive closure, so a single pass
        is exhaustive — no outer fixed-point iteration is needed.
        """
        refs: dict[str, set[str]] = {}
        for name, ci in self.index.class_table.items():
            field_types: set[str] = set()
            for _storage_name, fd in ci.instance_storage:
                field_types.update(self._runtime_managed_names(fd.type))
            refs[name] = field_types
        for name in refs:
            visited: set[str] = set()
            stack = list(refs.get(name, set()))
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                if cur == name:
                    self.index.class_table[name].is_cyclable = True
                    break
                stack.extend(refs.get(cur, set()))

    def validate_generic_type_facts(self) -> None:
        """Validate resolved specialization types discovered by GenericAnalyzer."""
        for type_expr, line, col in self.session.generic_resolved_type_facts:
            self._validate_mutex_payloads_in_type(type_expr, line=line, col=col)

    def expression_produces_owned_result(self, expression) -> bool:
        result = self.types.canonical_type(self.type_of(expression))
        managed = self.is_managed_result_type(result)
        if isinstance(expression, (NewExpr, BraceInitializer, ListLiteral, MapLiteral)):
            return managed
        if isinstance(expression, CastExpr):
            return managed and self.expression_produces_owned_result(expression.expr)
        if isinstance(expression, FStringLiteral):
            return any(isinstance(part, FStringExpr) for part in expression.parts)
        if isinstance(expression, AssignExpr):
            target = expression.target
            owned_receiver = isinstance(target, (FieldAccessExpr, IndexExpr)) and self.expression_produces_owned_result(
                target.obj
            )
            owned_value = (
                expression.op == "="
                and self.storage.is_virtual_projection(target)
                and (
                    managed
                    or self.expression_produces_owned_result(expression.value)
                    or self.types.requires_string_conversion(result, self.type_of(expression.value))
                )
            )
            return managed and (owned_receiver or owned_value)
        if isinstance(expression, (FieldAccessExpr, IndexExpr)):
            if not managed:
                return False
            if self.expression_produces_owned_result(expression.obj):
                return True
            if isinstance(expression, FieldAccessExpr):
                return self.storage.custom_property_getter(
                    self.index.class_table,
                    self.types.canonical_type(self.type_of(expression.obj)),
                    expression.field,
                ) and (not isinstance(expression.obj, (SelfExpr, SuperExpr)))
            if not isinstance(expression, IndexExpr):
                return False
            receiver = self.types.canonical_type(self.type_of(expression.obj))
            protocol = self.types.resolve_index_protocol(
                receiver, active_type_params=self.storage.active_type_parameters()
            )
            return bool(protocol and protocol.getter is not None)
        if isinstance(expression, TernaryExpr):
            return self._conditional_produces_owned_result(result, (expression.true_expr, expression.false_expr))
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return self._conditional_produces_owned_result(result, (expression.left, expression.right))
        if isinstance(expression, BinaryExpr):
            if self._string_concat_produces_owned_result(expression, result):
                return True
            return self._overload_produces_owned_result(expression.left, expression.op, result)
        if isinstance(expression, UnaryExpr):
            return self._overload_produces_owned_result(
                expression.operand, "__neg__" if expression.op == "-" else "", result, magic_is_resolved=True
            )
        if not isinstance(expression, CallExpr) or not managed:
            return False
        if result.base == "string":
            return self._string_call_produces_owned_result(expression)
        return self._known_language_call(expression)

    def is_managed_result_type(self, type_expr) -> bool:
        return self.storage.is_managed_value_type(type_expr)

    def _conditional_produces_owned_result(self, result, branches) -> bool:
        if not self.is_managed_result_type(result):
            return False
        if not any(self.expression_produces_owned_result(item) for item in branches):
            return False
        return all(self._ownership_branch_is_promotable(item) for item in branches)

    def _ownership_branch_is_promotable(self, expression) -> bool:
        if isinstance(expression, NullLiteral):
            return True
        if self.expression_produces_owned_result(expression):
            return True
        return self.is_managed_result_type(self.types.canonical_type(self.type_of(expression)))

    def _string_concat_produces_owned_result(self, expression, result) -> bool:
        if expression.op != "+" or result is None or result.base != "string":
            return False
        left = self.types.canonical_type(self.type_of(expression.left))
        right = self.types.canonical_type(self.type_of(expression.right))
        return bool(left and right and (left.base == "string") and (right.base == "string"))

    def _overload_produces_owned_result(self, operand, operator, result, *, magic_is_resolved=False) -> bool:
        if not self.is_managed_result_type(result) or result.base == "string":
            return False
        magic = (
            operator
            if magic_is_resolved
            else {"+": "__add__", "-": "__sub__", "*": "__mul__", "/": "__div__", "%": "__mod__"}.get(operator, "")
        )
        operand_type = self.types.canonical_type(self.type_of(operand))
        class_info = self.index.class_table.get(operand_type.base) if operand_type else None
        return bool(magic and class_info and (magic in class_info.methods))

    def _known_language_call(self, expression) -> bool:
        callee = expression.callee
        if isinstance(callee, Identifier):
            symbol = self.session.scope.lookup(callee.name)
            if symbol is not None and symbol.kind != "function":
                return False
            return (
                callee.name == "Mutex"
                or callee.name in self.index.class_table
                or callee.name in self.index.function_table
            )
        if not isinstance(callee, FieldAccessExpr):
            return False
        if isinstance(callee.obj, Identifier):
            owner = (
                None
                if self.session.scope.lookup(callee.obj.name) is not None
                else self.index.class_table.get(callee.obj.name)
            )
            if owner is not None and callee.field in owner.methods:
                return True
        receiver = self.types.canonical_type(self.type_of(callee.obj))
        if receiver is None:
            return False
        if receiver.base == "Thread" and callee.field == "join":
            return True
        if receiver.base == "Mutex" and callee.field == "get":
            return True
        owner = self.index.class_table.get(receiver.base)
        if owner is not None and callee.field in owner.methods:
            return True
        interface = self.index.interface_table.get(receiver.base)
        return bool(interface is not None and callee.field in interface.methods)

    def _string_call_produces_owned_result(self, expression) -> bool:
        if self._known_language_call(expression):
            return True
        callee = expression.callee
        if isinstance(callee, Identifier):
            return callee.name in {"__btrc_str_track", "__btrc_string_adopt", "__btrc_string_alloc"}
        if not isinstance(callee, FieldAccessExpr):
            return False
        receiver = self.types.canonical_type(self.type_of(callee.obj))
        if receiver is not None and receiver.base == "string":
            from src.compiler.python.analyzer.types import STRING_METHODS

            method = STRING_METHODS.get(callee.field)
            return bool(method and method.tracked)
        if callee.field != "toString" or receiver is None:
            return False
        return receiver.base != "bool" and receiver.base not in self.index.enum_table

    def validate_mutex_destroy_receiver(self, expression, plan: MutexDestroyReceiverPlan) -> None:
        """Require one physical owned slot whose reference can be released."""
        receiver = expression.callee.obj
        if not plan.standalone:
            self.session.error(
                "Mutex.destroy() must be a standalone expression statement", expression.line, expression.col
            )
            return
        if plan.optional:
            self.session.error(
                "Mutex.destroy() cannot use optional chaining; release a physical owned slot",
                expression.line,
                expression.col,
            )
            return
        if plan.indirect or not plan.stable_storage:
            self.session.error(
                "Mutex.destroy() requires a physical owned slot; bind projections or temporaries to a local first",
                expression.line,
                expression.col,
            )
            return
        if not plan.mutable:
            return
        if not isinstance(receiver, Identifier):
            return
        symbol = self.session.scope.lookup(receiver.name)
        borrowed = {"param", "loop", "parallel", "catch", "capture", "lambda_param"}
        if symbol and symbol.kind in borrowed and (not symbol.owned_storage):
            self.session.error(
                "Borrowed Mutex bindings cannot be destroyed; bind an owned local first",
                expression.line,
                expression.col,
            )

    def _validate_mutex_payloads_in_type(self, type_expr, *, active_type_params=(), line=0, col=0) -> bool:
        """Validate every concrete Mutex payload nested in ``type_expr``."""
        canonical = self.types.canonical_type(type_expr)
        if canonical is None:
            return True
        valid = True
        if canonical.base == "Mutex" and len(canonical.generic_args or []) == 1:
            problem = self._mutex_payload_problem(canonical.generic_args[0], frozenset(active_type_params))
            if problem is not None:
                self.types.report_type_shape_error(f"Mutex<T> payload type {problem}", canonical, line, col)
                valid = False
        for argument in canonical.generic_args or []:
            if not self._validate_mutex_payloads_in_type(
                argument, active_type_params=active_type_params, line=line, col=col
            ):
                valid = False
        return valid

    def _mutex_payload_problem(self, payload, active_type_params):
        visiting = frozenset()
        if self._mutex_payload_contains_handle(payload, "Thread", active_type_params, visiting):
            return "cannot contain a Thread handle"
        if self._mutex_payload_contains_handle(payload, "Mutex", active_type_params, visiting):
            return "cannot contain a Mutex handle"
        if self._mutex_payload_contains_array(payload, active_type_params, visiting):
            return "cannot contain array storage"
        collection = self._unregistered_mutex_collection(payload, active_type_params, visiting)
        if collection is not None:
            return f"cannot contain runtime-owned collection storage without a registered managed class declaration ('{collection}')"
        canonical = self.types.canonical_type(payload)
        if not self._is_direct_mutex_managed_value(canonical) and self._mutex_payload_has_managed_reference(
            canonical, active_type_params, visiting
        ):
            return "aggregate cannot contain string or class references"
        return None

    def _mutex_payload_contains_handle(self, type_expr, handle, active_type_params, visiting) -> bool:
        canonical = self.types.canonical_type(type_expr)
        if canonical is None or self._is_unresolved_mutex_parameter(canonical, active_type_params):
            return False
        if canonical.base == handle:
            return True
        if canonical.base in {"__fn_ptr", "__realtime_fn_ptr"}:
            return False
        if any(
            self._mutex_payload_contains_handle(argument, handle, active_type_params, visiting)
            for argument in canonical.generic_args or []
        ):
            return True
        return any(
            self._mutex_payload_contains_handle(field, handle, active_type_params, nested)
            for field, nested in self._mutex_aggregate_fields(canonical, visiting)
        )

    def _mutex_payload_contains_array(self, type_expr, active_type_params, visiting) -> bool:
        canonical = self.types.canonical_type(type_expr)
        if canonical is None or self._is_unresolved_mutex_parameter(canonical, active_type_params):
            return False
        if canonical.is_array:
            return True
        if canonical.base in {"__fn_ptr", "__realtime_fn_ptr"}:
            return False
        if any(
            self._mutex_payload_contains_array(argument, active_type_params, visiting)
            for argument in canonical.generic_args or []
        ):
            return True
        return any(
            self._mutex_payload_contains_array(field, active_type_params, nested)
            for field, nested in self._mutex_aggregate_fields(canonical, visiting)
        )

    def _unregistered_mutex_collection(self, type_expr, active_type_params, visiting):
        canonical = self.types.canonical_type(type_expr)
        if canonical is None or self._is_unresolved_mutex_parameter(canonical, active_type_params):
            return None
        if canonical.base in _RUNTIME_COLLECTION_BASES and canonical.base not in self.index.class_table:
            return canonical.base
        if canonical.base in {"__fn_ptr", "__realtime_fn_ptr"}:
            return None
        for argument in canonical.generic_args or []:
            collection = self._unregistered_mutex_collection(argument, active_type_params, visiting)
            if collection is not None:
                return collection
        for field, nested in self._mutex_aggregate_fields(canonical, visiting):
            collection = self._unregistered_mutex_collection(field, active_type_params, nested)
            if collection is not None:
                return collection
        return None

    def _mutex_payload_has_managed_reference(self, type_expr, active_type_params, visiting) -> bool:
        canonical = self.types.canonical_type(type_expr)
        if canonical is None or self._is_unresolved_mutex_parameter(canonical, active_type_params):
            return False
        if self._is_direct_mutex_managed_value(canonical):
            return True
        if canonical.pointer_depth > 0 or canonical.base in {"__fn_ptr", "__realtime_fn_ptr"}:
            return False
        if canonical.is_array:
            canonical = self.types.strip_outer_storage(canonical, array=True)
        if canonical.base == "Tuple":
            return any(
                self._mutex_payload_has_managed_reference(argument, active_type_params, visiting)
                for argument in canonical.generic_args or []
            )
        return any(
            self._mutex_payload_has_managed_reference(field, active_type_params, nested)
            for field, nested in self._mutex_aggregate_fields(canonical, visiting)
        )

    def _is_direct_mutex_managed_value(self, canonical) -> bool:
        return bool(
            canonical
            and (not canonical.is_array)
            and (
                self.types.is_scalar_string_value(canonical)
                or (canonical.base in self.index.class_table and canonical.pointer_depth <= 1)
            )
        )

    @staticmethod
    def _is_unresolved_mutex_parameter(canonical, active_type_params) -> bool:
        return bool(
            canonical.base in active_type_params
            and (not canonical.generic_args)
            and (canonical.pointer_depth == 0)
            and (not canonical.is_array)
        )

    def _mutex_aggregate_fields(self, canonical, visiting):
        if canonical.pointer_depth > 0:
            return ()
        if canonical.base == "Tuple":
            return tuple((argument, visiting) for argument in canonical.generic_args or [])
        name = canonical.base.removeprefix("struct ")
        kind = "struct" if name in self.index.struct_table else "rich-enum"
        visit_key = f"{kind}:{name}"
        if visit_key in visiting:
            return ()
        nested = visiting | {visit_key}
        fields = []
        declaration = self.index.struct_table.get(name)
        if declaration and (not declaration.is_forward):
            fields.extend((field.type, nested) for field in declaration.fields)
        rich_enum = self.index.rich_enum_table.get(name)
        if rich_enum:
            for variant in rich_enum.variants:
                fields.extend((parameter.type, nested) for parameter in variant.params)
        return tuple(fields)

    def _raw_parameter_call_is_safe(self, call, name, owner, local_names) -> bool:
        if self.raw_expression_mentions_parameter(call.callee, name):
            return False
        declaration, unresolved = self._raw_borrow_call_target(call, owner, local_names)
        for argument_index, argument in enumerate(call.args):
            if not self._raw_expression_carries_parameter(argument, name):
                continue
            if isinstance(call.callee, Identifier) and self.is_raw_lifetime_call(call) and (argument_index == 0):
                return False
            if unresolved and self._raw_unresolved_call_is_borrow_only(call, argument_index):
                continue
            if unresolved or declaration is None:
                return False
            parameter_index = self._raw_bound_parameter_index(declaration, call, argument_index)
            if parameter_index < 0 or not self._raw_parameter_is_borrow_only(declaration, parameter_index):
                return False
        return True

    @staticmethod
    def _raw_unresolved_call_is_borrow_only(call, argument_index):
        callee = call.callee
        return bool(
            isinstance(callee, Identifier) and HOSTED_ABI.parameter_is_read_only_borrow(callee.name, argument_index)
        )

    def _raw_borrow_call_target(self, call, owner, local_names):
        callee = call.callee
        if isinstance(callee, Identifier):
            if callee.name in local_names:
                return (None, False)
            if self.hosted_call_uses_owned_symbol(call, local_names=local_names):
                return (None, True)
            declaration = self.index.function_table.get(callee.name)
            return (declaration, declaration is None or declaration.body is None)
        if not isinstance(callee, FieldAccessExpr):
            return (None, False)
        if isinstance(callee.obj, SelfExpr) and owner is not None:
            return (owner.methods.get(callee.field), False)
        if isinstance(callee.obj, Identifier):
            class_info = self.index.class_table.get(callee.obj.name)
            if class_info is not None:
                return (class_info.methods.get(callee.field), False)
        return (None, False)

    @staticmethod
    def _raw_bound_parameter_index(declaration, call, argument_index):
        if argument_index < len(call.arg_names) and call.arg_names[argument_index]:
            name = call.arg_names[argument_index]
            return next((index for index, parameter in enumerate(declaration.params) if parameter.name == name), -1)
        return argument_index

    def _raw_expression_carries_parameter(self, expression, name) -> bool:
        if expression is None:
            return False
        if isinstance(expression, Identifier):
            return expression.name == name
        if isinstance(expression, CastExpr):
            return self._raw_expression_carries_parameter(expression.expr, name)
        if isinstance(expression, UnaryExpr):
            if expression.op == "&":
                return self.raw_expression_mentions_parameter(expression.operand, name)
            if expression.op == "!":
                return False
            if expression.op == "*":
                return bool(
                    self._opaque_projection_carrier_type(self.type_of(expression))
                    and self.raw_expression_mentions_parameter(expression.operand, name)
                )
            return self._raw_expression_carries_parameter(expression.operand, name)
        if isinstance(expression, BinaryExpr):
            if expression.op in _NON_CARRYING_BINARY_OPS:
                return False
            return self._raw_expression_carries_parameter(
                expression.left, name
            ) or self._raw_expression_carries_parameter(expression.right, name)
        if isinstance(expression, TernaryExpr):
            return self._raw_expression_carries_parameter(
                expression.true_expr, name
            ) or self._raw_expression_carries_parameter(expression.false_expr, name)
        if isinstance(expression, (IndexExpr, FieldAccessExpr)):
            return bool(
                self._opaque_projection_carrier_type(self.type_of(expression))
                and self.raw_expression_mentions_parameter(expression, name)
            )
        if isinstance(expression, CallExpr):
            return self._raw_hosted_alias_carries_parameter(expression, name)
        if isinstance(expression, NewExpr):
            return any(self._raw_expression_carries_parameter(argument, name) for argument in expression.args)
        if isinstance(expression, (BraceInitializer, ListLiteral, TupleLiteral)):
            return any(self._raw_expression_carries_parameter(element, name) for element in expression.elements)
        if isinstance(expression, MapLiteral):
            return any(
                self._raw_expression_carries_parameter(entry.key, name)
                or self._raw_expression_carries_parameter(entry.value, name)
                for entry in expression.entries
            )
        return False

    def _raw_hosted_alias_carries_parameter(self, expression, name) -> bool:
        callee = expression.callee
        if not isinstance(callee, Identifier):
            return False
        local_names = self._raw_borrow_proof_local_names
        if not self.hosted_call_uses_owned_symbol(expression, local_names=local_names):
            return False
        parameter = HOSTED_ABI.return_alias_parameter(callee.name)
        return bool(
            parameter is not None
            and parameter < len(expression.args)
            and self._raw_expression_carries_parameter(expression.args[parameter], name)
        )

    @staticmethod
    def raw_expression_mentions_parameter(node, name: str) -> bool:
        if node is None:
            return False
        if isinstance(node, Identifier):
            return node.name == name
        if isinstance(node, LambdaExpr):
            if any(parameter.name == name for parameter in node.params):
                return False
            return OwnershipAnalyzer.raw_expression_mentions_parameter(node.body, name)
        if isinstance(node, (str, int, float, bool)):
            return False
        if isinstance(node, (list, tuple)):
            return any(OwnershipAnalyzer.raw_expression_mentions_parameter(item, name) for item in node)
        if not is_dataclass(node):
            return False
        return any(
            OwnershipAnalyzer.raw_expression_mentions_parameter(getattr(node, field.name), name)
            for field in fields(node)
            if field.name not in _LOCATION_FIELDS
        )

    @staticmethod
    def raw_statement_consumes_parameter(node, name: str) -> bool:
        return isinstance(
            node, (DeleteStmt, KeepStmt, ReleaseStmt, ThrowStmt)
        ) and OwnershipAnalyzer.raw_expression_mentions_parameter(node.expr, name)

    @staticmethod
    def raw_local_names(declaration) -> frozenset[str]:
        names = {parameter.name for parameter in getattr(declaration, "params", ()) or ()}

        def collect(node) -> None:
            if node is None or isinstance(node, (str, int, float, bool)):
                return
            if isinstance(node, (list, tuple)):
                for item in node:
                    collect(item)
                return
            if not is_dataclass(node):
                return
            if isinstance(node, VarDeclStmt):
                names.add(node.name)
            for field in fields(node):
                if field.name not in _LOCATION_FIELDS:
                    collect(getattr(node, field.name))

        collect(getattr(declaration, "body", None))
        return frozenset(names)

    def _raw_parameter_is_borrow_only(self, declaration, index) -> bool:
        cache = self._raw_borrow_effect_cache
        provenance = getattr(declaration, "source_file", None)
        key = (id(declaration), index, provenance)
        if key in cache:
            return cache[key]
        if key in self._raw_borrow_effect_visiting:
            return False
        params = getattr(declaration, "params", ()) or ()
        body = getattr(declaration, "body", None)
        if body is None or index >= len(params):
            return False
        self._raw_borrow_effect_visiting.add(key)
        owner = self._raw_borrow_owner(declaration)
        local_names = self.raw_local_names(declaration)
        previous_locals = self._raw_borrow_proof_local_names
        self._raw_borrow_proof_local_names = local_names
        try:
            with self.session.source(provenance):
                result = self._raw_parameter_uses_are_safe(body, params[index].name, owner, local_names)
        finally:
            self._raw_borrow_proof_local_names = previous_locals
            self._raw_borrow_effect_visiting.remove(key)
        cache[key] = result
        return result

    def _raw_borrow_owner(self, declaration):
        owners = self._raw_borrow_owner_cache
        if owners is None:
            owners = self._raw_borrow_owner_cache = {}
            for info in self.index.class_table.values():
                for name, method in info.methods.items():
                    declaring_name = info.method_owners.get(name, info.name)
                    declaring_info = self.index.class_table.get(declaring_name, info)
                    owners[id(method)] = declaring_info
                if info.constructor is not None:
                    owners[id(info.constructor)] = info
        return owners.get(id(declaration))

    def _raw_parameter_uses_are_safe(self, node, name, owner, local_names) -> bool:
        if node is None:
            return True
        if isinstance(node, VarDeclStmt):
            if self._raw_expression_carries_parameter(node.initializer, name):
                return False
        elif isinstance(node, AssignExpr):
            if self.raw_expression_mentions_parameter(node.target, name) or self._raw_expression_carries_parameter(
                node.value, name
            ):
                return False
        elif isinstance(node, ReturnStmt):
            if self._raw_expression_carries_parameter(node.value, name):
                return False
        elif isinstance(node, (LambdaExpr, NewExpr, SpawnExpr)):
            if self.raw_expression_mentions_parameter(node, name):
                return False
        elif isinstance(node, UnaryExpr) and node.op in {"++", "--"}:
            if self.raw_expression_mentions_parameter(node.operand, name):
                return False
        elif self.raw_statement_consumes_parameter(node, name):
            return False
        elif isinstance(node, CallExpr):
            if not self._raw_parameter_call_is_safe(node, name, owner, local_names):
                return False
        if isinstance(node, (str, int, float, bool)):
            return True
        if isinstance(node, (list, tuple)):
            return all(self._raw_parameter_uses_are_safe(item, name, owner, local_names) for item in node)
        if not is_dataclass(node):
            return True
        return all(
            self._raw_parameter_uses_are_safe(getattr(node, field.name), name, owner, local_names)
            for field in fields(node)
            if field.name not in {"line", "col", "source_file"}
        )

    def _opaque_projection_carrier_type(self, type_expr) -> bool:
        canonical = self.types.canonical_type(type_expr)
        return bool(
            canonical
            and (canonical.is_array or canonical.pointer_depth > 0 or canonical.base in {"intptr_t", "uintptr_t"})
        )

    def _opaque_projection_embeds_storage(self, expression) -> bool:
        """Whether a field/index result still denotes its receiver's storage."""
        return self.storage.projection_embeds_storage(expression)

    def _has_temporary_projection_storage(self, expression) -> bool:
        """Whether a projection's backing storage dies with this expression."""
        if expression is None:
            return False
        if self.expression_produces_owned_result(expression):
            return True
        result_type = self.types.canonical_type(self.type_of(expression))
        struct_name = result_type.base.removeprefix("struct ") if result_type else ""
        temporary_struct = bool(
            result_type
            and result_type.pointer_depth == 0
            and (not result_type.is_array)
            and (struct_name in self.index.struct_table)
        )
        if isinstance(expression, (CallExpr, BraceInitializer)):
            return temporary_struct
        if isinstance(expression, CastExpr):
            return self._has_temporary_projection_storage(expression.expr)
        if isinstance(expression, (FieldAccessExpr, IndexExpr)):
            return self._has_temporary_projection_storage(expression.obj)
        if isinstance(expression, TernaryExpr):
            return self._has_temporary_projection_storage(
                expression.true_expr
            ) or self._has_temporary_projection_storage(expression.false_expr)
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return self._has_temporary_projection_storage(expression.left) or self._has_temporary_projection_storage(
                expression.right
            )
        return isinstance(expression, NewExpr) and temporary_struct

    def _hosted_return_alias_argument(self, expression):
        if not isinstance(expression, CallExpr) or not isinstance(expression.callee, Identifier):
            return None
        if not self.hosted_call_uses_owned_symbol(expression):
            return None
        name = expression.callee.name
        parameter = HOSTED_ABI.return_alias_parameter(name)
        if parameter is None or parameter >= len(expression.args):
            return None
        return expression.args[parameter]

    def _opaque_managed_type(self, type_expr):
        canonical = self.types.canonical_type(type_expr)
        if canonical is None or canonical.is_array:
            return None
        active = self.storage.active_type_parameters()
        active_parameter_value = canonical.base in active and (
            canonical.pointer_depth == 0 or (canonical.is_nullable and canonical.pointer_depth == 1)
        )
        if self.is_managed_result_type(canonical) or canonical.base in _MANAGED_RUNTIME_BASES or active_parameter_value:
            return canonical
        return None

    def _opaque_raw_carrier_type(self, type_expr) -> bool:
        canonical = self.types.canonical_type(type_expr)
        if canonical is None or self._opaque_managed_type(canonical):
            return False
        if canonical.pointer_depth > 0:
            return True
        return bool(canonical.base != "bool" and self.types.is_numeric_value(canonical))

    def opaque_managed_origin_type(self, expression):
        if expression is None:
            return None
        if isinstance(expression, StringLiteral):
            return None
        direct = self._opaque_managed_type(self.type_of(expression))
        if direct is not None:
            return direct
        if isinstance(expression, CastExpr):
            return self.opaque_managed_origin_type(expression.expr)
        if isinstance(expression, UnaryExpr):
            if expression.op == "*":
                if self._opaque_projection_carrier_type(
                    self.type_of(expression)
                ) and self._expression_carries_opaque_borrow(expression.operand):
                    return self.opaque_managed_origin_type(expression.operand)
                return None
            return self.opaque_managed_origin_type(expression.operand)
        if isinstance(expression, BinaryExpr):
            if expression.op in _NON_CARRYING_BINARY_OPS:
                return None
            return self.opaque_managed_origin_type(expression.left) or self.opaque_managed_origin_type(expression.right)
        if isinstance(expression, TernaryExpr):
            return self.opaque_managed_origin_type(expression.true_expr) or self.opaque_managed_origin_type(
                expression.false_expr
            )
        if isinstance(expression, (IndexExpr, FieldAccessExpr)):
            origin = self.opaque_managed_origin_type(expression.obj)
            carries = self._expression_carries_opaque_borrow(expression.obj)
            embedded = self._opaque_projection_embeds_storage(expression)
            if self._opaque_projection_carrier_type(self.type_of(expression)) and (
                carries or (embedded and (origin or self._has_temporary_projection_storage(expression.obj)))
            ):
                return origin
            return None
        alias_argument = self._hosted_return_alias_argument(expression)
        if alias_argument is not None:
            return self.opaque_managed_origin_type(alias_argument)
        return None

    def _expression_carries_opaque_borrow(self, expression) -> bool:
        if expression is None:
            return False
        if isinstance(expression, CastExpr):
            if not self._opaque_raw_carrier_type(expression.target_type):
                return False
            if isinstance(expression.expr, StringLiteral):
                return False
            return bool(
                self.opaque_managed_origin_type(expression.expr)
                or self._expression_carries_opaque_borrow(expression.expr)
            )
        if isinstance(expression, UnaryExpr):
            if expression.op == "!":
                return False
            if expression.op == "&":
                operand = expression.operand
                return bool(
                    self._opaque_projection_carrier_type(self.type_of(expression))
                    and (
                        self._expression_carries_opaque_borrow(operand)
                        or (
                            isinstance(operand, (FieldAccessExpr, IndexExpr))
                            and (
                                self.opaque_managed_origin_type(operand.obj)
                                or self._expression_carries_opaque_borrow(operand.obj)
                                or self._has_temporary_projection_storage(operand.obj)
                            )
                        )
                    )
                )
            if expression.op == "*":
                return bool(
                    self._opaque_projection_carrier_type(self.type_of(expression))
                    and self._expression_carries_opaque_borrow(expression.operand)
                )
            return self._expression_carries_opaque_borrow(expression.operand)
        if isinstance(expression, BinaryExpr):
            if expression.op in _NON_CARRYING_BINARY_OPS:
                return False
            if expression.op == "-" and all(
                self.types.is_pointer_value(self.type_of(operand)) for operand in (expression.left, expression.right)
            ):
                return False
            return self._expression_carries_opaque_borrow(expression.left) or self._expression_carries_opaque_borrow(
                expression.right
            )
        if isinstance(expression, TernaryExpr):
            return self._expression_carries_opaque_borrow(
                expression.true_expr
            ) or self._expression_carries_opaque_borrow(expression.false_expr)
        if isinstance(expression, (IndexExpr, FieldAccessExpr)):
            embedded = self._opaque_projection_embeds_storage(expression)
            return bool(
                self._opaque_projection_carrier_type(self.type_of(expression))
                and (
                    self._expression_carries_opaque_borrow(expression.obj)
                    or (
                        embedded
                        and (
                            self.opaque_managed_origin_type(expression.obj)
                            or self._has_temporary_projection_storage(expression.obj)
                        )
                    )
                )
            )
        alias_argument = self._hosted_return_alias_argument(expression)
        if alias_argument is not None:
            return self.expression_is_opaque_borrow(alias_argument)
        return False

    def expression_is_opaque_borrow(self, expression) -> bool:
        if isinstance(expression, StringLiteral):
            return False
        return bool(
            self._opaque_managed_type(self.type_of(expression)) or self._expression_carries_opaque_borrow(expression)
        )

    @staticmethod
    def _explicit_opaque_storage_address(expression) -> bool:
        """Recognize an explicit address without blessing representation casts."""
        while isinstance(expression, CastExpr):
            expression = expression.expr
        return bool(
            isinstance(expression, UnaryExpr)
            and expression.op == "&"
            and isinstance(expression.operand, (FieldAccessExpr, IndexExpr))
        )

    def validate_opaque_borrow_storage(self, expected, value, subject="This operation", line=0, col=0) -> None:
        if not self._opaque_raw_carrier_type(expected):
            return
        if not self.expression_is_opaque_borrow(value):
            return
        self.session.error(
            f"{subject} cannot persist a managed value as a raw representation; use it only in a non-persisting expression or a proven borrow-only FFI call",
            getattr(value, "line", line),
            getattr(value, "col", col),
        )

    def validate_opaque_call_argument(
        self, declaration, parameter_index, expected, argument, label, *, bodyless_ffi=False
    ) -> None:
        if not self._opaque_raw_carrier_type(expected):
            return
        if not self.expression_is_opaque_borrow(argument):
            return
        hosted_borrow = bodyless_ffi and (
            HOSTED_ABI.parameter_is_read_only_borrow(label, parameter_index)
            or (
                self._explicit_opaque_storage_address(argument)
                and HOSTED_ABI.parameter_is_nonescaping(label, parameter_index)
            )
        )
        if hosted_borrow or (
            declaration is not None and self._raw_parameter_is_borrow_only(declaration, parameter_index)
        ):
            return
        self.session.error(
            f"Argument to '{label}()' cannot forward a managed value as a raw representation because the parameter is not proven borrow-only",
            getattr(argument, "line", 0),
            getattr(argument, "col", 0),
        )

    def validate_managed_parameter_consumption(self, statement, expression, operand_type) -> None:
        if (
            not isinstance(statement, (DeleteStmt, ReleaseStmt))
            or not isinstance(expression, Identifier)
            or (not self._possibly_managed_parameter_type(operand_type))
        ):
            return
        symbol = self.session.scope.lookup(expression.name)
        if symbol is None:
            return
        if isinstance(statement, ReleaseStmt) and self._release_balances_keep(expression):
            return
        if symbol.kind in {"capture", "lambda_param"} and (not symbol.owned_storage):
            self.session.error(
                "Borrowed managed lambda bindings cannot be released or deleted; bind an owned local first",
                statement.line,
                statement.col,
            )
            return
        if symbol.kind != "param":
            return
        if self.session.in_virtual_setter or self._is_index_setter_value_param(expression.name):
            self.session.error(
                "Property/index setter value parameters cannot consume their argument because assignment results must remain valid",
                statement.line,
                statement.col,
            )
            return
        declaration = self.session.current_callable
        transferred = self.owned_transfer_param_indices(declaration)
        index = next(
            (
                position
                for position, parameter in enumerate(getattr(declaration, "params", ()))
                if parameter.name == expression.name
            ),
            -1,
        )
        if index not in transferred:
            self.session.error(
                "Managed parameter consumption must be an unconditional leading release/delete so callers can prove ownership transfer",
                statement.line,
                statement.col,
            )

    def _release_balances_keep(self, expression: Identifier) -> bool:
        """Whether an adjacent retain supplies the reference being released.

        Adjacency keeps this proof local: no intervening statement can throw or
        leave the scope before the guard reference is released.
        """
        previous = self.session.previous_statement
        return bool(
            isinstance(previous, KeepStmt)
            and isinstance(previous.expr, Identifier)
            and (previous.expr.name == expression.name)
        )

    def _possibly_managed_parameter_type(self, type_expr) -> bool:
        if type_expr is None:
            return False
        if type_expr.base in {"string", "Mutex"} or type_expr.base in self.index.class_table:
            return True
        params = set(self.session.current_class.generic_params if self.session.current_class else ())
        params.update(getattr(self.session.current_callable, "generic_params", ()) or ())
        return type_expr.base in params

    def _is_index_setter_value_param(self, name: str) -> bool:
        method = self.session.current_method
        return bool(method and method.name == "set" and (len(method.params) == 2) and (method.params[1].name == name))

    def raw_lifetime_uses_static_string(self, expression) -> bool:
        if isinstance(expression, StringLiteral):
            return True
        if isinstance(expression, CastExpr):
            return self.raw_lifetime_uses_static_string(expression.expr)
        if isinstance(expression, UnaryExpr):
            return self.raw_lifetime_uses_static_string(expression.operand)
        if isinstance(expression, BinaryExpr):
            return self.raw_lifetime_uses_static_string(expression.left) or self.raw_lifetime_uses_static_string(
                expression.right
            )
        if isinstance(expression, TernaryExpr):
            return self.raw_lifetime_uses_static_string(expression.true_expr) or self.raw_lifetime_uses_static_string(
                expression.false_expr
            )
        alias_argument = self._hosted_return_alias_argument(expression)
        if alias_argument is not None:
            return self.raw_lifetime_uses_static_string(alias_argument)
        return False

    def _is_hosted_raw_lifetime_value(self, name: str) -> bool:
        if HOSTED_ABI.raw_lifetime_arity(name) is None:
            return False
        symbol = self.session.scope.lookup(name)
        if symbol is not None and symbol.kind != "function":
            return False
        declaration = self.index.function_table.get(name)
        return bool(
            declaration is None or declaration.body is None or self.hosted_name_bypasses_source_definition(name)
        )

    def validate_raw_lifetime_value(self, expression, direct_callee) -> bool:
        if direct_callee or not self._is_hosted_raw_lifetime_value(expression.name):
            return False
        self.session.error(
            f"Hosted lifetime function '{expression.name}' must be called directly and cannot be stored or forwarded as a value",
            expression.line,
            expression.col,
        )
        return True

    def is_raw_lifetime_call(self, call) -> bool:
        callee = call.callee
        if not isinstance(callee, Identifier) or HOSTED_ABI.raw_lifetime_arity(callee.name) is None:
            return False
        symbol = self.session.scope.lookup(callee.name)
        if symbol is not None and symbol.kind != "function":
            return False
        declaration = self.index.function_table.get(callee.name)
        if declaration is not None:
            return declaration.body is None or self.hosted_call_bypasses_source_definition(call)
        return callee.name not in self.index.class_table and symbol is None

    def validate_raw_lifetime_call(self, call) -> None:
        """Reject values whose lifetime is owned by a btrc runtime protocol."""
        name = call.callee.name
        expected = HOSTED_ABI.raw_lifetime_arity(name)
        if expected is None:
            return
        if len(call.args) != expected:
            self.session.error(
                f"'{name}()' expects {expected} argument(s) but got {len(call.args)}", call.line, call.col
            )
            return
        if any(call.arg_names or ()):
            self.session.error(f"'{name}()' does not accept named arguments", call.line, call.col)
            return
        argument = call.args[0]
        if self.raw_lifetime_uses_static_string(argument):
            self.session.error(
                f"{name}() cannot consume static string storage; only heap memory owned by a raw allocator may be consumed",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )
            return
        lifetime_source = argument
        while isinstance(lifetime_source, CastExpr):
            lifetime_source = lifetime_source.expr
        argument_type = self.opaque_managed_origin_type(argument)
        if argument_type is not None and (not argument_type.is_array):
            if self._reject_managed_raw_deallocation(name, argument, argument_type, lifetime_source, call):
                return
        family = HOSTED_ABI.consume_deallocator(name)
        compatibility, producer = self._hosted_deallocator_compatibility(argument, family)
        if compatibility is False:
            self.session.error(
                f"{name}() cannot consume storage returned by {producer}() because it is not compatible with the '{family}' deallocator family",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )

    def _reject_managed_raw_deallocation(self, name, argument, argument_type, lifetime_source, call) -> bool:
        active_parameters = self.storage.active_type_parameters()
        unresolved_value = argument_type.base in active_parameters and argument_type.pointer_depth == 0
        managed_value = self._opaque_managed_type(argument_type) is not None
        runtime_handle = argument_type.base == "Thread" and argument_type.pointer_depth == 0
        if not (managed_value or runtime_handle or unresolved_value):
            return False
        indirect = self.storage.is_virtual_projection(lifetime_source)
        if name != "free":
            guidance = "raw resizing is only valid for raw pointer buffers"
        elif indirect:
            guidance = "bind an owned direct local before managed destruction"
        elif runtime_handle:
            guidance = "join the Thread or let its owning scope clean it up"
        elif unresolved_value:
            guidance = "use a pointer-typed raw buffer or a managed ownership operation"
        elif argument_type.base == "string":
            guidance = "release the string or let its owning scope clean it up"
        elif argument_type.base == "Mutex":
            guidance = "call Mutex.destroy() or let its owning scope clean it up"
        else:
            guidance = "use 'delete' so the owning slot is cleared safely"
        self.session.error(
            f"{name}() cannot consume managed value of type '{self.types.format_type(argument_type)}'; {guidance}",
            getattr(argument, "line", call.line),
            getattr(argument, "col", call.col),
        )
        return True

    def _hosted_deallocator_compatibility(self, expression, family):
        while isinstance(expression, CastExpr):
            expression = expression.expr
        if isinstance(expression, UnaryExpr) and expression.op == "&":
            return (False, "address-of storage")
        if isinstance(expression, TernaryExpr):
            return self._combined_deallocator_compatibility((expression.true_expr, expression.false_expr), family)
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return self._combined_deallocator_compatibility((expression.left, expression.right), family)
        inferred = self.types.canonical_type(self.type_of(expression))
        if (
            isinstance(expression, BinaryExpr)
            and expression.op in {"+", "-"}
            and (inferred is not None)
            and (inferred.pointer_depth > 0)
        ):
            return (False, "pointer arithmetic")
        if inferred is not None and inferred.is_array:
            return (False, "array storage")
        if not isinstance(expression, CallExpr) or not isinstance(expression.callee, Identifier):
            return (None, "raw value")
        if not self.hosted_call_uses_owned_symbol(expression):
            return (None, expression.callee.name)
        name = expression.callee.name
        alias_is_null = HOSTED_ABI.alias_argument_is_provably_null(name, expression.args)
        deallocator = HOSTED_ABI.return_deallocator(name, alias_argument_is_null=alias_is_null)
        if deallocator is not None:
            return (deallocator == family, name)
        effect = HOSTED_ABI.return_effect(name, alias_argument_is_null=alias_is_null)
        if effect != RETURN_ALIAS or HOSTED_ABI.return_alias_shape(name) != ALIAS_EXACT:
            return (False, name)
        spec = HOSTED_ABI.function(name)
        index = spec.return_alias_parameter if spec is not None else None
        if index is None or index >= len(expression.args):
            return (False, name)
        compatibility, producer = self._hosted_deallocator_compatibility(expression.args[index], family)
        return (compatibility, producer if compatibility is False else name)

    def _combined_deallocator_compatibility(self, branches, family):
        results = [self._hosted_deallocator_compatibility(branch, family) for branch in branches]
        invalid = next((item for item in results if item[0] is False), None)
        if invalid is not None:
            return invalid
        if all(item[0] is True for item in results):
            return (True, "conditional allocation")
        return (None, "conditional raw value")

    def validate_conditional_raw_projection_call(self, call) -> None:
        """Reject carriers whose owner cannot be stabilized without eager branches."""
        for argument in call.args:
            carrier = self.raw_projection_carrier(argument)
            choice = self.first_branch_local_storage_choice(carrier)
            if choice is not None:
                self.session.error(
                    _CONDITIONAL_STORAGE_ERROR, getattr(choice, "line", call.line), getattr(choice, "col", call.col)
                )

    def _is_managed(self, type_expr) -> bool:
        return self.is_managed_result_type(self.types.canonical_type(type_expr))

    def _is_raw_carrier(self, type_expr) -> bool:
        canonical = self.types.canonical_type(type_expr)
        return self.is_raw_projection_carrier_type(canonical)

    @staticmethod
    def _callable_statements(declaration):
        """Return a callable's block statements, including wrapped lambda blocks."""
        body = getattr(declaration, "body", None)
        statements = getattr(body, "statements", None)
        if statements is not None:
            return statements
        return getattr(getattr(body, "body", None), "statements", ())

    @staticmethod
    def owned_transfer_param_indices(declaration) -> frozenset[int]:
        """Parameters consumed by unconditional leading release/delete statements."""
        body = getattr(declaration, "body", None)
        params = getattr(declaration, "params", None)
        if body is None or not params:
            return frozenset()
        indices = {parameter.name: index for index, parameter in enumerate(params) if not parameter.keep}
        transferred: set[int] = set()
        statements = OwnershipAnalyzer._callable_statements(declaration)
        for position, statement in enumerate(statements):
            if isinstance(statement, (DeleteStmt, ReleaseStmt)) and isinstance(statement.expr, Identifier):
                index = indices.get(statement.expr.name)
                if index is None:
                    return frozenset()
                transferred.add(index)
                continue
            if isinstance(statement, ReturnStmt) and statement.value is None and (position == len(statements) - 1):
                break
            return frozenset()
        return frozenset(transferred)

    def is_raw_projection_carrier_type(self, type_expr) -> bool:
        """Match every strict-C pointer/array/address-integer carrier."""
        return bool(
            type_expr
            and (not self._is_managed(type_expr))
            and (type_expr.is_array or type_expr.pointer_depth > 0 or type_expr.base in {"intptr_t", "uintptr_t"})
        )

    def raw_projection_carrier(self, expression):
        """Return the branch-preserving raw-projection shape for ``expression``."""
        return self._raw_projection_carrier(expression, addressed=False)

    def _raw_projection_carrier(self, expression, *, addressed: bool):
        alias_argument = self._hosted_return_alias_argument(expression)
        if alias_argument is not None:
            nested = self._raw_projection_carrier(alias_argument, addressed=False)
            if nested is not None:
                return nested
            if self.storage.is_managed_value_type(self.type_of(alias_argument)):
                return RawProjectionLeaf(expression=alias_argument, direct_storage=True)
            return None
        if isinstance(expression, CastExpr):
            if not self._is_raw_carrier(self.type_of(expression)):
                return None
            nested = self._raw_projection_carrier(expression.expr, addressed=False)
            if nested is not None:
                return nested
            if self.storage.is_managed_value_type(self.type_of(expression.expr)):
                return RawProjectionLeaf(expression=expression.expr, direct_storage=True)
            return None
        if isinstance(expression, UnaryExpr) and expression.op == "&":
            return self._raw_projection_carrier(expression.operand, addressed=True)
        if (
            isinstance(expression, UnaryExpr)
            and expression.op == "*"
            and (addressed or self._is_raw_carrier(self.type_of(expression)))
        ):
            return self._raw_projection_carrier(expression.operand, addressed=False)
        if isinstance(expression, TernaryExpr):
            if not addressed and (not self._is_raw_carrier(self.type_of(expression))):
                return None
            return RawProjectionChoice(
                expression=expression,
                branches=(
                    self._branch("true", expression.true_expr, addressed),
                    self._branch("false", expression.false_expr, addressed),
                ),
            )
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            if not addressed and (not self._is_raw_carrier(self.type_of(expression))):
                return None
            return RawProjectionChoice(
                expression=expression,
                branches=(
                    self._branch("present", expression.left, addressed),
                    self._branch("fallback", expression.right, addressed),
                ),
            )
        if isinstance(expression, BinaryExpr) and expression.op in {"+", "-"}:
            if not self._is_raw_carrier(self.type_of(expression)):
                return None
            candidates = (expression.left, expression.right) if expression.op == "+" else (expression.left,)
            for candidate in candidates:
                if self._is_raw_carrier(self.type_of(candidate)):
                    carrier = self._raw_projection_carrier(candidate, addressed=False)
                    if carrier is not None:
                        return carrier
            return None
        if isinstance(expression, (FieldAccessExpr, IndexExpr)) and (
            addressed or self._is_raw_carrier(self.type_of(expression))
        ):
            nested = self._raw_projection_carrier(expression.obj, addressed=False)
            if nested is not None:
                return nested
            return RawProjectionLeaf(expression=expression)
        return None

    def _branch(self, label, expression, addressed):
        return RawProjectionBranch(
            label=label,
            expression=expression,
            carrier=self._raw_projection_carrier(expression, addressed=addressed),
        )

    @staticmethod
    def unconditional_projection_leaves(carrier):
        """Return leaves only when no runtime branch selects the backing store."""
        if carrier is None:
            return ()
        if isinstance(carrier, RawProjectionLeaf):
            return (carrier,)
        return ()

    def first_branch_local_storage_choice(self, carrier):
        """Find a choice that would require evaluating branch storage eagerly."""
        if not isinstance(carrier, RawProjectionChoice):
            return None
        for branch in carrier.branches:
            if self._carrier_has_storage(branch.carrier):
                return carrier.expression
        return None

    def _carrier_has_storage(self, carrier):
        if isinstance(carrier, RawProjectionLeaf):
            return self.storage.projection_storage_root(carrier.expression, direct=carrier.direct_storage) is not None
        if isinstance(carrier, RawProjectionChoice):
            return any(self._carrier_has_storage(branch.carrier) for branch in carrier.branches)
        return False


__all__ = [
    "CallableValueSemantics",
    "OwnershipAnalyzer",
    "RawProjectionBranch",
    "RawProjectionChoice",
    "RawProjectionLeaf",
]
