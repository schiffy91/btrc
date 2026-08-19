"""Cohesive calls IR lowering owner."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from src.compiler.python.abi.declarations import DEALLOC_FREE, RETURN_ALIAS, RETURN_FRESH, RETURN_INDEPENDENT
from src.compiler.python.abi.hosted import HOSTED_ABI
from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.analyzer.storage import StorageModel
from src.compiler.python.analyzer.types import (
    STRING_CONVERSIONS,
    STRING_METHODS,
    TypeIdentity,
    TypeSystem,
)
from src.compiler.python.ir.nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRExpr,
    IRFunctionDecl,
    IRLiteral,
    IRParam,
    IRStmtExpr,
    IRTernary,
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
    FieldAccessExpr,
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
    SpawnExpr,
    TernaryExpr,
    TupleLiteral,
    TypeExpr,
    UnaryExpr,
)

from .types import CodegenError, CTypeLowerer

if TYPE_CHECKING:
    from src.compiler.python.frontend.sources import SourceMap

    from .ownership import (
        CleanupScopeState,
        ManagedLifetimeLowerer,
        ManagedValueSemantics,
        OwnershipLowerer,
        OwnershipOperandOrder,
    )
    from .session import LoweringSession

_STRING_METHODS = frozenset(
    (
        "toString",
        "str",
        "trim",
        "toUpper",
        "toLower",
        "substring",
        "replace",
        "repeat",
        "reverse",
        "capitalize",
        "join",
        "split",
    )
)
ADOPT = "adopt"
COPY = "copy"
REJECT = "reject"
_STRING_METHODS = {name: spec.helper for name, spec in STRING_METHODS.items() if spec.helper}
_STRING_TRACK_METHODS = {name for name, spec in STRING_METHODS.items() if spec.tracked}
_STRING_CONVERSION_METHODS = STRING_CONVERSIONS


@dataclass(frozen=True)
class _DeclarationScope:
    function_name: str
    source_file: str
    source_map: SourceMap | None


@dataclass(frozen=True)
class _DefaultArgumentState:
    substitutions: Mapping[str, TypeExpr] | None = None
    declaration: _DeclarationScope | None = None


_EMPTY_DEFAULT_ARGUMENT_STATE = _DefaultArgumentState()


class DefaultArgumentLoweringContext:
    """Own call-default substitutions and declaration provenance for one run."""

    def __init__(self, type_identity: TypeIdentity | None = None) -> None:
        self._type_identity = type_identity if type_identity is not None else TypeIdentity()
        self._state = ContextVar(
            f"btrc_default_arguments_{id(self)}",
            default=_EMPTY_DEFAULT_ARGUMENT_STATE,
        )

    @contextmanager
    def scope(
        self,
        param,
        is_default: bool = True,
        *,
        function_name: str | None = None,
        source_file: str = "",
        source_map: SourceMap | None = None,
    ) -> Iterator[None]:
        """Activate one nested argument or declaration lowering scope."""
        current = self._state.get()
        substitutions = current.substitutions
        default_type_map = getattr(param, "default_type_map", None) if is_default and param is not None else None
        if default_type_map:
            substitutions = MappingProxyType(dict(default_type_map))
        declaration = current.declaration
        if function_name is not None:
            declaration = _DeclarationScope(
                function_name=function_name,
                source_file=source_file,
                source_map=source_map,
            )
        token = self._state.set(
            _DefaultArgumentState(
                substitutions=substitutions,
                declaration=declaration,
            )
        )
        try:
            yield
        finally:
            self._state.reset(token)

    def resolve_type(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        """Apply the active default parameter's concrete type substitutions."""
        substitutions = self._state.get().substitutions
        if not substitutions or type_expr is None:
            return type_expr
        return self._type_identity.substitute(type_expr, substitutions)

    def predefined_identifier(self, node) -> str | None:
        """Freeze a predefined identifier at its declaration site."""
        declaration = self._state.get().declaration
        if declaration is None:
            return None
        source_file = declaration.source_file
        source_line = node.line or 0
        if declaration.source_map is not None:
            mapped = declaration.source_map.declaration(
                declaration.source_file,
                source_line,
            )
            if mapped is not None:
                mapped_file, source_line = mapped
                source_file = source_file or mapped_file
        if node.name == "__func__":
            return json.dumps(declaration.function_name)
        if node.name == "__LINE__":
            return str(source_line)
        if node.name == "__FILE__" and source_file:
            return json.dumps(source_file)
        return None


@dataclass(frozen=True)
class CallOperand:
    """One source operand evaluated before invoking a managed call."""

    node: object
    type_expr: object
    c_type: str
    lowered: IRExpr
    keep: bool = False
    pin: bool = False
    owned: bool = False
    transferred: bool = False


@dataclass(frozen=True, slots=True)
class CallResultPlan:
    """Result lifetime contract applied after a call is materialized."""

    c_type: str | None
    type_expr: TypeExpr | None = None
    opaque: bool = False
    source_site: object | None = None
    promote: bool = False
    owned: bool = False


@dataclass(frozen=True)
class OperandEvaluation:
    """A source-ordered operand prefix reusable by calls and declarations."""

    declarations: list
    prefix: list
    handoffs: list
    suffix: list
    values: dict[int, object]

    @property
    def before_value(self) -> list:
        """Runtime expressions that must run before constructing the value."""
        return [*self.prefix, *self.handoffs]


class CallBoundaryLowerer:
    """Sequence call operands and their ARC lifetime transitions."""

    def __init__(
        self,
        context: LoweringSession,
        lifetime: ManagedLifetimeLowerer,
        cleanup_scope: CleanupScopeState,
        values: ManagedValueSemantics,
    ) -> None:
        self._session = context
        self._lifetime = lifetime
        self._cleanup_scope = cleanup_scope
        self._values = values

    def materialize(
        self,
        evaluation: OperandEvaluation,
        call: IRExpr,
        result: CallResultPlan,
    ) -> IRExpr:
        """Apply one result contract to an already materialized call."""
        if self._session.is_unevaluated:
            return call
        declarations = evaluation.declarations
        suffix = evaluation.suffix
        sequence = evaluation.before_value
        if result.opaque:
            self._append_opaque_result(sequence, suffix, call, result)
        elif result.c_type is not None and result.c_type != "void":
            self._append_typed_result(sequence, suffix, declarations, call, result)
        else:
            sequence.append(call)
            sequence.extend(suffix)
            sequence.append(IRCast(target_type=CType(text="void"), expr=IRLiteral(text="0")))
        return IRStmtExpr(stmts=declarations, result=IRCommaExpr(expressions=sequence))

    @staticmethod
    def start() -> OperandEvaluation:
        """Create an empty source-ordered operand transaction."""
        return OperandEvaluation([], [], [], [], {})

    def evaluate(self, operands: list[CallOperand]) -> OperandEvaluation:
        """Prepare already lowered operands in source order."""
        evaluation = self.start()
        for operand in operands:
            self.append(evaluation, operand)
        return evaluation

    def append(
        self,
        evaluation: OperandEvaluation,
        operand: CallOperand,
    ) -> None:
        """Append one explicitly lowered operand to a typed transaction."""
        if self._session.is_unevaluated:
            evaluation.values[id(operand.node)] = operand.lowered
            return
        declarations = evaluation.declarations
        prefix = evaluation.prefix
        handoffs = evaluation.handoffs
        suffix = evaluation.suffix
        overrides = evaluation.values
        declaration = self._temporary("__btrc_call_operand", operand.c_type)
        declarations.append(declaration)
        value = IRVar(name=declaration.name)
        lowered = operand.lowered
        value.record_array_stabilization(lowered, operand.type_expr)
        prefix.append(IRBinOp(left=value, op="=", right=lowered))
        if operand.owned:
            self._lifetime.protect_temporary(
                declaration, operand.type_expr, declarations, prefix, "__btrc_call_operand_cleanup"
            )
        if operand.keep or operand.pin:
            retained_decl = self._temporary("__btrc_kept_operand", operand.c_type)
            declarations.append(retained_decl)
            retained = IRVar(name=retained_decl.name)
            prefix.extend(
                [self._lifetime.retain_value(value, operand.type_expr), IRBinOp(left=retained, op="=", right=value)]
            )
            self._lifetime.protect_temporary(
                retained_decl, operand.type_expr, declarations, prefix, "__btrc_kept_operand_cleanup"
            )
            suffix.extend(self._lifetime.release_and_clear(retained, operand.type_expr, declarations, operand.c_type))
        call_value = value
        if operand.owned:
            if operand.transferred:
                handoff_decl = self._temporary("__btrc_transferred_operand", operand.c_type)
                declarations.append(handoff_decl)
                call_value = IRVar(name=handoff_decl.name)
                handoffs.extend(
                    [
                        IRBinOp(left=call_value, op="=", right=value),
                        IRBinOp(left=value, op="=", right=IRLiteral(text="NULL")),
                    ]
                )
            else:
                suffix.extend(self._lifetime.release_and_clear(value, operand.type_expr, declarations, operand.c_type))
        overrides[id(operand.node)] = call_value

    @staticmethod
    def _append_opaque_result(sequence, suffix, call, result: CallResultPlan) -> None:
        if result.c_type is not None or result.type_expr is not None:
            raise ValueError("opaque call result cannot also have a concrete type")
        if result.source_site is None:
            raise ValueError("opaque call result requires a source site")
        if suffix:
            CallLowerer.reject_opaque_result_cleanup(result.source_site)
        sequence.append(call)

    def _append_typed_result(self, sequence, suffix, declarations, call, plan: CallResultPlan) -> None:
        assert plan.c_type is not None
        result_decl = self._temporary("__btrc_call_result", plan.c_type)
        result_decl.is_volatile = True
        declarations.append(result_decl)
        result = IRVar(name=result_decl.name)
        sequence.append(IRBinOp(left=result, op="=", right=call))
        if plan.promote:
            if plan.type_expr is None:
                raise ValueError("managed result promotion requires its semantic type")
            sequence.append(self._lifetime.retain_value(result, plan.type_expr))
        protect_result = bool(
            self._cleanup_scope.exception_cleanup_active()
            and plan.type_expr is not None
            and (plan.owned or plan.promote)
            and self._values.is_managed(plan.type_expr)
        )
        if protect_result:
            self._lifetime.protect_temporary(
                result_decl, plan.type_expr, declarations, sequence, "__btrc_call_result_cleanup"
            )
            handoff_decl = self._temporary("__btrc_call_result_handoff", plan.c_type)
            declarations.append(handoff_decl)
            handoff = IRVar(name=handoff_decl.name)
        sequence.extend(suffix)
        if protect_result:
            sequence.extend(
                [
                    IRBinOp(left=handoff, op="=", right=result),
                    IRBinOp(left=result, op="=", right=IRLiteral(text="NULL")),
                    handoff,
                ]
            )
        else:
            sequence.append(result)

    def _temporary(self, prefix: str, c_type: str, init=None) -> IRVarDecl:
        declaration = IRVarDecl(c_type=CType(text=c_type), name=self._session.fresh_temp(prefix), init=init)
        self._session.record_declaration(declaration)
        return declaration


class CallableStorageBoundary:
    """Validate callable representation and ownership across storage boundaries."""

    def __init__(
        self,
        analyzed: AnalyzedProgram,
        values: ManagedValueSemantics,
        type_identity: TypeIdentity,
    ) -> None:
        self._analyzed = analyzed
        self._values = values
        self._type_identity = type_identity

    def is_managed_callable(self, type_expr: TypeExpr | None) -> bool:
        """Whether a bare function pointer returns an ARC-managed value."""
        resolved = self._values.canonical(type_expr)
        return bool(
            self.is_callable(resolved) and resolved.generic_args and self._values.is_managed(resolved.generic_args[0])
        )

    def is_callable(self, type_expr: TypeExpr | None) -> bool:
        """Whether a type is one scalar bare function-pointer value."""
        resolved = self._values.canonical(type_expr)
        return bool(
            resolved is not None
            and resolved.base == "__fn_ptr"
            and (resolved.pointer_depth == 0)
            and (not resolved.is_array)
        )

    def reject_persistent_escape(
        self,
        expected_type: TypeExpr | None,
        value: object | None,
        boundary: str,
        provenance: CallableProvenance,
    ) -> None:
        """Reject a callback whose ownership tag cannot survive storage."""
        self._reject_environment_callable(expected_type, value, boundary, provenance)
        if not self._contains_unsafe_managed_callback(expected_type, value, provenance):
            return
        raise CodegenError(
            f"Managed-return callback cannot cross {boundary}; bare __fn_ptr storage erases its return ABI"
        )

    def reject_address_escape(self, operand: object | None, provenance: CallableProvenance) -> None:
        """Reject aliases that can mutate a tracked callable slot indirectly."""
        if not (
            operand is not None
            and self._is_storage_expression(operand, provenance)
            and self.is_managed_callable(provenance.type_of(operand))
        ):
            return
        raise CodegenError(
            "Managed-return callable storage cannot be addressed; an alias cannot preserve flow-sensitive return ownership ABI"
        )

    def reject_nonportable_callable_cast(self, expression: CastExpr, provenance: CallableProvenance) -> None:
        """Reject strict-C-invalid casts between function and data domains."""
        target = self._values.canonical(expression.target_type)
        target_callable = self.is_callable(target)
        source = self._values.canonical(provenance.type_of(expression.expr))
        source_callable = self.is_callable(source)
        carries_callable = self._contains_callable_value(expression.expr, provenance, managed=False)
        if target_callable and (not source_callable):
            if isinstance(expression.expr, NullLiteral) or (
                isinstance(expression.expr, IntLiteral) and expression.expr.value == 0
            ):
                return
            raise CodegenError("Function pointers cannot be cast from object pointers or integer values in strict C11")
        if carries_callable and (not target_callable):
            if target is not None and target.base == "bool" and (target.pointer_depth == 0):
                return
            raise CodegenError("Function pointers cannot be cast to object pointers or integer values in strict C11")

    def _reject_environment_callable(
        self,
        expected_type: TypeExpr | None,
        value: object | None,
        boundary: str,
        provenance: CallableProvenance,
        *,
        allow_direct_lambda: bool = False,
    ) -> None:
        if allow_direct_lambda and isinstance(value, LambdaExpr):
            return
        if not self._contains_environment_callable(expected_type, value, provenance):
            return
        raise CodegenError(
            f"Environment-requiring callable value cannot cross {boundary}; bare __fn_ptr has no tagged receiver or closure environment"
        )

    def _contains_environment_callable(
        self, expected_type: TypeExpr | None, value: object | None, provenance: CallableProvenance
    ) -> bool:
        if value is None:
            return False
        expected = self._values.canonical(expected_type)
        if expected is None:
            return provenance.requires_environment(value)
        if self.is_callable(expected):
            return provenance.requires_environment(value)
        slots = provenance.literal_slots(expected, value)
        if slots is not None:
            return self._environment_slots_contain(slots, provenance)
        return provenance.requires_environment(value)

    def _environment_slots_contain(self, slots, provenance: CallableProvenance) -> bool:
        """Check aggregate closure environments in persistent source flow."""
        flow = provenance.snapshot()
        for slot_type, element in slots:
            with provenance.at_flow(flow):
                if self._contains_environment_callable(slot_type, element, provenance):
                    return True
                flow = provenance.plan_evaluation((element,)).outgoing
        return False

    def _unsafe_slots_contain(self, slots, provenance: CallableProvenance) -> bool:
        """Check aggregate managed callbacks in persistent source flow."""
        flow = provenance.snapshot()
        for slot_type, element in slots:
            with provenance.at_flow(flow):
                if self._contains_unsafe_managed_callback(slot_type, element, provenance):
                    return True
                flow = provenance.plan_evaluation((element,)).outgoing
        return False

    def _contains_unsafe_managed_callback(
        self, expected_type: TypeExpr | None, value: object | None, provenance: CallableProvenance
    ) -> bool:
        if value is None:
            return False
        expected = self._values.canonical(expected_type)
        if expected is None:
            return self._contains_callable_value(value, provenance, managed=True)
        if expected.base == "bool" and expected.pointer_depth == 0:
            return False
        if self.is_managed_callable(expected):
            return provenance.evaluated_return_abi(value) is not CallableReturnABI.BORROWED
        slots = provenance.literal_slots(expected, value)
        if slots is not None:
            return self._unsafe_slots_contain(slots, provenance)
        if self._erases_managed_callable_value(expected, value, provenance):
            return True
        if self._is_validated_reference_owner(expected):
            return False
        return self._type_contains_managed_callback(expected, provenance)

    def _contains_callable_value(
        self, expression: object | None, provenance: CallableProvenance, *, managed: bool
    ) -> bool:
        if expression is None:
            return False
        type_expr = self._values.canonical(provenance.type_of(expression))
        if self.is_managed_callable(type_expr) if managed else self.is_callable(type_expr):
            return True
        if isinstance(expression, CastExpr):
            return self._contains_callable_value(expression.expr, provenance, managed=managed)
        if isinstance(expression, UnaryExpr) and expression.op in {"&", "*"}:
            return self._contains_callable_value(expression.operand, provenance, managed=managed)
        if isinstance(expression, AssignExpr):
            return self._contains_callable_value(expression.value, provenance, managed=managed)
        if isinstance(expression, TernaryExpr):
            return self._contains_callable_value(
                expression.true_expr, provenance, managed=managed
            ) or self._contains_callable_value(expression.false_expr, provenance, managed=managed)
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return self._contains_callable_value(
                expression.left, provenance, managed=managed
            ) or self._contains_callable_value(expression.right, provenance, managed=managed)
        if isinstance(expression, (BraceInitializer, ListLiteral, TupleLiteral)):
            return any(
                self._contains_callable_value(element, provenance, managed=managed) for element in expression.elements
            )
        if isinstance(expression, MapLiteral):
            return any(
                self._contains_callable_value(entry.key, provenance, managed=managed)
                or self._contains_callable_value(entry.value, provenance, managed=managed)
                for entry in expression.entries
            )
        return False

    def _erases_managed_callable_value(
        self, expected_type: object | None, value: object | None, provenance: CallableProvenance
    ) -> bool:
        if value is None:
            return False
        expected = self._values.canonical(expected_type)
        if expected is not None and expected.base == "bool" and expected.pointer_depth == 0 and not expected.is_array:
            return False
        if expected is not None and self.is_managed_callable(expected):
            return False
        slots = provenance.literal_slots(expected, value) if expected is not None else None
        if slots is not None:
            return any(
                self._erases_managed_callable_value(slot_type, element, provenance) for slot_type, element in slots
            )
        return self._contains_callable_value(value, provenance, managed=True)

    def _is_storage_expression(self, expression: object, provenance: CallableProvenance) -> bool:
        if isinstance(expression, Identifier):
            return bool(provenance.is_local(expression.name) or expression.name in self._analyzed.global_var_types)
        if isinstance(expression, (FieldAccessExpr, IndexExpr)):
            return True
        return bool(isinstance(expression, UnaryExpr) and expression.op == "*")

    def _is_validated_reference_owner(self, expected_type: TypeExpr | None) -> bool:
        expected = self._values.canonical(expected_type)
        return bool(
            expected is not None and (expected.pointer_depth > 0 or expected.base in self._analyzed.class_table)
        )

    def _type_contains_managed_callback(
        self,
        expected_type: TypeExpr | None,
        provenance: CallableProvenance,
        seen: frozenset[tuple] = frozenset(),
    ) -> bool:
        expected = self._values.canonical(expected_type)
        if expected is None:
            return False
        if self.is_managed_callable(expected):
            return True
        if self._is_validated_reference_owner(expected):
            return False
        key = self._type_identity.shape_key(expected)
        if key in seen:
            return False
        seen = seen | {key}
        if expected.is_array:
            from src.compiler.python.analyzer.types import TypeSystem

            return self._type_contains_managed_callback(
                TypeSystem.strip_outer_storage(expected, array=True), provenance, seen
            )
        if expected.pointer_depth > 0:
            return False
        if expected.base in {"Array", "List", "Set", "Vector"}:
            return bool(
                len(expected.generic_args) == 1
                and self._type_contains_managed_callback(expected.generic_args[0], provenance, seen)
            )
        if expected.base in {"Map", "Tuple"}:
            return any(
                self._type_contains_managed_callback(argument, provenance, seen) for argument in expected.generic_args
            )
        declaration = provenance.struct_declaration(expected)
        return bool(
            declaration is not None
            and any(self._type_contains_managed_callback(field.type, provenance, seen) for field in declaration.fields)
        )


class CallableReturnABI(StrEnum):
    """Ownership convention used by a managed-return function pointer."""

    BORROWED = "borrowed"
    OWNED = "owned"
    AMBIGUOUS = "ambiguous"

    @classmethod
    def join(cls, left: CallableReturnABI, right: CallableReturnABI) -> CallableReturnABI:
        return left if left is right else cls.AMBIGUOUS


@dataclass(frozen=True, slots=True)
class CallableEnvironment:
    """The lifted function and stack environment behind a closure binding."""

    function_name: str
    variable_name: str


@dataclass(frozen=True, slots=True)
class CallableBinding:
    """Flow-sensitive metadata for one lexical callable binding."""

    type_expr: TypeExpr
    return_abi: CallableReturnABI
    environment: CallableEnvironment | None = None


@dataclass(frozen=True, slots=True)
class CallableFlowSnapshot:
    """One immutable-by-contract callable dataflow state."""

    bindings: dict[str, CallableBinding]


@dataclass(slots=True)
class CallableFlowIsolation:
    """One explicit branch flow isolated from its incoming state."""

    incoming: CallableFlowSnapshot
    outgoing: CallableFlowSnapshot | None = None


@dataclass(frozen=True, slots=True)
class CallableCallEffect:
    """The exact managed-result ABI observed before lowering call operands."""

    call_id: int
    return_abi: CallableReturnABI
    returns_owned: bool


@dataclass(frozen=True, slots=True)
class CallableEvaluationPlan:
    """Entry state per evaluated AST node and the sequence's outgoing state."""

    incoming: CallableFlowSnapshot
    entries: dict[int, CallableFlowSnapshot]
    outgoing: CallableFlowSnapshot


@dataclass(slots=True)
class CallableLexicalScope:
    """Declarations and displaced bindings owned by one lexical block."""

    declared: set[str]
    shadowed: dict[str, CallableBinding | None]


@dataclass(slots=True)
class ExceptionalCallableCapture:
    """Callable states visible to exceptional exits from one try region."""

    entry_bindings: dict[str, CallableBinding]
    scope_depth: int
    states: list[CallableFlowSnapshot]


@dataclass(slots=True)
class LoopCallableCapture:
    """Callable states reaching the active loop's structured exits."""

    entry_bindings: dict[str, CallableBinding]
    scope_depth: int
    break_states: list[CallableFlowSnapshot]
    continue_states: list[CallableFlowSnapshot]


@dataclass(slots=True)
class SwitchCallableCapture:
    """Callable states that leave one switch through a structured break."""

    entry_bindings: dict[str, CallableBinding]
    scope_depth: int
    break_states: list[CallableFlowSnapshot]


@dataclass(slots=True)
class CallableMutationCapture:
    """Callable bindings that a lowered region may explicitly rebind."""

    names: set[str]


@dataclass(frozen=True, slots=True)
class CallableLoopFlow:
    """Edge-specific callable states produced by one lowered loop body."""

    head: CallableFlowSnapshot
    break_states: tuple[CallableFlowSnapshot, ...]
    backedge_states: tuple[CallableFlowSnapshot, ...]


@dataclass(frozen=True, slots=True)
class LoopConditionReachability:
    """The statically reachable exits from one loop condition."""

    can_exit: bool
    can_repeat: bool


class CallableSignatureLowerer:
    """Own immutable source-callable naming and C parameter representation."""

    def __init__(self, analyzed: AnalyzedProgram, types: CTypeLowerer) -> None:
        self._analyzed = analyzed
        self._types = types

    def source_binding_c_name(self, name: str) -> str:
        """Return a C binding name that cannot collide with a source type."""
        if name in HOSTED_ABI.macros or self._binding_conflicts_with_type(name):
            return f"__btrc_source_{name}"
        return name

    def _binding_conflicts_with_type(self, name: str) -> bool:
        if name in HOSTED_ABI.typedefs:
            return True
        tables = (
            self._analyzed.class_table,
            self._analyzed.interface_table,
            self._analyzed.struct_table,
            self._analyzed.typedef_table,
            self._analyzed.enum_table,
            self._analyzed.rich_enum_table,
        )
        if any(name in table for table in tables):
            return True
        return any(
            name in info.generic_params
            for table in (self._analyzed.class_table, self._analyzed.interface_table)
            for info in table.values()
        ) or any(
            name in method.generic_params
            for info in self._analyzed.class_table.values()
            for method in info.methods.values()
        )

    def source_function_c_name(self, name: str, call=None) -> str:
        """Return the isolated C symbol for a concrete source function."""
        declaration = self._analyzed.function_table.get(name)
        if declaration is None or declaration.body is None or declaration.is_gpu:
            return name
        if call is not None and id(call) in self._analyzed.hosted_call_ids:
            return name
        return HOSTED_ABI.source_function_symbol(name)

    def lower_source_param(self, parameter, *, resolved_type=None) -> IRParam:
        return self.lower_named_source_type_param(
            parameter.type,
            self._types.render(parameter.type),
            parameter.name,
            resolved_type=resolved_type,
        )

    def lower_named_source_type_param(
        self,
        type_expr,
        c_type,
        name,
        *,
        resolved_type=None,
    ) -> IRParam:
        represented_type = resolved_type or type_expr
        return IRParam(
            c_type=c_type if isinstance(c_type, CType) else CType(text=c_type),
            name=self.source_binding_c_name(name),
            is_volatile=bool(represented_type and represented_type.is_volatile),
            effective_is_volatile=StorageModel.effective_outer_volatile(
                represented_type,
                self._analyzed.typedef_table,
            ),
        )


class CallableProvenance:
    """Own callable bindings and their abstract flow for one emitted function."""

    def __init__(
        self,
        analyzed: AnalyzedProgram,
        session: LoweringSession,
        types: CTypeLowerer,
        signatures: CallableSignatureLowerer,
    ) -> None:
        self._analyzed = analyzed
        self._session = session
        self._types = types
        self._signatures = signatures
        self._bindings: dict[str, CallableBinding] = {}
        self._scopes: list[CallableLexicalScope] = []
        self._exception_captures: list[ExceptionalCallableCapture] = []
        self._loop_captures: list[LoopCallableCapture] = []
        self._switch_captures: list[SwitchCallableCapture] = []
        self._mutation_captures: list[CallableMutationCapture] = []
        self._observer_suppression_depth = 0
        self._declaration_scope_bases: list[int] = []

    def type_of(self, expression: object) -> TypeExpr | None:
        return self._session.type_of(expression)

    def is_local(self, name: str) -> bool:
        if self._declaration_scope_bases:
            scopes = self._scopes[self._declaration_scope_bases[-1] :]
            external = False
        else:
            scopes = self._scopes
            external = self._session.local_is_declared(name)
        return bool(external or any(name in scope.declared for scope in reversed(scopes)))

    def source_binding_c_name(self, name: str) -> str:
        return self._signatures.source_binding_c_name(name)

    def source_field_c_name(self, receiver, name: str) -> str:
        """Return the generated field name for a rich-enum payload slot."""
        if name not in HOSTED_ABI.macros:
            return name
        if not isinstance(receiver, FieldAccessExpr):
            return name
        data_access = receiver.obj
        if not isinstance(data_access, FieldAccessExpr) or data_access.field != "data":
            return name
        root = data_access.obj
        root_type = self.type_of(root)
        declaration = self._analyzed.rich_enum_table.get(root_type.base) if root_type is not None else None
        if declaration is None:
            return name
        variant = next(
            (item for item in declaration.variants if item.name == receiver.field),
            None,
        )
        if variant is None or all(parameter.name != name for parameter in variant.params):
            return name
        return self.source_binding_c_name(name)

    def source_function_c_name(self, name: str, call=None) -> str:
        return self._signatures.source_function_c_name(name, call)

    def lower_source_param(self, parameter, *, resolved_type=None) -> IRParam:
        return self._signatures.lower_source_param(parameter, resolved_type=resolved_type)

    def lower_named_source_type_param(
        self,
        type_expr,
        c_type,
        name,
        *,
        resolved_type=None,
    ) -> IRParam:
        return self._signatures.lower_named_source_type_param(
            type_expr,
            c_type,
            name,
            resolved_type=resolved_type,
        )

    def environment(self, name: str) -> CallableEnvironment | None:
        binding = self._bindings.get(name)
        return binding.environment if binding is not None else None

    def return_abi_for_name(self, name: str) -> CallableReturnABI:
        binding = self._bindings.get(name)
        return binding.return_abi if binding is not None else CallableReturnABI.BORROWED

    def begin_scope(self) -> CallableLexicalScope:
        scope = CallableLexicalScope(declared=set(), shadowed={})
        self._scopes.append(scope)
        return scope

    def finish_scope(self, scope: CallableLexicalScope) -> None:
        if not self._scopes or self._scopes[-1] is not scope:
            raise RuntimeError("callable lexical scopes must be properly nested")
        self._scopes.pop()
        result = self._bindings.copy()
        for name in scope.declared:
            displaced = scope.shadowed[name]
            if displaced is None:
                result.pop(name, None)
            else:
                result[name] = displaced
        self._bindings = result

    def bind_local(self, name: str, type_expr: TypeExpr | None, initializer: object | None) -> None:
        self._declare(name)
        resolved = self._canonical(type_expr)
        if not self._is_callable_type(resolved):
            self._bindings.pop(name, None)
            return
        self._bindings[name] = CallableBinding(
            type_expr=resolved,
            return_abi=self.return_abi(initializer) if initializer is not None else CallableReturnABI.BORROWED,
        )

    def bind_borrowed(self, name: str, type_expr: TypeExpr | None) -> None:
        self.bind_local(name, type_expr, None)

    def bind_with_abi(self, name: str, type_expr: TypeExpr | None, return_abi: CallableReturnABI) -> None:
        if not isinstance(return_abi, CallableReturnABI):
            raise ValueError(f"invalid callable return ABI: {return_abi!r}")
        self.bind_local(name, type_expr, None)
        binding = self._bindings.get(name)
        if binding is not None:
            self._bindings[name] = replace(binding, return_abi=return_abi)

    def shadow(self, name: str) -> None:
        self._declare(name)
        self._bindings.pop(name, None)

    def rebind_assignment(self, assignment: AssignExpr) -> None:
        if assignment.op != "=" or not isinstance(assignment.target, Identifier):
            return
        name = assignment.target.name
        binding = self._bindings.get(name)
        if binding is None:
            return
        resolved = self._canonical(self.type_of(assignment.target))
        if resolved is None:
            resolved = binding.type_expr
        if not self._is_callable_type(resolved):
            return
        self._bindings[name] = CallableBinding(
            type_expr=resolved,
            return_abi=self.return_abi(assignment.value),
            environment=self._expression_environment(assignment.value),
        )
        self._record_mutation(name)
        self.record_exceptional_flow()

    def is_callable(self, type_expr: TypeExpr | None) -> bool:
        """Return whether a type is one scalar bare function-pointer value."""
        resolved = self._canonical(type_expr)
        return bool(
            resolved is not None
            and resolved.base == "__fn_ptr"
            and resolved.pointer_depth == 0
            and not resolved.is_array
        )

    def requires_environment(self, expression: object | None) -> bool:
        """Return whether a callable expression needs state beyond a bare pointer."""
        if isinstance(expression, LambdaExpr):
            return bool(expression.captures)
        if isinstance(expression, Identifier):
            return self.environment(expression.name) is not None
        if isinstance(expression, FieldAccessExpr):
            return self._is_bound_instance_method(expression)
        if isinstance(expression, CastExpr):
            return self.requires_environment(expression.expr)
        if isinstance(expression, UnaryExpr) and expression.op in {"&", "*"}:
            return self.requires_environment(expression.operand)
        if isinstance(expression, AssignExpr):
            return self.requires_environment(expression.value)
        if isinstance(expression, TernaryExpr):
            return self.requires_environment(expression.true_expr) or self.requires_environment(expression.false_expr)
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return self.requires_environment(expression.left) or self.requires_environment(expression.right)
        return False

    def literal_slots(self, expected_type: object, value: object):
        """Return contextual aggregate slots, or ``None`` for a scalar value."""
        expected = self._canonical(expected_type)
        if expected is None:
            return None
        if isinstance(value, (BraceInitializer, ListLiteral)):
            if expected.is_array:
                element_type = TypeSystem.strip_outer_storage(expected, array=True)
                return tuple((element_type, element) for element in value.elements)
            if expected.base in {"Array", "List", "Set", "Vector"} and len(expected.generic_args) == 1:
                return tuple((expected.generic_args[0], element) for element in value.elements)
            if expected.base == "Tuple":
                return tuple(zip(expected.generic_args, value.elements))
            declaration = self.struct_declaration(expected)
            if declaration is not None:
                return tuple(zip((field.type for field in declaration.fields), value.elements))
        if isinstance(value, TupleLiteral) and expected.base == "Tuple":
            return tuple(zip(expected.generic_args, value.elements))
        if isinstance(value, MapLiteral) and expected.base == "Map" and len(expected.generic_args) == 2:
            key_type, value_type = expected.generic_args
            return tuple(slot for entry in value.entries for slot in ((key_type, entry.key), (value_type, entry.value)))
        return None

    def struct_declaration(self, expected_type: object):
        """Return a complete by-value struct declaration for a source type."""
        expected = self._canonical(expected_type)
        if expected is None or expected.pointer_depth > 0:
            return None
        declaration = self._analyzed.struct_table.get(expected.base.removeprefix("struct "))
        if declaration is None or declaration.is_forward:
            return None
        return declaration

    def _canonical(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        return self._types.canonical_type(type_expr)

    def _is_bound_instance_method(self, expression: FieldAccessExpr) -> bool:
        receiver = expression.obj
        if isinstance(receiver, Identifier) and not self.is_local(receiver.name):
            static_owner = self._analyzed.class_table.get(receiver.name)
            if static_owner is not None:
                method = static_owner.methods.get(expression.field)
                return bool(method is not None and method.access != "class")
        receiver_type = self._canonical(self.type_of(receiver))
        if receiver_type is None:
            return False
        class_info = self._analyzed.class_table.get(receiver_type.base)
        if class_info is not None:
            if expression.field in class_info.fields or expression.field in class_info.properties:
                return False
            method = class_info.methods.get(expression.field)
            if method is not None:
                return method.access != "class"
        interface_info = self._analyzed.interface_table.get(receiver_type.base)
        if interface_info is not None and expression.field in interface_info.methods:
            return True
        return bool(
            (receiver_type.base == "Thread" and expression.field == "join")
            or (receiver_type.base == "Mutex" and expression.field in {"get", "set", "destroy"})
            or receiver_type.base == "string"
        )

    def return_abi(self, expression: object | None) -> CallableReturnABI:
        if isinstance(expression, LambdaExpr):
            return CallableReturnABI.OWNED
        if isinstance(expression, Identifier):
            binding = self._bindings.get(expression.name)
            if binding is not None:
                return binding.return_abi
            if self.is_local(expression.name):
                return CallableReturnABI.BORROWED
            declaration = self._analyzed.function_table.get(expression.name)
            if declaration is not None and declaration.body is not None:
                return CallableReturnABI.OWNED
            return CallableReturnABI.BORROWED
        if isinstance(expression, FieldAccessExpr):
            declaration = self._source_static_method(expression)
            if declaration is not None and declaration.body is not None:
                return CallableReturnABI.OWNED
        if isinstance(expression, CastExpr):
            return self.return_abi(expression.expr)
        if isinstance(expression, UnaryExpr) and expression.op in {"&", "*"}:
            return self.return_abi(expression.operand)
        if isinstance(expression, AssignExpr):
            return self.return_abi(expression.value)
        if isinstance(expression, TernaryExpr):
            return CallableReturnABI.join(self.return_abi(expression.true_expr), self.return_abi(expression.false_expr))
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return CallableReturnABI.join(self.return_abi(expression.left), self.return_abi(expression.right))
        return CallableReturnABI.BORROWED

    def evaluated_return_abi(self, expression: object | None) -> CallableReturnABI:
        """Classify a value after its own source-ordered side effects.

        The transaction is provenance-only: real lowering still emits and
        applies the expression exactly once. This lets pre-lowering ownership
        boundaries inspect the value at the semantic point where it exists.
        """
        incoming = self.snapshot()
        try:
            with self._without_flow_observers():
                return self._evaluate_expression(expression)
        finally:
            self.restore(incoming)

    def plan_evaluation(self, expressions: Iterable[object]) -> CallableEvaluationPlan:
        """Model one source-ordered operand sequence without emitting it."""
        incoming = self.snapshot()
        entries: dict[int, CallableFlowSnapshot] = {}
        try:
            with self._without_flow_observers():
                for expression in expressions:
                    self._evaluate_expression(expression, entries)
                outgoing = self.snapshot()
        finally:
            self.restore(incoming)
        return CallableEvaluationPlan(incoming, entries, outgoing)

    @contextmanager
    def at_flow(self, state: CallableFlowSnapshot):
        """Run nested planning in an explicit abstract-flow entry state."""
        current = self.snapshot()
        self.restore(state)
        try:
            yield
        finally:
            self.restore(current)

    def conditional_branch_entries(
        self, expression: object
    ) -> tuple[
        tuple[object, CallableFlowSnapshot],
        tuple[object, CallableFlowSnapshot],
    ]:
        """Return each conditional branch with its abstract entry flow."""
        incoming = self.snapshot()
        try:
            with self._without_flow_observers():
                if isinstance(expression, TernaryExpr):
                    self._evaluate_expression(expression.condition)
                    branch_entry = self.snapshot()
                    return (
                        (expression.true_expr, branch_entry),
                        (expression.false_expr, branch_entry),
                    )
                if isinstance(expression, BinaryExpr) and expression.op == "??":
                    left_entry = self.snapshot()
                    self._evaluate_expression(expression.left)
                    right_entry = self.snapshot()
                    return (
                        (expression.left, left_entry),
                        (expression.right, right_entry),
                    )
                raise TypeError("conditional callable facts require ternary or null-coalescing expression")
        finally:
            self.restore(incoming)

    def capture_call_effect(self, expression: CallExpr) -> CallableCallEffect:
        """Freeze the callee ABI before any argument can mutate its binding."""
        return_abi = self.evaluated_return_abi(expression.callee)
        return CallableCallEffect(
            call_id=id(expression),
            return_abi=return_abi,
            returns_owned=self._call_returns_owned(expression, return_abi),
        )

    def call_returns_owned(self, expression: CallExpr, effect: CallableCallEffect | None = None) -> bool:
        """Whether a call uses btrc's caller-owned managed-result ABI."""
        if effect is None:
            effect = self.capture_call_effect(expression)
        if effect.call_id != id(expression):
            raise ValueError("callable call effect does not belong to this call")
        return effect.returns_owned

    def _evaluate_expression(
        self, expression: object | None, entries: dict[int, CallableFlowSnapshot] | None = None
    ) -> CallableReturnABI:
        """Apply only callable-binding effects in language evaluation order."""
        if expression is None:
            return CallableReturnABI.BORROWED
        if entries is not None:
            entries.setdefault(id(expression), self.snapshot())
        if isinstance(expression, AssignExpr):
            self._evaluate_assignment_target(expression.target, entries)
            value_abi = self._evaluate_expression(expression.value, entries)
            if expression.op == "=" and isinstance(expression.target, Identifier):
                binding = self._bindings.get(expression.target.name)
                if binding is not None:
                    resolved = self._canonical(self.type_of(expression.target))
                    self._bindings[expression.target.name] = CallableBinding(
                        type_expr=resolved or binding.type_expr,
                        return_abi=value_abi,
                        environment=self._expression_environment(expression.value),
                    )
                    self._record_mutation(expression.target.name)
                    self.record_exceptional_flow()
            return value_abi
        if isinstance(expression, TernaryExpr):
            self._evaluate_expression(expression.condition, entries)
            branch_entry = self.snapshot()
            true_abi = self._evaluate_expression(expression.true_expr, entries)
            true_flow = self.snapshot()
            self.restore(branch_entry)
            false_abi = self._evaluate_expression(expression.false_expr, entries)
            false_flow = self.snapshot()
            self.join_flows(true_flow, false_flow)
            return CallableReturnABI.join(true_abi, false_abi)
        if isinstance(expression, BinaryExpr):
            left_abi = self._evaluate_expression(expression.left, entries)
            if expression.op in {"??", "&&", "||"}:
                skipped = self.snapshot()
                right_abi = self._evaluate_expression(expression.right, entries)
                executed = self.snapshot()
                self.join_flows(skipped, executed)
                if expression.op == "??":
                    return CallableReturnABI.join(left_abi, right_abi)
                return CallableReturnABI.BORROWED
            self._evaluate_expression(expression.right, entries)
            return CallableReturnABI.BORROWED
        if isinstance(expression, CastExpr):
            return self._evaluate_expression(expression.expr, entries)
        if isinstance(expression, UnaryExpr):
            return self._evaluate_expression(expression.operand, entries)
        if isinstance(expression, CallExpr):
            self._evaluate_expression(expression.callee, entries)
            if isinstance(expression.callee, FieldAccessExpr) and expression.callee.optional:
                skipped = self.snapshot()
                for argument in expression.args:
                    self._evaluate_expression(argument, entries)
                executed = self.snapshot()
                self.join_flows(skipped, executed)
                return self.return_abi(expression)
            for argument in expression.args:
                self._evaluate_expression(argument, entries)
            return self.return_abi(expression)
        if isinstance(expression, NewExpr):
            for argument in expression.args:
                self._evaluate_expression(argument, entries)
            return self.return_abi(expression)
        if isinstance(expression, SpawnExpr):
            self._evaluate_expression(expression.fn, entries)
            return CallableReturnABI.BORROWED
        if isinstance(expression, FieldAccessExpr):
            self._evaluate_expression(expression.obj, entries)
            return self.return_abi(expression)
        if isinstance(expression, IndexExpr):
            self._evaluate_expression(expression.obj, entries)
            self._evaluate_expression(expression.index, entries)
            return self.return_abi(expression)
        if isinstance(expression, (BraceInitializer, ListLiteral, TupleLiteral)):
            for element in expression.elements:
                self._evaluate_expression(element, entries)
            return CallableReturnABI.BORROWED
        if isinstance(expression, MapLiteral):
            for entry in expression.entries:
                self._evaluate_expression(entry.key, entries)
                self._evaluate_expression(entry.value, entries)
            return CallableReturnABI.BORROWED
        if isinstance(expression, FStringLiteral):
            for part in expression.parts:
                if isinstance(part, FStringExpr):
                    self._evaluate_expression(part.expression, entries)
            return CallableReturnABI.BORROWED
        return self.return_abi(expression)

    def _evaluate_assignment_target(
        self, target: object, entries: dict[int, CallableFlowSnapshot] | None = None
    ) -> None:
        if isinstance(target, FieldAccessExpr):
            self._evaluate_expression(target.obj, entries)
        elif isinstance(target, IndexExpr):
            self._evaluate_expression(target.obj, entries)
            self._evaluate_expression(target.index, entries)
        elif isinstance(target, UnaryExpr) and target.op == "*":
            self._evaluate_expression(target.operand, entries)

    def _call_returns_owned(self, expression: CallExpr, return_abi: CallableReturnABI) -> bool:
        callee = expression.callee
        if isinstance(callee, Identifier) and id(expression) in self._analyzed.hosted_call_ids:
            return False
        if return_abi is CallableReturnABI.AMBIGUOUS:
            raise CodegenError(
                "Managed-return __fn_ptr call has ambiguous ownership ABI after control flow; keep source and foreign callbacks in separate bindings"
            )
        if return_abi is CallableReturnABI.OWNED:
            return True
        if isinstance(callee, Identifier):
            if self.is_local(callee.name):
                return False
            declaration = self._analyzed.function_table.get(callee.name)
            return bool(
                (callee.name == "Mutex" and declaration is None)
                or callee.name in self._analyzed.class_table
                or (declaration is not None and declaration.body is not None)
            )
        if not isinstance(callee, FieldAccessExpr):
            return False
        receiver = callee.obj
        if isinstance(receiver, Identifier) and (not self.is_local(receiver.name)):
            static_info = self._analyzed.class_table.get(receiver.name)
            if static_info is not None:
                static_method = static_info.methods.get(callee.field)
                if static_method is not None:
                    return bool(static_method.body is not None)
        receiver_type = self._canonical(self.type_of(receiver))
        if receiver_type is None:
            return False
        if receiver_type.base == "Thread" and callee.field == "join":
            return True
        if receiver_type.base == "Mutex" and callee.field == "get":
            return True
        class_info = self._analyzed.class_table.get(receiver_type.base)
        if class_info is not None and callee.field in class_info.methods:
            return True
        interface_info = self._analyzed.interface_table.get(receiver_type.base)
        return bool(interface_info is not None and callee.field in interface_info.methods)

    def snapshot(self) -> CallableFlowSnapshot:
        return CallableFlowSnapshot(self._bindings.copy())

    def restore(self, state: CallableFlowSnapshot) -> None:
        self._bindings = state.bindings.copy()

    def join_flows(self, *states: CallableFlowSnapshot) -> None:
        if not states:
            return
        keys = set().union(*(state.bindings.keys() for state in states))
        joined: dict[str, CallableBinding] = {}
        for name in keys:
            if any(name not in state.bindings for state in states):
                raise RuntimeError("callable flow join received mismatched lexical bindings")
            present = [state.bindings[name] for state in states]
            abis = {state.bindings[name].return_abi for state in states}
            environments = {state.bindings[name].environment for state in states}
            joined[name] = replace(
                present[0],
                return_abi=next(iter(abis)) if len(abis) == 1 else CallableReturnABI.AMBIGUOUS,
                environment=next(iter(environments)) if len(environments) == 1 else None,
            )
        self._bindings = joined

    def merge_flows(self, *states: CallableFlowSnapshot) -> CallableFlowSnapshot:
        """Return a joined state without changing the current owner state."""
        if not states:
            return self.snapshot()
        current = self.snapshot()
        try:
            self.join_flows(*states)
            return self.snapshot()
        finally:
            self.restore(current)

    def begin_mutation_capture(self) -> CallableMutationCapture:
        capture = CallableMutationCapture(names=set())
        self._mutation_captures.append(capture)
        return capture

    def finish_mutation_capture(self, capture: CallableMutationCapture) -> frozenset[str]:
        if not self._mutation_captures or self._mutation_captures[-1] is not capture:
            raise RuntimeError("callable mutation captures must be properly nested")
        self._mutation_captures.pop()
        return frozenset(capture.names)

    def project_mutations(
        self, *, all_result: CallableFlowSnapshot, continuation_entry: CallableFlowSnapshot, mutated: Iterable[str]
    ) -> CallableFlowSnapshot:
        """Apply one lowered region's conservative transfer to live entries."""
        bindings = continuation_entry.bindings.copy()
        for name in mutated:
            if name in all_result.bindings:
                bindings[name] = all_result.bindings[name]
            else:
                bindings.pop(name, None)
        return CallableFlowSnapshot(bindings)

    def complete_loop(
        self,
        flow: CallableLoopFlow,
        *,
        backedge_states: Iterable[CallableFlowSnapshot] | None = None,
        condition_can_exit: bool,
        condition_can_repeat: bool = True,
    ) -> None:
        """Prove loop-head invariance and install only reachable loop edges.

        A pre-test loop whose condition is the direct literal ``false`` (or
        zero) still has its body lowered, but none of that body's abstract
        callable-flow edges are reachable.  Dynamic and true conditions keep
        the conservative repeated-edge proof.
        """
        backedges = (
            tuple(flow.backedge_states if backedge_states is None else backedge_states) if condition_can_repeat else ()
        )
        for state in backedges:
            self.require_loop_edge_invariant(flow.head, state, edge="back-edge")
        exits = [*flow.break_states] if condition_can_repeat else []
        if condition_can_exit:
            exits.append(flow.head)
        if exits:
            self.join_flows(*exits)
        else:
            self.restore(flow.head)

    def complete_do_while(
        self,
        flow: CallableLoopFlow,
        *,
        condition_flow: CallableFlowSnapshot | None,
        condition_reachability: LoopConditionReachability,
    ) -> None:
        """Complete a loop whose body has one guaranteed first execution.

        ``condition_flow`` exists only when a reachable fallthrough or
        ``continue`` edge evaluates the condition.  A literal-false condition
        cannot return to the body, so that first iteration may establish a new
        callable ABI.  Conditions that may repeat remain fail-closed because
        the emitted body must be valid for both its first and later entries.
        """
        if condition_flow is not None and condition_reachability.can_repeat:
            self.require_loop_edge_invariant(flow.head, condition_flow, edge="condition edge")
        exits = [*flow.break_states]
        if condition_flow is not None and condition_reachability.can_exit:
            exits.append(condition_flow)
        if exits:
            self.join_flows(*exits)
        else:
            self.restore(flow.head)

    @classmethod
    def condition_reachability(cls, expression: object) -> LoopConditionReachability:
        """Return the condition edges reachable from a direct literal."""
        if isinstance(expression, BoolLiteral):
            return LoopConditionReachability(can_exit=not expression.value, can_repeat=expression.value)
        if isinstance(expression, IntLiteral):
            can_repeat = expression.value != 0
            return LoopConditionReachability(can_exit=not can_repeat, can_repeat=can_repeat)
        return LoopConditionReachability(can_exit=True, can_repeat=True)

    def require_loop_edge_invariant(
        self, expected: CallableFlowSnapshot, actual: CallableFlowSnapshot, *, edge: str
    ) -> None:
        """Reject an edge whose callable representation changes the loop head."""
        if actual.bindings == expected.bindings:
            return
        changed = sorted(
            name
            for name in expected.bindings.keys() | actual.bindings.keys()
            if expected.bindings.get(name) != actual.bindings.get(name)
        )
        names = ", ".join(changed) or "<unknown>"
        raise CodegenError(
            f"Callable ownership ABI must be invariant across a repeated loop {edge}; changed binding(s): {names}"
        )

    @contextmanager
    def isolated_flow(self):
        """Isolate one explicitly traversed branch and expose its exit flow."""
        isolation = CallableFlowIsolation(incoming=self.snapshot())
        try:
            yield isolation
        finally:
            isolation.outgoing = self.snapshot()
            self.restore(isolation.incoming)

    def begin_exception_capture(self) -> ExceptionalCallableCapture:
        capture = ExceptionalCallableCapture(
            entry_bindings=self._bindings.copy(), scope_depth=len(self._scopes), states=[]
        )
        self._exception_captures.append(capture)
        self.record_exceptional_flow()
        return capture

    def finish_exception_capture(self, capture: ExceptionalCallableCapture) -> list[CallableFlowSnapshot]:
        if not self._exception_captures or self._exception_captures[-1] is not capture:
            raise RuntimeError("callable exceptional-flow captures must be properly nested")
        self._exception_captures.pop()
        return capture.states

    def record_exceptional_flow(self) -> None:
        if self._observer_suppression_depth:
            return
        for capture in self._exception_captures:
            state = self._restricted_snapshot(capture.entry_bindings, capture.scope_depth)
            if not capture.states or capture.states[-1] != state:
                capture.states.append(state)

    def begin_loop_capture(self) -> LoopCallableCapture:
        capture = LoopCallableCapture(
            entry_bindings=self._bindings.copy(), scope_depth=len(self._scopes), break_states=[], continue_states=[]
        )
        self._loop_captures.append(capture)
        return capture

    def finish_loop_capture(
        self, capture: LoopCallableCapture
    ) -> tuple[list[CallableFlowSnapshot], list[CallableFlowSnapshot]]:
        if not self._loop_captures or self._loop_captures[-1] is not capture:
            raise RuntimeError("callable loop captures must be properly nested")
        self._loop_captures.pop()
        return (capture.break_states, capture.continue_states)

    def begin_switch_capture(self) -> SwitchCallableCapture:
        capture = SwitchCallableCapture(
            entry_bindings=self._bindings.copy(), scope_depth=len(self._scopes), break_states=[]
        )
        self._switch_captures.append(capture)
        return capture

    def finish_switch_capture(self, capture: SwitchCallableCapture) -> list[CallableFlowSnapshot]:
        if not self._switch_captures or self._switch_captures[-1] is not capture:
            raise RuntimeError("callable switch captures must be properly nested")
        self._switch_captures.pop()
        return capture.break_states

    def record_control_exit(self, kind: str, control_context: Iterable[str]) -> None:
        targets = {"loop", "switch"} if kind == "break" else {"loop"}
        target = next((candidate for candidate in reversed(tuple(control_context)) if candidate in targets), None)
        if target == "switch":
            if not self._switch_captures:
                return
            capture = self._switch_captures[-1]
            state = self._restricted_snapshot(capture.entry_bindings, capture.scope_depth)
            if not capture.break_states or capture.break_states[-1] != state:
                capture.break_states.append(state)
            return
        if target != "loop" or not self._loop_captures:
            return
        capture = self._loop_captures[-1]
        state = self._restricted_snapshot(capture.entry_bindings, capture.scope_depth)
        states = capture.break_states if kind == "break" else capture.continue_states
        if not states or states[-1] != state:
            states.append(state)

    def _declare(self, name: str) -> None:
        if not self._scopes:
            return
        scope = self._scopes[-1]
        if name in scope.declared:
            return
        scope.declared.add(name)
        scope.shadowed[name] = self._bindings.get(name)

    def _record_mutation(self, name: str) -> None:
        if self._observer_suppression_depth:
            return
        for capture in self._mutation_captures:
            capture.names.add(name)

    @contextmanager
    def _without_flow_observers(self):
        """Keep abstract queries from publishing phantom control-flow facts."""
        self._observer_suppression_depth += 1
        try:
            yield
        finally:
            self._observer_suppression_depth -= 1

    def _source_static_method(self, expression: FieldAccessExpr):
        receiver = expression.obj
        if not isinstance(receiver, Identifier) or self.is_local(receiver.name):
            return None
        class_info = self._analyzed.class_table.get(receiver.name)
        if class_info is None:
            return None
        declaration = class_info.methods.get(expression.field)
        if declaration is None or declaration.access != "class":
            return None
        return declaration

    def _is_callable_type(self, type_expr: TypeExpr | None) -> bool:
        return self.is_callable(type_expr)

    def _expression_environment(self, expression: object) -> CallableEnvironment | None:
        if isinstance(expression, Identifier):
            return self.environment(expression.name)
        if isinstance(expression, CastExpr):
            return self._expression_environment(expression.expr)
        if isinstance(expression, UnaryExpr) and expression.op in {"&", "*"}:
            return self._expression_environment(expression.operand)
        if isinstance(expression, AssignExpr):
            return self._expression_environment(expression.value)
        return None

    def _restricted_snapshot(
        self, entry_bindings: dict[str, CallableBinding], scope_depth: int
    ) -> CallableFlowSnapshot:
        bindings: dict[str, CallableBinding] = {}
        active_scopes = self._scopes[scope_depth:]
        for name, entry in entry_bindings.items():
            binding = self._bindings.get(name, entry)
            for scope in reversed(active_scopes):
                if name in scope.declared:
                    binding = scope.shadowed[name]
            bindings[name] = binding if binding is not None else entry
        return CallableFlowSnapshot(bindings)


@dataclass(frozen=True)
class DefaultTarget:
    declaration: object
    c_name: str
    owner_name: str = ""
    class_prefix: str = ""
    self_type: TypeExpr | None = None
    substitutions: dict | None = None


@dataclass(frozen=True, slots=True)
class GenericDefaultHelperPlan:
    """A specialized default body awaiting ordinary function lowering."""

    target: DefaultTarget
    symbol: str
    parameters: tuple[object, ...]
    parameter_index: int
    helper_parameters: tuple[IRParam, ...]


@dataclass(frozen=True)
class PreparedValue:
    """A lowered value after target-directed conversion."""

    value: IRExpr
    effective_type: object
    owned: bool
    converted: bool = False


@dataclass(frozen=True, slots=True)
class ValuePreparationPlan:
    """Target-directed value facts resolved before expression traversal."""

    source: object
    source_type: TypeExpr | None
    target_type: TypeExpr | None
    hosted_mode: str | None
    source_owned: bool
    string_conversion: bool


@dataclass(frozen=True)
class PrintfArg:
    """A format fragment and the exact C expression it accepts."""

    format_spec: str
    value: IRExpr


@dataclass(frozen=True, slots=True)
class CallPlan:
    source: object
    callee: object
    operands: tuple[object, ...]
    argument_names: tuple[str | None, ...]
    declaration: object | None
    result_type: object | None


class CallLowerer:
    """Own calls lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        default_context: DefaultArgumentLoweringContext,
        type_identity: TypeIdentity,
        ownership: OwnershipLowerer,
        values: ManagedValueSemantics,
        operand_order: OwnershipOperandOrder,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._default_arguments = default_context
        self._type_identity = type_identity
        self._ownership = ownership
        self._values = values
        self._operand_order = operand_order
        self._default_argument_helpers: set[str] = set()

    def plan(self, node):
        declaration = None
        callee_name = getattr(node.callee, "name", None)
        if callee_name is not None:
            declaration = self._analyzed.function_table.get(callee_name)
        return CallPlan(
            source=node,
            callee=node.callee,
            operands=tuple(node.args),
            argument_names=tuple(argument.name for argument in node.args),
            declaration=declaration,
            result_type=self._session.type_of(node),
        )

    def plan_new(self, node: NewExpr, instance_type: TypeExpr) -> CallPlan:
        """Plan a constructor call without lowering any source operand."""
        return CallPlan(
            source=node,
            callee=self.constructor_symbol(instance_type),
            operands=tuple(node.args),
            argument_names=tuple(CallLowerer.arg_names_for(node, len(node.args))),
            declaration=self._analyzed.class_table.get(instance_type.base),
            result_type=instance_type,
        )

    def constructor_symbol(self, instance_type: TypeExpr) -> str:
        """Return the concrete constructor symbol for a resolved source type."""
        type_name = instance_type.base
        if instance_type.generic_args:
            type_name = self._type_identity.specialization_symbol(instance_type.base, instance_type.generic_args)
        return f"{type_name}_new"

    def materialize(self, plan, lowered_callee, lowered_operands):
        callee = lowered_callee
        if isinstance(callee, IRVar):
            callee = callee.name
        if not isinstance(callee, str):
            return IRCall(callee="__btrc_invoke", args=[callee, *lowered_operands])
        return IRCall(callee=callee, args=list(lowered_operands))

    @staticmethod
    def arg_names_for(node, count: int) -> list[str]:
        names = list(getattr(node, "arg_names", []) or [])
        while len(names) < count:
            names.append("")
        return names

    @staticmethod
    def bind_arg_nodes_to_params(
        params: list, ast_args: list, arg_names: list[str]
    ) -> list[tuple[int | None, object, bool]]:
        """Bind explicit arguments, then omitted defaults, without lowering.

        Explicit nodes stay in source evaluation order. Omitted defaults follow in
        parameter order. The boolean marks synthesized default arguments.
        """
        if not params:
            return [(None, argument, False) for argument in ast_args]
        names = list(arg_names or [])
        names.extend([""] * (len(ast_args) - len(names)))
        param_indices = {param.name: index for index, param in enumerate(params)}
        positional_index = 0
        bound: set[int] = set()
        result: list[tuple[int | None, object, bool]] = []
        for index, argument in enumerate(ast_args):
            name = names[index]
            if name:
                param_index = param_indices.get(name)
            else:
                param_index = positional_index
                positional_index += 1
            if param_index is not None and param_index < len(params):
                bound.add(param_index)
            result.append((param_index, argument, False))
        for index, param in enumerate(params):
            if index not in bound and param.default is not None:
                result.append((index, param.default, True))
        return result

    @staticmethod
    def reject_opaque_result_cleanup(call):
        raise CodegenError(
            f"opaque C call result at {call.line}:{call.col} cannot cross an ownership cleanup boundary; provide a typed declaration or exact hosted ABI contract"
        )

    @staticmethod
    def bound_nodes_by_parameter(params, bindings):
        """Return the explicit or default AST node supplying each parameter."""
        result = [None] * len(params)
        for param_index, node, _is_default in bindings:
            if param_index is not None and 0 <= param_index < len(result):
                result[param_index] = node
        return result

    def materialize_default_call(
        self,
        call,
        params,
        param_index,
        bound_nodes,
        overrides,
        provenance: CallableProvenance,
        *,
        receiver_node=None,
        receiver_value=None,
    ) -> IRCall:
        """Build a default helper call from explicit stabilized operands."""
        target, symbol = self.ensure_default_helper(
            call,
            params,
            param_index,
            provenance,
        )
        args = []
        if target.self_type is not None:
            value = receiver_value
            if value is None and receiver_node is not None:
                value = overrides.get(id(receiver_node))
            if value is None:
                CallLowerer._missing_dependency("method receiver")
            args.append(IRCast(target_type=CType(text=self._types.render(target.self_type)), expr=value))
        for prior_index in range(param_index):
            prior = bound_nodes[prior_index]
            value = overrides.get(id(prior)) if prior is not None else None
            if value is None:
                CallLowerer._missing_dependency(params[prior_index].name)
            prior_param = params[prior_index]
            source_type = (
                prior_param.type
                if prior is prior_param.default
                else self._default_arguments.resolve_type(self._session.type_of(prior))
            )
            args.append(self._types.upcast_class_pointer(prior_param.type, source_type, value))
        return IRCall(callee=symbol, args=args)

    @staticmethod
    def _missing_dependency(name):
        raise CodegenError(f"default argument dependency '{name}' was not evaluated before use")

    def ensure_default_helper(
        self, call, params, param_index: int, provenance: CallableProvenance
    ) -> tuple[DefaultTarget, str]:
        """Emit one typed evaluator and return its target metadata and symbol."""
        target = self._resolve_target(call, params, param_index, provenance)
        symbol = f"__btrc_default_{target.c_name}_{param_index + 1}"
        if symbol in self._default_argument_helpers:
            return (target, symbol)
        self._default_argument_helpers.add(symbol)
        param = params[param_index]
        helper_params = self._helper_params(
            target,
            params,
            param_index,
            provenance,
        )
        self._session.module.function_decls.append(
            IRFunctionDecl(
                name=symbol,
                return_type=CType(text=self._types.render(param.type)),
                params=list(helper_params),
                is_static=True,
            )
        )
        self._session.deferred_specializations.append(
            GenericDefaultHelperPlan(
                target=target,
                symbol=symbol,
                parameters=tuple(params),
                parameter_index=param_index,
                helper_parameters=tuple(helper_params),
            )
        )
        return (target, symbol)

    def _resolve_target(self, call, params, param_index: int, provenance: CallableProvenance) -> DefaultTarget:
        substitutions = dict(getattr(params[param_index], "default_type_map", None) or {})
        if isinstance(call, NewExpr):
            return self._constructor_target(call.type.base, substitutions)
        callee = call.callee if isinstance(call, CallExpr) else None
        if isinstance(callee, Identifier):
            class_info = self._analyzed.class_table.get(callee.name)
            if class_info is not None:
                return self._constructor_target(callee.name, substitutions)
            declaration = self._analyzed.function_table.get(callee.name)
            if declaration is not None:
                return DefaultTarget(
                    declaration=declaration,
                    c_name=provenance.source_function_c_name(declaration.name),
                    substitutions=substitutions,
                )
        if isinstance(callee, FieldAccessExpr):
            variant = self.rich_enum_variant_target(call)
            if variant is not None:
                enum_name, declaration = variant
                return DefaultTarget(
                    declaration=declaration, c_name=f"{enum_name}_{declaration.name}", substitutions=substitutions
                )
            class_info = self._receiver_class(callee)
            method = class_info.methods.get(callee.field) if class_info else None
            if method is not None:
                owner_name = class_info.method_owners.get(callee.field, class_info.name)
                owner = self._analyzed.class_table[owner_name]
                class_args = [substitutions[name] for name in owner.generic_params if name in substitutions]
                class_prefix = (
                    self._type_identity.specialization_symbol(owner_name, class_args) if class_args else owner_name
                )
                c_name = f"{class_prefix}_{method.name}"
                if method.generic_params:
                    method_args = tuple(substitutions[name] for name in method.generic_params)
                    c_name = self._type_identity.method_instance_symbol(
                        owner_name, tuple(class_args), method.name, method_args
                    )
                self_type = None
                if method.access != "class":
                    self_type = TypeExpr(base=owner_name, generic_args=class_args, pointer_depth=1)
                return DefaultTarget(
                    declaration=method,
                    c_name=c_name,
                    owner_name=owner_name,
                    class_prefix=class_prefix,
                    self_type=self_type,
                    substitutions=substitutions,
                )
        raise CodegenError("cannot resolve declaration scope for a default argument")

    def _constructor_target(self, class_name: str, substitutions: dict) -> DefaultTarget:
        owner = self._analyzed.class_table[class_name]
        class_args = [substitutions[name] for name in owner.generic_params if name in substitutions]
        prefix = self._type_identity.specialization_symbol(class_name, class_args) if class_args else class_name
        return DefaultTarget(
            declaration=owner.constructor,
            c_name=f"{prefix}_new",
            owner_name=class_name,
            class_prefix=prefix,
            substitutions=substitutions,
        )

    def _receiver_class(self, callee):
        receiver = callee.obj
        if isinstance(receiver, Identifier) and (not self._session.local_is_declared(receiver.name)):
            direct = self._analyzed.class_table.get(receiver.name)
            if direct is not None:
                return direct
        receiver_type = self._types.canonical_type(self._analyzed.node_types.get(id(receiver)))
        return self._analyzed.class_table.get(receiver_type.base) if receiver_type else None

    def _helper_params(self, target, params, param_index, provenance: CallableProvenance):
        result = []
        if target.self_type is not None:
            result.append(IRParam(c_type=CType(text=self._types.render(target.self_type)), name="self"))
        result.extend(provenance.lower_source_param(param) for param in params[:param_index])
        return result

    def hosted_string_conversion_mode(self, expression, target_type, source_type) -> str | None:
        """Classify raw-char-pointer to managed-string conversion."""
        return self._conversion_mode(expression, target_type, source_type)

    def _conversion_mode(self, expression, target_type, source_type) -> str | None:
        target = self._types.canonical_type(target_type)
        source = self._types.canonical_type(source_type)
        if not CallLowerer._managed_string(target) or not CallLowerer._raw_c_string(source):
            return None
        if not isinstance(expression, CallExpr) or not isinstance(expression.callee, Identifier):
            return REJECT
        if id(expression) not in self._analyzed.hosted_call_ids:
            return REJECT
        name = expression.callee.name
        spec = HOSTED_ABI.function(name)
        if spec is None:
            return REJECT
        alias_is_null = HOSTED_ABI.alias_argument_is_provably_null(name, expression.args)
        effect = HOSTED_ABI.return_effect(name, alias_argument_is_null=alias_is_null)
        if (
            effect == RETURN_FRESH
            and HOSTED_ABI.return_deallocator(name, alias_argument_is_null=alias_is_null) == DEALLOC_FREE
        ):
            return ADOPT
        if effect in {RETURN_ALIAS, RETURN_INDEPENDENT}:
            return COPY
        return REJECT

    @staticmethod
    def _managed_string(type_expr) -> bool:
        return bool(
            type_expr and type_expr.base == "string" and (type_expr.pointer_depth == 0) and (not type_expr.is_array)
        )

    @staticmethod
    def _raw_c_string(type_expr) -> bool:
        return bool(
            type_expr and type_expr.base == "char" and (type_expr.pointer_depth == 1) and (not type_expr.is_array)
        )

    def plan_value(self, node, target_type, provenance: CallableProvenance) -> ValuePreparationPlan:
        """Resolve target-directed conversion facts without lowering source IR."""
        source_type = self._types.canonical_type(self._session.type_of(node))
        resolved_target = self._types.canonical_type(target_type)
        hosted_mode = self.hosted_string_conversion_mode(node, resolved_target, source_type)
        source_owned = bool(
            id(node) not in self._session.owning_overrides and self._ownership.owns_result(node, provenance=provenance)
        )
        if hosted_mode == REJECT:
            raise CodegenError(
                "raw char* to managed string conversion reached IR without a proven hosted ownership effect"
            )
        return ValuePreparationPlan(
            source=node,
            source_type=source_type,
            target_type=resolved_target,
            hosted_mode=hosted_mode,
            source_owned=source_owned,
            string_conversion=self.requires_string_conversion(resolved_target, source_type),
        )

    @staticmethod
    def materialize_value(
        plan: ValuePreparationPlan,
        lowered: IRExpr,
        *,
        converted: IRExpr | None = None,
    ) -> PreparedValue:
        """Materialize resolved value facts from explicitly lowered IR."""
        if plan.hosted_mode in {ADOPT, COPY}:
            return PreparedValue(
                value=lowered,
                effective_type=plan.target_type,
                owned=True,
                converted=True,
            )
        if plan.string_conversion:
            if converted is None:
                raise ValueError("string conversion requires materialized call IR")
            return PreparedValue(
                value=converted,
                effective_type=TypeExpr(base="string"),
                owned=True,
                converted=True,
            )
        return PreparedValue(
            value=lowered,
            effective_type=plan.source_type or plan.target_type,
            owned=plan.source_owned,
        )

    def materialize_string_conversion(self, plan: ValuePreparationPlan, receiver: IRExpr) -> IRExpr:
        """Build one null-safe class-to-string conversion from stable input."""
        return IRTernary(
            condition=IRBinOp(left=receiver, op="!=", right=IRLiteral(text="NULL")),
            true_expr=self._types.to_string_call(plan.source_type, receiver),
            false_expr=IRLiteral(text='""'),
        )

    def requires_string_conversion(self, target_type, source_type) -> bool:
        target = self._types.canonical_type(target_type)
        source = self._types.canonical_type(source_type)
        return bool(self._type_identity.is_scalar_string(target) and self._types.has_to_string(source))

    def prepared_value_pin_flags(self, prepared_values) -> list[bool]:
        """Mark borrowed managed values invalidatable by later evaluation."""
        return self._operand_order.source_order_pin_flags(
            [node for node, _prepared in prepared_values],
            [prepared.effective_type for _node, prepared in prepared_values],
            [prepared.owned for _node, prepared in prepared_values],
        )

    def adapt_printf_arg(self, value: IRExpr, value_type: TypeExpr | None, format_spec: str) -> PrintfArg:
        """Make one printf argument match its format without duplicating effects.

        Function pointers cannot be converted to ``void*`` portably.  They render as
        an opaque token.  A direct print expression remains in a comma expression
        so it is evaluated exactly once.  F-string values have already been
        assigned to a temporary by their caller; reading that temporary in each
        formatting pass both preserves the evaluation contract and avoids an
        unused-but-set strict-C diagnostic.
        """
        resolved_type = self._types.canonical_type(value_type) if value_type is not None else None
        format_spec = self._types.format_spec(resolved_type) if resolved_type is not None else format_spec
        if (
            resolved_type is not None
            and resolved_type.base == "__fn_ptr"
            and (resolved_type.pointer_depth == 0)
            and (not resolved_type.is_array)
        ):
            token = IRLiteral(text='"<function>"')
            discarded = IRCast(target_type=CType(text="void"), expr=value)
            return PrintfArg(format_spec="%s", value=IRCommaExpr(expressions=[discarded, token]))
        if (
            resolved_type is not None
            and resolved_type.base == "bool"
            and (resolved_type.pointer_depth == 0)
            and (not resolved_type.is_array)
        ):
            return PrintfArg(
                format_spec="%s",
                value=IRTernary(
                    condition=value, true_expr=IRLiteral(text='"true"'), false_expr=IRLiteral(text='"false"')
                ),
            )
        if resolved_type is not None and resolved_type.base == "__fn_ptr":
            return PrintfArg(format_spec="%p", value=IRCast(target_type=CType(text="void*"), expr=value))
        if (
            resolved_type is not None
            and resolved_type.pointer_depth == 0
            and (not resolved_type.is_array)
            and (resolved_type.base in self._analyzed.enum_table)
        ):
            return PrintfArg(format_spec="%d", value=IRCast(target_type=CType(text="int"), expr=value))
        if (
            resolved_type is not None
            and resolved_type.pointer_depth == 0
            and (not resolved_type.is_array)
            and (resolved_type.base in self._analyzed.rich_enum_table)
        ):
            return PrintfArg(format_spec="%s", value=IRCall(callee=f"{resolved_type.base}_toString", args=[value]))
        if self._is_by_value_aggregate(resolved_type):
            is_tuple = resolved_type.base == "Tuple" or resolved_type.base.startswith("(")
            token = '"<tuple>"' if is_tuple else '"<struct>"'
            return PrintfArg(
                format_spec="%s",
                value=IRCommaExpr(
                    expressions=[IRCast(target_type=CType(text="void"), expr=value), IRLiteral(text=token)]
                ),
            )
        if format_spec == "%s":
            self._session.require_helper("__btrc_string_or_empty")
            return PrintfArg(
                format_spec=format_spec,
                value=IRCall(callee="__btrc_string_or_empty", args=[value], helper_ref="__btrc_string_or_empty"),
            )
        if format_spec == "%p":
            return PrintfArg(format_spec=format_spec, value=IRCast(target_type=CType(text="void*"), expr=value))
        if format_spec == "%u":
            return PrintfArg(format_spec=format_spec, value=IRCast(target_type=CType(text="unsigned int"), expr=value))
        return PrintfArg(format_spec=format_spec, value=value)

    def _is_by_value_aggregate(self, value_type: TypeExpr | None) -> bool:
        if value_type is None or value_type.pointer_depth > 0 or value_type.is_array:
            return False
        if value_type.base == "Tuple" or value_type.base.startswith("("):
            return True
        struct_name = value_type.base.removeprefix("struct ")
        return struct_name in self._analyzed.struct_table

    def rich_enum_variant_target(self, node, *, identifier_is_local=None):
        """Return ``(enum_name, variant)`` for a lexical type-qualified call."""
        callee = getattr(node, "callee", None)
        if not isinstance(callee, FieldAccessExpr) or not isinstance(callee.obj, Identifier):
            return None
        owner = callee.obj.name
        is_local = identifier_is_local or self._session.local_is_declared
        if is_local(owner):
            return None
        declaration = self._analyzed.rich_enum_table.get(owner)
        if declaration is None:
            return None
        variant = next((candidate for candidate in declaration.variants if candidate.name == callee.field), None)
        return (owner, variant) if variant is not None else None
