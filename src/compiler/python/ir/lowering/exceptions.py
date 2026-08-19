"""Cohesive exceptions IR lowering owner."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.compiler.python.abi.declarations import CONSUME, MUTATE, RETURN_ALIAS, RETURN_OPAQUE, UNKNOWN
from src.compiler.python.abi.hosted import HOSTED_ABI
from src.compiler.python.analyzer.flow import ControlFlowAnalyzer
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRCompoundLiteral,
    IRDeref,
    IRDoWhile,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRFunctionDecl,
    IRFunctionDef,
    IRGlobalDecl,
    IRIf,
    IRIndex,
    IRInitializerList,
    IRLiteral,
    IRModule,
    IRParam,
    IRReturn,
    IRSizeof,
    IRStatementSequence,
    IRStmt,
    IRStmtExpr,
    IRSwitch,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
)
from src.compiler.python.syntax.ast.generated import ThrowStmt, TryCatchStmt, TypeExpr

from .types import CodegenError, CTypeLowerer

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalyzedProgram

    from .calls import (
        CallableFlowSnapshot,
        CallableMutationCapture,
        CallableProvenance,
        ExceptionalCallableCapture,
    )
    from .expressions import ExpressionLowerer
    from .ownership import OwnershipLowerer
    from .session import LoweringSession
AliasState = dict["Storage", set["PointerOrigin"]]
_ASSIGNMENT_OPS = frozenset({"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="})
_TYPE_QUALIFIERS = frozenset({"const", "volatile"})
OPAQUE_POINTER_DEPTH = -1


@dataclass(frozen=True)
class ExceptionBinding:
    """One catch-local value materialized by the statement owner."""

    name: str
    c_type: str
    type_expr: TypeExpr
    value: IRCall
    owned: bool


@dataclass(slots=True)
class TryCatchPlan:
    """Bounded transaction state for one structured try/catch lowering."""

    source: TryCatchStmt
    incoming: CallableFlowSnapshot
    finally_only: bool
    try_terminates: bool
    pending_name: str | None
    error_name: str
    statements: list[IRStmt] = field(default_factory=list)
    try_body: IRBlock | None = None
    try_flow: CallableFlowSnapshot | None = None
    exceptional_capture: ExceptionalCallableCapture | None = None
    exceptional_entry: CallableFlowSnapshot | None = None
    catch_body: IRBlock | None = None
    catch_flow: CallableFlowSnapshot | None = None
    catch_bindings: tuple[ExceptionBinding, ...] = ()
    continuation_flows: tuple[CallableFlowSnapshot, ...] = ()
    finally_body: IRBlock | None = None
    finally_capture: CallableMutationCapture | None = None
    finally_mutations: frozenset[str] = frozenset()
    finally_result: CallableFlowSnapshot | None = None


@dataclass(frozen=True)
class SetjmpCallEffects:
    catalog: FunctionEffectCatalog
    flow: PointerFlowResult


@dataclass(frozen=True)
class Storage:
    """One lexically resolved C object with exact or opaque pointer depth."""

    name: str
    identity: int
    kind: str
    pointer_depth: int = 0
    is_array: bool = False
    compiler_owned: bool = False

    @property
    def is_pointer(self) -> bool:
        return self.pointer_depth != 0

    @property
    def automatic(self) -> bool:
        return self.kind in {"automatic", "parameter"}


@dataclass(frozen=True)
class PointerOrigin:
    """A concrete object or relative pointee; negative depth is saturated."""

    storage: Storage
    depth: int = 0
    source_exposed: bool = False

    def deeper(self) -> PointerOrigin:
        if self.depth < 0 or self.storage.pointer_depth < 0:
            return self.saturated()
        return PointerOrigin(self.storage, self.depth + 1, self.source_exposed)

    def saturated(self) -> PointerOrigin:
        return PointerOrigin(self.storage, OPAQUE_POINTER_DEPTH, self.source_exposed)


@dataclass(frozen=True, order=True)
class ParameterEffect:
    index: int
    depth: int = 1


@dataclass(frozen=True)
class FunctionEffect:
    writes: frozenset[ParameterEffect] = frozenset()
    captures: frozenset[ParameterEffect] = frozenset()
    returns: frozenset[ParameterEffect] = frozenset()
    unknown_return: bool = False


class FunctionEffectCatalog:
    """Own fixed-point call effects for one structured IR module."""

    def __init__(
        self,
        function_names: set[str],
        external_effects: dict[str, FunctionEffect],
    ) -> None:
        self._functions = {name: FunctionEffect() for name in function_names}
        self._external = dict(external_effects)

    def resolve(self, callee: object, argument_count: int) -> FunctionEffect:
        """Resolve one call without exposing the catalog's mutable maps."""
        if isinstance(callee, str) and callee in self._functions:
            return self._functions[callee]
        if isinstance(callee, str) and callee in self._external:
            return self._external[callee]
        if isinstance(callee, str):
            return self.hosted_effect(callee, argument_count) or self.unknown_effect(argument_count)
        return self.unknown_effect(argument_count)

    def merge(self, name: str, effect: FunctionEffect) -> bool:
        """Join one inferred summary and report whether the fixed point moved."""
        current = self._functions[name]
        merged = FunctionEffect(
            writes=current.writes | effect.writes,
            captures=current.captures | effect.captures,
            returns=current.returns | effect.returns,
            unknown_return=current.unknown_return or effect.unknown_return,
        )
        if merged == current:
            return False
        self._functions[name] = merged
        return True

    @staticmethod
    def unknown_effect(argument_count: int) -> FunctionEffect:
        parameters = frozenset(ParameterEffect(index) for index in range(argument_count))
        return FunctionEffect(
            writes=parameters,
            captures=parameters,
            unknown_return=True,
        )

    @staticmethod
    def hosted_effect(name: str, argument_count: int) -> FunctionEffect | None:
        spec = HOSTED_ABI.function(name)
        if spec is None:
            return None
        if spec.parameters is None:
            return FunctionEffectCatalog.unknown_effect(argument_count)
        writes = set()
        captures = set()
        for index in range(argument_count):
            if index >= len(spec.parameters):
                writes.add(ParameterEffect(index))
                captures.add(ParameterEffect(index))
                continue
            parameter = spec.parameters[index]
            if parameter.pointer_depth == 0:
                continue
            effect = spec.effects[index]
            if effect in {MUTATE, CONSUME, UNKNOWN}:
                writes.add(ParameterEffect(index))
            if effect in {CONSUME, UNKNOWN}:
                captures.add(ParameterEffect(index))
        returns = set()
        if spec.return_effect == RETURN_ALIAS and spec.return_alias_parameter is not None:
            returns.add(ParameterEffect(spec.return_alias_parameter))
        return FunctionEffect(
            writes=frozenset(writes),
            captures=frozenset(captures),
            returns=frozenset(returns),
            unknown_return=spec.return_effect == RETURN_OPAQUE,
        )

    @staticmethod
    def external_effect(
        declaration: IRFunctionDecl,
        type_facts: PointerTypeFacts,
    ) -> FunctionEffect:
        hosted = FunctionEffectCatalog.hosted_effect(declaration.name, len(declaration.params))
        if hosted is not None:
            return hosted
        pointers = frozenset(
            ParameterEffect(index)
            for index, parameter in enumerate(declaration.params)
            if type_facts.is_pointer(parameter.c_type)
        )
        return FunctionEffect(
            writes=pointers,
            captures=pointers,
            returns=pointers if type_facts.is_pointer(declaration.return_type) else frozenset(),
            unknown_return=type_facts.is_pointer(declaration.return_type),
        )


@dataclass
class PointerFlowResult:
    writes: dict[int, set[PointerOrigin]] = field(default_factory=dict)
    origins: dict[int, set[PointerOrigin]] = field(default_factory=dict)
    storages: dict[int, Storage] = field(default_factory=dict)
    captures: set[PointerOrigin] = field(default_factory=set)
    returns: set[PointerOrigin] = field(default_factory=set)
    unknown_pointer_values: set[Storage] = field(default_factory=set)

    def record_origins(self, value: object, origins) -> set[PointerOrigin]:
        result = set(origins)
        self.origins.setdefault(id(value), set()).update(result)
        return result

    def record_write(self, value: object, origins) -> None:
        self.writes.setdefault(id(value), set()).update(origins)


class _MutationCollector:
    def __init__(self, effects: SetjmpCallEffects) -> None:
        self.flow = effects.flow
        self.storages: set[Storage] = set()

    def block(self, block: IRBlock | None, bound=None) -> None:
        if block is None:
            return
        local = set(bound or ())
        for statement in block.stmts:
            self._statement(statement, local)

    def _record(self, value, bound) -> None:
        for origin in self.flow.writes.get(id(value), ()):
            if origin.depth == 0 and origin.storage.identity not in bound:
                self.storages.add(origin.storage)

    def _expression(self, value, bound) -> None:
        if value is None:
            return
        self._record(value, bound)
        if isinstance(value, IRSizeof):
            return
        if isinstance(value, IRStmtExpr):
            local = set(bound)
            for statement in value.stmts:
                self._statement(statement, local)
            self._expression(value.result, local)
            return
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                child = getattr(value, field.name)
                items = child if isinstance(child, (list, tuple)) else (child,)
                for item in items:
                    self._expression(item, bound)

    def _declaration(self, declaration, bound) -> None:
        self._expression(declaration.array_size, bound)
        storage = self.flow.storages.get(id(declaration))
        if storage is not None:
            bound.add(storage.identity)
        self._expression(declaration.init, bound)

    def _statement(self, statement, bound) -> None:
        self._record(statement, bound)
        if isinstance(statement, IRVarDecl):
            self._declaration(statement, bound)
        elif isinstance(statement, IRIf):
            self._expression(statement.condition, bound)
            self.block(statement.then_block, bound)
            self.block(statement.else_block, bound)
        elif isinstance(statement, (IRWhile, IRDoWhile)):
            self._expression(statement.condition, bound)
            self.block(statement.body, bound)
        elif isinstance(statement, IRFor):
            local = set(bound)
            if isinstance(statement.init, IRVarDecl):
                self._declaration(statement.init, local)
            else:
                self._expression(statement.init, local)
            self._expression(statement.condition, local)
            self._expression(statement.update, local)
            self.block(statement.body, local)
        elif isinstance(statement, IRSwitch):
            self._expression(statement.value, bound)
            for case in statement.cases:
                local = set(bound)
                self._expression(case.value, local)
                for child in case.body:
                    self._statement(child, local)
        elif isinstance(statement, IRBlock):
            self.block(statement, bound)
        else:
            self._expression(statement, bound)


class PointerFlow:
    """Interpret pointer values while retaining structured storage identity."""

    def __init__(
        self,
        function: IRFunctionDef,
        globals_by_name: Mapping[str, Storage],
        type_facts: PointerTypeFacts,
        effect_catalog: FunctionEffectCatalog,
    ) -> None:
        self.function = function
        self.type_facts = type_facts
        self._effect_catalog = effect_catalog
        self.result = PointerFlowResult()
        self.bindings = dict(globals_by_name)
        self.parameters: list[Storage] = []
        self.state: AliasState = {}
        for parameter in function.params:
            storage = Storage(
                name=parameter.name,
                identity=id(parameter),
                kind="parameter",
                pointer_depth=self.type_facts.pointer_depth(parameter.c_type),
                compiler_owned=ExceptionLowerer.compiler_storage_name(parameter.name),
            )
            self.bindings[parameter.name] = storage
            self.parameters.append(storage)
            self.result.storages[id(parameter)] = storage
            if storage.is_pointer:
                self.state[storage] = {PointerOrigin(storage, depth=1)}

    def run(self) -> PointerFlowResult:
        self.state = self._block(self.function.body, self.state, scoped=False)
        return self.result

    def _resolve(self, name: str) -> Storage | None:
        return self.bindings.get(name)

    def _declare(self, declaration: IRVarDecl) -> Storage:
        kind = "static" if declaration.is_static else "extern" if declaration.is_extern else "automatic"
        storage = Storage(
            name=declaration.name,
            identity=id(declaration),
            kind=kind,
            pointer_depth=self.type_facts.pointer_depth(declaration.c_type),
            is_array=declaration.array_size is not None or declaration.is_unsized_array,
            compiler_owned=ExceptionLowerer.compiler_storage_name(declaration.name),
        )
        self.bindings[declaration.name] = storage
        self.result.storages[id(declaration)] = storage
        return storage

    def _block(self, block: IRBlock | None, state: AliasState, *, scoped: bool = True) -> AliasState:
        if block is None:
            return state
        saved_bindings = dict(self.bindings)
        current = ExceptionLowerer._copy_state(state)
        for statement in block.stmts:
            current = self._statement(statement, current)
        if not scoped:
            return current
        self.bindings = saved_bindings
        visible = set(saved_bindings.values())
        return {storage: origins for storage, origins in current.items() if storage in visible}

    def _statement(self, statement, state: AliasState) -> AliasState:
        self.state = state
        if isinstance(statement, IRVarDecl):
            current = self._expression(statement.array_size, state)[1]
            storage = self._declare(statement)
            origins, current = self._expression(statement.init, current)
            if storage.is_pointer and (not storage.is_array):
                current[storage] = set(origins)
                if origins and (not storage.automatic):
                    self.result.captures.update(origins)
            elif origins:
                self.result.captures.update(origins)
            return current
        if isinstance(statement, IRAssign):
            return self._assignment(statement, statement.target, statement.value, state)
        if isinstance(statement, IRReturn):
            origins, current = self._expression(statement.value, state)
            self.result.returns.update(origins)
            return current
        if isinstance(statement, IRExprStmt):
            return self._expression(statement.expr, state)[1]
        if isinstance(statement, IRIf):
            _, current = self._expression(statement.condition, state)
            left = self._block(statement.then_block, ExceptionLowerer._copy_state(current))
            right = self._block(statement.else_block, ExceptionLowerer._copy_state(current))
            return ExceptionLowerer._join_states(left, right)
        if isinstance(statement, (IRWhile, IRDoWhile)):
            return self._loop(statement, state)
        if isinstance(statement, IRFor):
            return self._for(statement, state)
        if isinstance(statement, IRSwitch):
            return self._switch(statement, state)
        if isinstance(statement, IRBlock):
            return self._block(statement, state)
        return state

    def _loop(self, statement, state: AliasState) -> AliasState:
        entry = ExceptionLowerer._copy_state(state)
        header = ExceptionLowerer._copy_state(state)
        for _ in range(16):
            _, conditioned = self._expression(statement.condition, ExceptionLowerer._copy_state(header))
            body = self._block(statement.body, conditioned)
            updated = ExceptionLowerer._join_states(entry, body)
            if updated == header:
                return updated
            header = updated
        return self._widen(header)

    def _for(self, statement: IRFor, state: AliasState) -> AliasState:
        saved_bindings = dict(self.bindings)
        current = (
            self._statement(statement.init, state)
            if statement.init is not None
            else ExceptionLowerer._copy_state(state)
        )
        entry = ExceptionLowerer._copy_state(current)
        header = ExceptionLowerer._copy_state(current)
        for _ in range(16):
            _, conditioned = self._expression(statement.condition, ExceptionLowerer._copy_state(header))
            body = self._block(statement.body, conditioned)
            _, back = self._expression(statement.update, body)
            updated = ExceptionLowerer._join_states(entry, back)
            if updated == header:
                break
            header = updated
        else:
            header = self._widen(header)
        self.bindings = saved_bindings
        visible = set(saved_bindings.values())
        return {storage: origins for storage, origins in header.items() if storage in visible}

    def _switch(self, statement: IRSwitch, state: AliasState) -> AliasState:
        _, entry = self._expression(statement.value, state)
        exits = [ExceptionLowerer._copy_state(entry)]
        fallthrough = None
        for case in statement.cases:
            start = ExceptionLowerer._join_states(entry, fallthrough or {})
            _, start = self._expression(case.value, start)
            output = self._block(IRBlock(case.body), start)
            if case.falls_through:
                fallthrough = output
            else:
                exits.append(output)
                fallthrough = None
        if fallthrough is not None:
            exits.append(fallthrough)
        return ExceptionLowerer._join_states(*exits)

    @staticmethod
    def _widen(state: AliasState) -> AliasState:
        all_origins = set().union(*state.values()) if state else set()
        return {storage: set(all_origins if storage.is_pointer else origins) for storage, origins in state.items()}

    def _expression(self, value, state):
        if value is None:
            return (set(), state)
        if isinstance(value, IRVar):
            storage = self._resolve(value.name)
            if value.array_storage_known and value.array_storage_root:
                storage = self._resolve(value.array_storage_root)
                origins = {PointerOrigin(storage, source_exposed=True)} if storage else set()
            elif storage is not None and storage.is_array:
                origins = {PointerOrigin(storage, source_exposed=True)}
            else:
                origins = set(state.get(storage, ())) if storage is not None and storage.is_pointer else set()
            return (self.result.record_origins(value, origins), state)
        if isinstance(value, IRAddressOf):
            _, current = self._expression(value.expr, state)
            origins = {
                PointerOrigin(origin.storage, origin.depth, origin.source_exposed or value.source_expression)
                for origin in self._locations(value.expr, current)
            }
            return (self.result.record_origins(value, origins), current)
        if isinstance(value, IRDeref):
            child, current = self._expression(value.expr, state)
            return (self.result.record_origins(value, self._load(child, current)), current)
        if isinstance(value, IRCast):
            origins, current = self._expression(value.expr, state)
            target_depth = self.type_facts.pointer_depth(value.target_type)
            if target_depth == 0:
                if origins and (not self._is_void_cast(value.target_type)):
                    self.result.captures.update(origins)
                origins = set()
            else:
                origins = {
                    origin.saturated() if self._cast_widens(origin, target_depth) else origin for origin in origins
                }
            return (self.result.record_origins(value, origins), current)
        if isinstance(value, IRCommaExpr):
            origins: set[PointerOrigin] = set()
            current = state
            for expression in value.expressions:
                origins, current = self._expression(expression, current)
            return (self.result.record_origins(value, origins), current)
        if isinstance(value, IRStmtExpr):
            current = state
            for statement in value.stmts:
                current = self._statement(statement, current)
            origins, current = self._expression(value.result, current)
            return (self.result.record_origins(value, origins), current)
        if isinstance(value, IRTernary):
            _, current = self._expression(value.condition, state)
            left, left_state = self._expression(value.true_expr, self._copy(current))
            right, right_state = self._expression(value.false_expr, self._copy(current))
            return (self.result.record_origins(value, left | right), self._join(left_state, right_state))
        if isinstance(value, IRCall):
            return self._call(value, state)
        if isinstance(value, IRBinOp):
            if value.op in _ASSIGNMENT_OPS:
                current = self._assignment(value, value.left, value.right, state, op=value.op)
                origins = self.result.origins.get(id(value.right), set()) if value.op == "=" else set()
                return (self.result.record_origins(value, origins), current)
            if value.op in {"&&", "||", "??"}:
                left, current = self._expression(value.left, state)
                right, right_state = self._expression(value.right, self._copy(current))
                origins = left | right if value.op == "??" else set()
                return (self.result.record_origins(value, origins), self._join(current, right_state))
            left, current = self._expression(value.left, state)
            right, current = self._expression(value.right, current)
            origins = left | right if value.op in {"+", "-"} else set()
            return (self.result.record_origins(value, origins), current)
        if isinstance(value, IRUnaryOp):
            origins, current = self._expression(value.operand, state)
            if value.op in {"++", "--"}:
                self.result.record_write(value, self._locations(value.operand, current))
            if value.op == "!":
                origins = set()
            return (self.result.record_origins(value, origins), current)
        if isinstance(value, IRSizeof):
            return (self.result.record_origins(value, ()), state)
        if isinstance(value, IRFieldAccess):
            _, current = self._expression(value.obj, state)
            if value.array_storage_known and value.array_storage_root:
                storage = self._resolve(value.array_storage_root)
                origins = {PointerOrigin(storage, source_exposed=True)} if storage else set()
            else:
                origins = set()
            return (self.result.record_origins(value, origins), current)
        if isinstance(value, IRIndex):
            _, current = self._expression(value.obj, state)
            _, current = self._expression(value.index, current)
            return (self.result.record_origins(value, ()), current)
        if isinstance(value, (IRInitializerList, IRCompoundLiteral)):
            origins: set[PointerOrigin] = set()
            current = state
            children = value.elements if isinstance(value, IRInitializerList) else [item for _, item in value.fields]
            for child in children:
                child_origins, current = self._expression(child, current)
                origins.update(child_origins)
            return (self.result.record_origins(value, origins), current)
        current = state
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                child = getattr(value, field.name)
                items = child if isinstance(child, (list, tuple)) else (child,)
                for item in items:
                    _, current = self._expression(item, current)
        return (self.result.record_origins(value, ()), current)

    def _assignment(self, node, target, value, state, *, op="="):
        _, current = self._expression(target, state)
        origins, current = self._expression(value, current)
        locations = self._locations(target, current)
        self.result.record_write(node, locations)
        if op != "=":
            return current
        local_pointers = {
            origin.storage
            for origin in locations
            if origin.depth == 0 and origin.storage.is_pointer and (not origin.storage.is_array)
        }
        exact_local = len(locations) == 1 and len(local_pointers) == 1
        if exact_local:
            destination = next(iter(local_pointers))
            current[destination] = set(origins)
            if not destination.automatic:
                self.result.captures.update(origins)
        elif local_pointers and len(local_pointers) == len(locations):
            for storage in local_pointers:
                current.setdefault(storage, set()).update(origins)
        elif origins:
            self.result.captures.update(origins)
        return current

    def _call(self, call: IRCall, state):
        current = state
        if not isinstance(call.callee, str):
            _, current = self._expression(call.callee, current)
        for argument in call.args:
            _, current = self._expression(argument, current)
        effect = self._effect_catalog.resolve(call.callee, len(call.args))
        writes = set()
        for item in effect.writes:
            if item.index < len(call.args):
                writes.update(self._argument_targets(call.args[item.index], item.depth, current))
        self.result.record_write(call, writes)
        for origin in writes:
            storage = origin.storage
            if origin.depth == 0 and storage.is_pointer and (not storage.is_array):
                current[storage] = set()
                if origin.source_exposed and (not storage.compiler_owned):
                    self.result.unknown_pointer_values.add(storage)
        for item in effect.captures:
            if item.index < len(call.args):
                self.result.captures.update(self._argument_targets(call.args[item.index], item.depth, current))
        origins = set()
        for item in effect.returns:
            if item.index < len(call.args):
                origins.update(self._argument_targets(call.args[item.index], item.depth, current))
        if effect.unknown_return:
            for argument in call.args:
                origins.update(self.result.origins.get(id(argument), ()))
        return (self.result.record_origins(call, origins), current)

    def _argument_targets(self, argument, depth, state):
        origins = set(self.result.origins.get(id(argument), ()))
        if depth < 0:
            saturated = set()
            frontier = origins
            while frontier:
                expandable = set()
                for origin in frontier:
                    concrete = origin.saturated() if origin.depth > 0 else origin
                    if concrete not in saturated:
                        saturated.add(concrete)
                        expandable.add(origin)
                frontier = self._load(expandable, state)
            return saturated
        for _ in range(max(0, depth - 1)):
            origins = self._load(origins, state)
        return origins

    def _locations(self, value, state):
        if isinstance(value, IRVar):
            storage = self._resolve(value.name)
            return {PointerOrigin(storage)} if storage else set()
        if isinstance(value, IRFieldAccess) and value.arrow:
            return set(self.result.origins.get(id(value.obj), ()))
        if isinstance(value, (IRIndex, IRDeref)):
            if value.storage_root_known and value.storage_root:
                storage = self._resolve(value.storage_root)
                return {PointerOrigin(storage)} if storage else set()
            if value.storage_root_known or isinstance(value, IRDeref):
                child = value.obj if isinstance(value, IRIndex) else value.expr
                return set(self.result.origins.get(id(child), ()))
        root = value.direct_storage_root()
        storage = self._resolve(root) if root else None
        return {PointerOrigin(storage)} if storage else set()

    @staticmethod
    def _copy(state):
        return {storage: set(origins) for storage, origins in state.items()}

    @staticmethod
    def _join(*states):
        result = {}
        for state in states:
            for storage, origins in state.items():
                result.setdefault(storage, set()).update(origins)
        return result

    @staticmethod
    def _load(origins, state):
        loaded = set()
        for origin in origins:
            if origin.depth < 0:
                loaded.add(origin)
            elif origin.depth > 0 and origin.storage.pointer_depth < 0:
                loaded.add(origin.saturated())
            elif 0 < origin.depth < origin.storage.pointer_depth:
                loaded.add(origin.deeper())
            elif origin.depth == 0 and origin.storage.is_pointer:
                loaded.update(state.get(origin.storage, ()))
        return loaded

    @staticmethod
    def _cast_widens(origin, target_depth):
        """Whether a cast invents pointee levels beyond an abstract origin."""
        if origin.depth <= 0:
            return False
        declared_depth = origin.storage.pointer_depth
        if target_depth < 0 or declared_depth < 0:
            return True
        remaining_depth = max(0, declared_depth - origin.depth + 1)
        return target_depth > remaining_depth

    def _is_void_cast(self, target_type):
        return self.type_facts.is_void(target_type)


@dataclass(frozen=True)
class PointerTypeFacts:
    aliases: frozenset[str]
    read_only_pointee_aliases: frozenset[str]
    alias_depths: dict[str, int]
    void_aliases: frozenset[str]

    def is_pointer(self, c_type: object) -> bool:
        return self.pointer_depth(c_type) != 0

    def pointer_depth(self, c_type: object) -> int:
        stars = ExceptionLowerer._pointer_stars(c_type)
        alias = ExceptionLowerer._alias_name(c_type, self.aliases)
        if stars == 0 and alias is not None and (alias in self.alias_depths):
            return self.alias_depths[alias]
        pointer_base = ExceptionLowerer._pointer_base_alias(c_type, self.aliases)
        if pointer_base is not None and pointer_base in self.alias_depths:
            stars += self.alias_depths[pointer_base]
        if stars == 0 and alias is not None:
            return OPAQUE_POINTER_DEPTH
        return stars

    def is_void(self, c_type: object) -> bool:
        text = str(c_type).strip()
        if "*" in text or any(character in text for character in "[]()"):
            return False
        words = [word for word in text.split() if word not in _TYPE_QUALIFIERS]
        return words == ["void"] or (len(words) == 1 and words[0] in self.void_aliases)


class _QualifierSafety:
    def __init__(
        self,
        parameters: Sequence[IRParam],
        inferred: set[int],
        globals_by_name: Mapping[str, IRGlobalDecl],
    ) -> None:
        self._parameters = parameters
        self._inferred = inferred
        self._globals = globals_by_name

    def block(self, block: IRBlock | None, inherited=()) -> None:
        if block is None:
            return
        visible = list(inherited)
        for statement in block.stmts:
            self._statement(statement, visible)

    def _resolve(self, name: str, visible):
        for declaration in reversed(visible):
            if declaration.name == name:
                return declaration
        for parameter in self._parameters:
            if parameter.name == name:
                return parameter
        return self._globals.get(name)

    def _reject(self, name: str, declaration) -> None:
        if id(declaration) not in self._inferred:
            return
        raise CodegenError(
            f"storage object '{name}' is modified across try/throw and requires volatile storage; its address or array decay requires unsupported layered pointer qualifiers"
        )

    def _expression(self, value: object, visible, *, parent=None, field_name="") -> None:
        if value is None:
            return
        if isinstance(value, IRStmtExpr):
            local = list(visible)
            for statement in value.stmts:
                self._statement(statement, local)
            self._expression(value.result, local)
            return
        if isinstance(value, IRAddressOf) and value.source_expression and (not isinstance(parent, IRSizeof)):
            root = value.expr.direct_storage_root()
            declaration = self._resolve(root, visible) if root else None
            if (
                declaration is not None
                and declaration.is_volatile
                and (not ExceptionLowerer.compiler_storage_name(root))
            ):
                self._reject(root, declaration)
        if isinstance(value, IRVar):
            declaration = self._resolve(value.name, visible)
            array_root = value.array_storage_root if value.array_storage_known else value.name
            array_declaration = self._resolve(array_root, visible)
            if (
                isinstance(array_declaration, (IRVarDecl, IRGlobalDecl))
                and array_declaration.is_volatile
                and (not ExceptionLowerer.compiler_storage_name(value.name))
                and (
                    value.array_storage_known
                    or array_declaration.array_size is not None
                    or array_declaration.is_unsized_array
                )
                and (not isinstance(parent, IRSizeof))
                and (not (isinstance(parent, IRIndex) and field_name == "obj"))
            ):
                self._reject(array_root, array_declaration)
            return
        if (
            isinstance(value, IRFieldAccess)
            and value.array_storage_known
            and value.array_storage_root
            and (not isinstance(parent, IRSizeof))
            and (not (isinstance(parent, IRIndex) and field_name == "obj"))
        ):
            declaration = self._resolve(value.array_storage_root, visible)
            if (
                declaration is not None
                and declaration.is_volatile
                and (not ExceptionLowerer.compiler_storage_name(value.array_storage_root))
            ):
                self._reject(value.array_storage_root, declaration)
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                child = getattr(value, field.name)
                if isinstance(child, (list, tuple)):
                    for item in child:
                        self._expression(item, visible, parent=value, field_name=field.name)
                else:
                    self._expression(child, visible, parent=value, field_name=field.name)

    def _declaration(self, declaration: IRVarDecl, visible) -> None:
        self._expression(declaration.array_size, visible)
        visible.append(declaration)
        self._expression(declaration.init, visible)

    def _statement(self, statement, visible) -> None:
        if isinstance(statement, IRVarDecl):
            self._declaration(statement, visible)
        elif isinstance(statement, IRIf):
            self._expression(statement.condition, visible)
            self.block(statement.then_block, visible)
            self.block(statement.else_block, visible)
        elif isinstance(statement, (IRWhile, IRDoWhile)):
            self._expression(statement.condition, visible)
            self.block(statement.body, visible)
        elif isinstance(statement, IRFor):
            local = list(visible)
            if isinstance(statement.init, IRVarDecl):
                self._declaration(statement.init, local)
            else:
                self._expression(statement.init, local)
            self._expression(statement.condition, local)
            self._expression(statement.update, local)
            self.block(statement.body, local)
        elif isinstance(statement, IRSwitch):
            self._expression(statement.value, visible)
            for case in statement.cases:
                local = list(visible)
                self._expression(case.value, local)
                for child in case.body:
                    self._statement(child, local)
        elif isinstance(statement, IRBlock):
            self.block(statement, visible)
        else:
            self._expression(statement, visible)


class _LexicalVisibilityPass:
    def __init__(
        self,
        parameters: Sequence[IRParam],
        effects: SetjmpCallEffects,
    ) -> None:
        self._parameters = parameters
        self._effects = effects
        self.inferred_volatile: set[int] = set()

    def _qualify(self, declaration) -> None:
        if not declaration.is_volatile:
            self.inferred_volatile.add(id(declaration))
        declaration.is_volatile = True
        declaration.effective_is_volatile = True

    def block(self, block: IRBlock | None, inherited=()) -> None:
        if block is None:
            return
        visible = list(inherited)
        for index, statement in enumerate(block.stmts):
            if ExceptionLowerer.contains_setjmp(statement):
                continuation = IRBlock(stmts=block.stmts[index + 1 :])
                self._mark_visible(visible, ExceptionLowerer.mutated_names(continuation, effects=self._effects))
            self._statement(statement, visible)

    @staticmethod
    def _append_visible(visible, declaration, hoist_sink=None) -> None:
        if all(existing is not declaration for existing in visible):
            visible.append(declaration)
        if hoist_sink is not None and all(existing is not declaration for existing in hoist_sink):
            hoist_sink.append(declaration)

    def _mark_visible(self, visible, modified=None) -> None:
        if modified is None:
            remaining = {
                *(id(parameter) for parameter in self._parameters),
                *(id(declaration) for declaration in visible),
            }
        else:
            remaining = {storage.identity for storage in modified}
        remaining.update(
            id(declaration) for declaration in visible if ExceptionLowerer.compiler_storage_name(declaration.name)
        )
        for declaration in reversed(visible):
            if id(declaration) in remaining:
                if ExceptionLowerer._automatic(declaration):
                    self._qualify(declaration)
                remaining.remove(id(declaration))
        for parameter in self._parameters:
            if id(parameter) in remaining:
                self._qualify(parameter)

    def _prepare_hoists(self, value: object, visible, modified=None, hoist_sink=None) -> None:
        """Model declarations emitted while the emitter pre-renders an expression."""
        if isinstance(value, IRStmtExpr):
            for statement in value.stmts:
                if isinstance(statement, IRVarDecl):
                    self._prepare_declaration(statement, visible, modified, hoist_sink)
            self._prepare_hoists(value.result, visible, modified, hoist_sink)
            return
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                self._prepare_hoists(getattr(value, field.name), visible, modified, hoist_sink)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._prepare_hoists(item, visible, modified, hoist_sink)

    def _scan_expression(self, value: object, visible, modified=None, *, parent=None, field_name="") -> None:
        if isinstance(value, IRCall) and value.callee == "setjmp":
            self._mark_visible(visible, modified)
            return
        if isinstance(value, IRStmtExpr):
            self._scan_expression(value.result, visible, modified, parent=parent, field_name=field_name)
            return
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                child = getattr(value, field.name)
                if isinstance(child, (list, tuple)):
                    for item in child:
                        self._scan_expression(item, visible, modified, parent=value, field_name=field.name)
                else:
                    self._scan_expression(child, visible, modified, parent=value, field_name=field.name)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._scan_expression(item, visible, modified, parent=parent, field_name=field_name)

    def _prepare_declaration(self, declaration, visible, modified=None, hoist_sink=None) -> None:
        self._prepare_hoists(declaration.array_size, visible, modified, hoist_sink)
        self._prepare_hoists(declaration.init, visible, modified, hoist_sink)
        self._scan_expression(declaration.array_size, visible, modified)
        self._append_visible(visible, declaration, hoist_sink)
        self._scan_expression(declaration.init, visible, modified)

    def _process_expression(self, value, visible, modified=None, hoist_sink=None) -> None:
        self._prepare_hoists(value, visible, modified, hoist_sink)
        self._scan_expression(value, visible, modified)

    def _simple(self, visible, *expressions) -> None:
        for expression in expressions:
            self._prepare_hoists(expression, visible)
        for expression in expressions:
            self._scan_expression(expression, visible)

    def _statement(self, statement, visible) -> None:
        if isinstance(statement, IRVarDecl):
            self._prepare_declaration(statement, visible)
        elif isinstance(statement, IRAssign):
            self._simple(visible, statement.target, statement.value)
        elif isinstance(statement, IRReturn):
            self._simple(visible, statement.value)
        elif isinstance(statement, IRExprStmt):
            self._simple(visible, statement.expr)
        elif isinstance(statement, IRIf):
            modified = (
                ExceptionLowerer.mutated_names(statement.then_block, effects=self._effects)
                | ExceptionLowerer.mutated_names(statement.else_block, effects=self._effects)
                if ExceptionLowerer.contains_setjmp(statement.condition)
                else None
            )
            self._process_expression(statement.condition, visible, modified)
            self.block(statement.then_block, visible)
            self.block(statement.else_block, visible)
        elif isinstance(statement, IRWhile):
            if ExceptionLowerer.contains_setjmp(statement):
                self._mark_visible(visible, ExceptionLowerer.loop_mutated_names(statement, effects=self._effects))
            self._simple(visible, statement.condition)
            self.block(statement.body, visible)
        elif isinstance(statement, IRDoWhile):
            if ExceptionLowerer.contains_setjmp(statement):
                self._mark_visible(visible, ExceptionLowerer.loop_mutated_names(statement, effects=self._effects))
            self._process_expression(statement.condition, visible)
            self.block(statement.body, visible)
        elif isinstance(statement, IRFor):
            self._for(statement, visible)
        elif isinstance(statement, IRSwitch):
            self._simple(visible, statement.value)
            for index, case in enumerate(statement.cases):
                case_visible = list(visible)
                self._simple(case_visible, case.value)
                case_block = IRBlock(stmts=case.body)
                if ExceptionLowerer.contains_setjmp(case_block) and case.falls_through:
                    self._mark_visible(
                        case_visible,
                        ExceptionLowerer.switch_fallthrough_mutated_names(statement, index, effects=self._effects),
                    )
                self.block(case_block, case_visible)
        elif isinstance(statement, IRBlock):
            self.block(statement, visible)

    def _for(self, statement, visible) -> None:
        if isinstance(statement.init, IRVarDecl):
            self._prepare_hoists(statement.init.array_size, visible, hoist_sink=visible)
            self._prepare_hoists(statement.init.init, visible, hoist_sink=visible)
        else:
            for expression in ExceptionLowerer._statement_expressions(statement.init):
                self._prepare_hoists(expression, visible, hoist_sink=visible)
        self._prepare_hoists(statement.condition, visible, hoist_sink=visible)
        self._prepare_hoists(statement.update, visible, hoist_sink=visible)
        loop_visible = list(visible)
        if isinstance(statement.init, IRVarDecl):
            self._scan_expression(statement.init.array_size, visible)
            self._append_visible(loop_visible, statement.init)
            self._scan_expression(statement.init.init, loop_visible)
        else:
            for expression in ExceptionLowerer._statement_expressions(statement.init):
                self._scan_expression(expression, loop_visible)
        if ExceptionLowerer.contains_setjmp(statement):
            self._mark_visible(loop_visible, ExceptionLowerer.loop_mutated_names(statement, effects=self._effects))
        self._scan_expression(statement.condition, loop_visible)
        self._scan_expression(statement.update, loop_visible)
        self.block(statement.body, loop_visible)


class ExceptionLowerer:
    """Own exceptions lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        expressions: ExpressionLowerer,
        ownership: OwnershipLowerer,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._expressions = expressions
        self._ownership = ownership

    @staticmethod
    def _global_storages(module, type_facts) -> dict[str, Storage]:
        return {
            declaration.name: Storage(
                name=declaration.name,
                identity=id(declaration),
                kind="global",
                pointer_depth=type_facts.pointer_depth(declaration.c_type),
                is_array=declaration.array_size is not None or declaration.is_unsized_array,
                compiler_owned=ExceptionLowerer.compiler_storage_name(declaration.name),
            )
            for declaration in module.global_decls
        }

    @staticmethod
    def _parameter_effects(origins, parameters) -> frozenset[ParameterEffect]:
        indices = {storage.identity: index for index, storage in enumerate(parameters)}
        effects = set()
        for origin in origins:
            if origin.depth == 0 or origin.storage.identity not in indices:
                continue
            depth = origin.depth
            declared_depth = origin.storage.pointer_depth
            if depth < 0 or declared_depth < 0 or depth > declared_depth:
                depth = OPAQUE_POINTER_DEPTH
            effects.add(ParameterEffect(indices[origin.storage.identity], depth))
        return frozenset(effects)

    @staticmethod
    def _flow_effect(flow: PointerFlowResult, parameters) -> FunctionEffect:
        writes = set()
        for origins in flow.writes.values():
            writes.update(origins)
        return FunctionEffect(
            writes=ExceptionLowerer._parameter_effects(writes, parameters),
            captures=ExceptionLowerer._parameter_effects(flow.captures, parameters),
            returns=ExceptionLowerer._parameter_effects(flow.returns, parameters),
        )

    @staticmethod
    def build_setjmp_call_effects(module: IRModule) -> dict[str, SetjmpCallEffects]:
        """Compute write, return-alias, and capture summaries to a fixed point."""
        type_facts = ExceptionLowerer.pointer_type_facts(module)
        definitions = {function.name: function for function in module.function_defs}
        external = {
            declaration.name: FunctionEffectCatalog.external_effect(declaration, type_facts)
            for declaration in module.function_decls
            if declaration.name not in definitions
        }
        globals_by_name = ExceptionLowerer._global_storages(module, type_facts)
        catalog = FunctionEffectCatalog(set(definitions), external)
        flows: dict[str, PointerFlowResult] = {}

        changed = True
        while changed:
            changed = False
            for name, function in definitions.items():
                flow = ExceptionLowerer.analyze_pointer_flow(function, globals_by_name, type_facts, catalog)
                parameters = [flow.storages[id(parameter)] for parameter in function.params]
                flows[name] = flow
                if catalog.merge(name, ExceptionLowerer._flow_effect(flow, parameters)):
                    changed = True
        flows = {
            name: ExceptionLowerer.analyze_pointer_flow(function, globals_by_name, type_facts, catalog)
            for name, function in definitions.items()
        }
        return {name: SetjmpCallEffects(catalog=catalog, flow=flows[name]) for name in definitions}

    @staticmethod
    def reject_unmodelled_setjmp_captures(function, effects) -> None:
        if not ExceptionLowerer.contains_setjmp(function.body):
            return
        for storage in effects.flow.unknown_pointer_values:
            raise CodegenError(
                f"pointer storage object '{storage.name}' receives an unmodelled pointer value in a function containing try/setjmp"
            )
        escaped = effects.flow.captures | {origin for origin in effects.flow.returns if origin.depth == 0}
        for origin in escaped:
            storage = origin.storage
            if origin.depth == 0 and origin.source_exposed and storage.automatic and (not storage.compiler_owned):
                raise CodegenError(
                    f"automatic storage object '{storage.name}' escapes into unmodelled storage in a function containing try/setjmp"
                )

    @staticmethod
    def contains_setjmp(value: object) -> bool:
        from ..nodes import IRCall

        if isinstance(value, IRCall):
            return value.callee == "setjmp"
        if dataclasses.is_dataclass(value):
            return any(
                ExceptionLowerer.contains_setjmp(getattr(value, field.name)) for field in dataclasses.fields(value)
            )
        if isinstance(value, (list, tuple)):
            return any(ExceptionLowerer.contains_setjmp(item) for item in value)
        return False

    @staticmethod
    def mutated_names(block: IRBlock | None, *, effects, summarize: bool = False):
        """Return exact storage identities modified outside ``block`` declarations."""
        del summarize
        collector = _MutationCollector(effects)
        collector.block(block)
        return collector.storages

    @staticmethod
    def loop_mutated_names(statement: IRFor | IRWhile | IRDoWhile, *, effects):
        statements = []
        if statement.condition is not None:
            from ..nodes import IRExprStmt

            statements.append(IRExprStmt(expr=statement.condition))
        update = getattr(statement, "update", None)
        if update is not None:
            from ..nodes import IRExprStmt

            statements.append(IRExprStmt(expr=update))
        if statement.body is not None:
            statements.append(statement.body)
        return ExceptionLowerer.mutated_names(IRBlock(stmts=statements), effects=effects)

    @staticmethod
    def switch_fallthrough_mutated_names(statement: IRSwitch, index: int, *, effects):
        modified = set()
        while index + 1 < len(statement.cases) and statement.cases[index].falls_through:
            index += 1
            modified.update(ExceptionLowerer.mutated_names(IRBlock(stmts=statement.cases[index].body), effects=effects))
        return modified

    @staticmethod
    def _copy_state(state: AliasState) -> AliasState:
        return {storage: set(origins) for storage, origins in state.items()}

    @staticmethod
    def _join_states(*states: AliasState) -> AliasState:
        joined: AliasState = {}
        for state in states:
            for storage, origins in state.items():
                joined.setdefault(storage, set()).update(origins)
        return joined

    @staticmethod
    def analyze_pointer_flow(
        function: IRFunctionDef,
        globals_by_name: Mapping[str, Storage],
        type_facts: PointerTypeFacts,
        effect_catalog: FunctionEffectCatalog,
    ) -> PointerFlowResult:
        return PointerFlow(function, globals_by_name, type_facts, effect_catalog).run()

    @staticmethod
    def _alias_name(c_type: object, aliases: set[str] | frozenset[str]) -> str | None:
        """Return an unadorned typedef name from one rendered C type."""
        text = str(c_type).strip()
        if "*" in text or any(character in text for character in "[]()"):
            return None
        words = [word for word in text.split() if word not in _TYPE_QUALIFIERS]
        return words[0] if len(words) == 1 and words[0] in aliases else None

    @staticmethod
    def _pointer_base_alias(c_type: object, aliases: set[str] | frozenset[str]) -> str | None:
        text = str(c_type).replace("*", " ")
        words = [word for word in text.split() if word not in _TYPE_QUALIFIERS]
        return words[0] if len(words) == 1 and words[0] in aliases else None

    @staticmethod
    def _pointer_stars(c_type: object) -> int:
        return str(c_type).count("*")

    @staticmethod
    def pointer_type_facts(module) -> PointerTypeFacts:
        """Resolve pointer shape and pointee constness through typedef chains."""
        definitions = {declaration.name: declaration for declaration in module.typedef_defs}
        aliases: set[str] = set()
        changed = True
        while changed:
            changed = False
            for name, declaration in definitions.items():
                target = str(declaration.target_type).strip()
                inherited = ExceptionLowerer._alias_name(target, set(definitions))
                is_pointer = "*" in target or inherited in aliases
                if is_pointer and name not in aliases:
                    aliases.add(name)
                    changed = True
        depths: dict[str, int] = {}
        changed = True
        while changed:
            changed = False
            for name, declaration in definitions.items():
                target = str(declaration.target_type).strip()
                stars = ExceptionLowerer._pointer_stars(target)
                inherited = ExceptionLowerer._alias_name(target, set(definitions))
                pointer_base = ExceptionLowerer._pointer_base_alias(target, set(definitions))
                ready = stars > 0
                depth = stars
                if stars == 0 and inherited is not None and (inherited in depths):
                    ready = True
                    depth = depths[inherited]
                elif stars > 0 and pointer_base in aliases:
                    ready = pointer_base in depths
                    if ready:
                        depth += depths[pointer_base]
                if ready and name not in depths:
                    depths[name] = depth
                    changed = True
        read_only: set[str] = set()
        changed = True
        while changed:
            changed = False
            for name, declaration in definitions.items():
                target = str(declaration.target_type).strip()
                inherited = ExceptionLowerer._alias_name(target, set(definitions))
                pointer_base = ExceptionLowerer._pointer_base_alias(target, set(definitions))
                is_read_only = (
                    inherited in read_only
                    if "*" not in target
                    else target.startswith("const ") and target.count("*") == 1 and (pointer_base not in aliases)
                )
                if is_read_only and name not in read_only:
                    read_only.add(name)
                    changed = True
        void_aliases: set[str] = set()
        changed = True
        while changed:
            changed = False
            for name, declaration in definitions.items():
                target = str(declaration.target_type).strip()
                inherited = ExceptionLowerer._alias_name(target, set(definitions))
                words = [word for word in target.split() if word not in _TYPE_QUALIFIERS]
                if (words == ["void"] or inherited in void_aliases) and name not in void_aliases:
                    void_aliases.add(name)
                    changed = True
        return PointerTypeFacts(
            aliases=frozenset(aliases),
            read_only_pointee_aliases=frozenset(read_only),
            alias_depths=depths,
            void_aliases=frozenset(void_aliases),
        )

    @staticmethod
    def reject_inferred_volatile_aliases(function, inferred: set[int], globals_by_name) -> None:
        """Fail before C emission when an implicit qualifier cannot be preserved."""
        _QualifierSafety(function.params, inferred, globals_by_name).block(function.body)

    @staticmethod
    def reject_volatile_global_aliases(module) -> dict[str, IRGlobalDecl]:
        """Validate global initializers and return their C-name lookup."""
        globals_by_name = {declaration.name: declaration for declaration in module.global_decls}
        safety = _QualifierSafety((), set(), globals_by_name)
        for declaration in module.global_decls:
            safety._expression(declaration.array_size, ())
            safety._expression(declaration.init, ())
        return globals_by_name

    @staticmethod
    def compiler_storage_name(name: str) -> bool:
        """Whether a C binding is compiler-authored rather than source-renamed."""
        return name.startswith("__btrc_") and (not name.startswith("__btrc_source_"))

    @staticmethod
    def _statement_expressions(statement):
        if isinstance(statement, IRVarDecl):
            return (statement.array_size, statement.init)
        if isinstance(statement, IRAssign):
            return (statement.target, statement.value)
        if isinstance(statement, IRExprStmt):
            return (statement.expr,)
        return ()

    @staticmethod
    def _automatic(declaration: IRVarDecl) -> bool:
        return not declaration.is_static and (not declaration.is_extern)

    @staticmethod
    def apply_setjmp_volatility(module: IRModule) -> None:
        """Qualify automatics directly modified after a generated ``setjmp``.

        Declarations created in a try/catch branch occur after its setjmp, while
        declarations in completed sibling blocks are out of scope. Unmodified
        visible values also retain their pre-setjmp value under C11 and must not be
        needlessly qualified: doing so can make an otherwise valid pointer to an
        aggregate incompatible with its declared C API. Source address/array
        aliases visible across setjmp are treated conservatively and rejected by
        the qualifier-safety pass because layered pointee qualifiers are not yet
        representable in the source type model.
        """
        globals_by_name = ExceptionLowerer.reject_volatile_global_aliases(module)
        if not any(ExceptionLowerer.contains_setjmp(function.body) for function in module.function_defs):
            return
        call_effects = ExceptionLowerer.build_setjmp_call_effects(module)
        for function in module.function_defs:
            ExceptionLowerer.reject_unmodelled_setjmp_captures(function, call_effects[function.name])
            visibility = _LexicalVisibilityPass(function.params, call_effects[function.name])
            visibility.block(function.body)
            ExceptionLowerer.reject_inferred_volatile_aliases(function, visibility.inferred_volatile, globals_by_name)

    def _require_setjmp(self):
        """Register the header even for try/throw nested inside lifted bodies."""
        self._session.require_runtime_header("setjmp.h")

    @contextmanager
    def try_catch_scope(self, node: TryCatchStmt, provenance: CallableProvenance):
        """Own the lifetime of one structured try/catch lowering transaction."""
        self._session.in_trycatch_depth += 1
        try:
            yield self._create_try_catch_plan(node, provenance)
        finally:
            self._session.in_trycatch_depth -= 1

    def _create_try_catch_plan(self, node: TryCatchStmt, provenance: CallableProvenance) -> TryCatchPlan:
        self._require_setjmp()
        self._session.require_helper("__btrc_trycatch_globals")
        self._session.require_helper("__btrc_push_try")
        self._session.require_helper("__btrc_throw")
        finally_only = node.catch_block is None and node.finally_block is not None
        try_terminates = finally_only and ControlFlowAnalyzer.block_must_terminate(node.try_block)
        pending_name = (
            self._session.fresh_temp("__btrc_finally_pending") if finally_only and (not try_terminates) else None
        )
        error_name = self._session.fresh_temp("__btrc_finally_error") if finally_only else ""
        return TryCatchPlan(
            source=node,
            incoming=provenance.snapshot(),
            finally_only=finally_only,
            try_terminates=try_terminates,
            pending_name=pending_name,
            error_name=error_name,
            statements=[IRExprStmt(expr=IRCall(callee="__btrc_push_try", args=[], helper_ref="__btrc_push_try"))],
        )

    @contextmanager
    def try_body_scope(self, plan: TryCatchPlan, provenance: CallableProvenance):
        """Isolate the ordinary statement traversal for a try branch."""
        self._session.in_try_depth += 1
        self._ownership.push_control_context("try")
        plan.exceptional_capture = provenance.begin_exception_capture()
        try:
            with provenance.isolated_flow() as try_isolation:
                yield
            assert try_isolation.outgoing is not None
            plan.try_flow = try_isolation.outgoing
        finally:
            if plan.exceptional_capture is None:
                exceptional_flows = []
            else:
                exceptional_flows = provenance.finish_exception_capture(plan.exceptional_capture)
            self._ownership.pop_control_context()
            self._session.in_try_depth -= 1
        if plan.try_body is None or plan.try_flow is None:
            raise CodegenError("try branch was not materialized")
        if self._session.uses_any_helper({"__btrc_register_cleanup", "__btrc_register_direct_cleanup"}):
            self._session.require_helper("__btrc_discard_cleanups")
            plan.try_body.stmts.append(
                IRExprStmt(
                    expr=IRCall(
                        callee="__btrc_discard_cleanups",
                        args=[IRVar(name="__btrc_try_top")],
                        helper_ref="__btrc_discard_cleanups",
                    )
                )
            )
        plan.try_body.stmts.extend(ExceptionLowerer.pop_try_frames(1))
        provenance.join_flows(*exceptional_flows, plan.try_flow)
        plan.exceptional_entry = provenance.snapshot()
        if plan.finally_only:
            plan.statements.extend(ExceptionLowerer.finally_state_declarations(plan.error_name, plan.pending_name))
            plan.catch_body = IRBlock(stmts=ExceptionLowerer.capture_finally_error(plan.error_name, plan.pending_name))
            plan.catch_flow = plan.exceptional_entry
        else:
            plan.catch_bindings = tuple(self._catch_bindings(plan.source))

    @contextmanager
    def catch_body_scope(self, plan: TryCatchPlan, provenance: CallableProvenance):
        """Isolate ordinary statement traversal for an explicit catch branch."""
        if plan.finally_only:
            raise CodegenError("finally-only transaction has no source catch block")
        with provenance.isolated_flow() as catch_isolation:
            yield plan.catch_bindings
        assert catch_isolation.outgoing is not None
        plan.catch_flow = catch_isolation.outgoing

    def prepare_finally(self, plan: TryCatchPlan, provenance: CallableProvenance) -> None:
        """Join try/catch flows before an optional finally block is traversed."""
        if plan.try_body is None or plan.try_flow is None:
            raise CodegenError("try branch was not completed")
        if plan.catch_body is None or plan.catch_flow is None:
            raise CodegenError("catch branch was not completed")
        try_falls_through = IRStatementSequence(plan.try_body.stmts).may_fall_through()
        catch_falls_through = IRStatementSequence(plan.catch_body.stmts).may_fall_through()
        continuation_flows: list[CallableFlowSnapshot] = []
        if try_falls_through:
            continuation_flows.append(plan.try_flow)
        if not plan.finally_only and catch_falls_through:
            continuation_flows.append(plan.catch_flow)
        plan.continuation_flows = tuple(continuation_flows)
        if plan.source.finally_block:
            provenance.join_flows(plan.try_flow, plan.catch_flow)
        elif continuation_flows:
            provenance.join_flows(*continuation_flows)
        else:
            provenance.restore(plan.incoming)

    @contextmanager
    def finally_body_scope(self, plan: TryCatchPlan, provenance: CallableProvenance):
        """Capture mutations made by an ordinary lowered finally block."""
        plan.finally_capture = provenance.begin_mutation_capture()
        try:
            yield
        finally:
            plan.finally_mutations = provenance.finish_mutation_capture(plan.finally_capture)
        plan.finally_result = provenance.snapshot()

    def materialize_try_catch(self, plan: TryCatchPlan, provenance: CallableProvenance) -> list[IRStmt]:
        """Materialize a completed try/catch/finally transaction."""
        if plan.try_body is None or plan.catch_body is None:
            raise CodegenError("try/catch branches were not materialized")
        plan.statements.append(
            IRIf(
                condition=ExceptionLowerer.setjmp_success_condition(),
                then_block=plan.try_body,
                else_block=plan.catch_body,
            )
        )
        if plan.source.finally_block:
            if plan.finally_body is None or plan.finally_result is None:
                raise CodegenError("finally branch was not materialized")
            plan.statements.extend(plan.finally_body.stmts)
            if plan.finally_only:
                plan.statements.append(ExceptionLowerer.rethrow_finally_error(plan.error_name, plan.pending_name))
            if plan.continuation_flows and IRStatementSequence(plan.statements).may_fall_through():
                continuation_entry = provenance.merge_flows(*plan.continuation_flows)
                provenance.restore(
                    provenance.project_mutations(
                        all_result=plan.finally_result,
                        continuation_entry=continuation_entry,
                        mutated=plan.finally_mutations,
                    )
                )
            else:
                provenance.restore(plan.incoming)
        return plan.statements

    def _catch_bindings(self, node):
        if not node.catch_var:
            return []
        from src.compiler.python.syntax.ast.generated import TypeExpr

        self._session.require_helper("__btrc_strdup")
        self._session.require_helper("__btrc_str_track")
        return [
            ExceptionBinding(
                name=node.catch_var,
                c_type="char*",
                type_expr=TypeExpr(base="string"),
                value=IRCall(
                    callee="__btrc_str_track",
                    args=[
                        IRCall(
                            callee="__btrc_strdup", args=[IRVar(name="__btrc_error_msg")], helper_ref="__btrc_strdup"
                        )
                    ],
                    helper_ref="__btrc_str_track",
                ),
                owned=True,
            )
        ]

    def lower_throw(self, node: ThrowStmt, provenance: CallableProvenance) -> list[IRStmt]:
        self._require_setjmp()
        self._session.require_helper("__btrc_throw")
        expr = self._expressions.lower_expr(
            node.expr,
            provenance,
        )
        return [
            IRExprStmt(expr=IRCall(callee="__btrc_throw", args=[expr], helper_ref="__btrc_throw", never_returns=True))
        ]

    @staticmethod
    def setjmp_success_condition():
        """Build ``setjmp(current_frame.env) == 0`` without rendered C."""
        frame = IRIndex(obj=IRVar(name="__btrc_try_stack"), index=IRVar(name="__btrc_try_top"))
        return IRBinOp(
            left=IRCall(callee="setjmp", args=[IRFieldAccess(obj=frame, field="env", arrow=True)]),
            op="==",
            right=IRLiteral(text="0"),
        )

    @staticmethod
    def pop_try_frames(depth: int) -> list[IRExprStmt]:
        """Discard ``depth`` active generated try frames."""
        if depth <= 0:
            return []
        top = IRVar(name="__btrc_try_top")
        if depth == 1:
            expression = IRUnaryOp(op="--", operand=top, prefix=False)
        else:
            expression = IRBinOp(left=top, op="-=", right=IRLiteral(text=str(depth)))
        return [IRExprStmt(expr=expression)]

    @staticmethod
    def finally_state_declarations(error_name, pending_name=None):
        """Declare stable state for an exception crossing a finally body."""
        declarations = []
        if pending_name is not None:
            declarations.append(IRVarDecl(c_type=CType(text="bool"), name=pending_name, init=IRLiteral(text="false")))
        declarations.append(
            IRVarDecl(
                c_type=CType(text="char"), name=error_name, array_size=IRLiteral(text="1024"), init=IRLiteral(text='""')
            )
        )
        return declarations

    @staticmethod
    def capture_finally_error(error_name, pending_name=None):
        """Copy the active runtime error into a finally-only handler's state."""
        statements = []
        if pending_name is not None:
            statements.append(IRAssign(target=IRVar(name=pending_name), value=IRLiteral(text="true")))
        statements.append(
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_copy_error_message",
                    args=[
                        IRCast(target_type=CType(text="char*"), expr=IRVar(name=error_name)),
                        IRSizeof(operand=IRVar(name=error_name)),
                        IRVar(name="__btrc_error_msg"),
                    ],
                    helper_ref="__btrc_copy_error_message",
                )
            )
        )
        return statements

    @staticmethod
    def finally_error_message(error_name):
        """View volatile setjmp-preserved storage through a read-only C API."""
        return IRCast(target_type=CType(text="const char*"), expr=IRVar(name=error_name))

    @staticmethod
    def rethrow_finally_error(error_name, pending_name=None):
        """Build the structured rethrow after a single shared finally body."""
        rethrow = IRExprStmt(
            expr=IRCall(
                callee="__btrc_throw",
                args=[ExceptionLowerer.finally_error_message(error_name)],
                helper_ref="__btrc_throw",
                never_returns=True,
            )
        )
        if pending_name is None:
            return rethrow
        return IRIf(condition=IRVar(name=pending_name), then_block=IRBlock(stmts=[rethrow]))
