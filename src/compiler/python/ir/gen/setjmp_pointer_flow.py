"""Flow-sensitive pointer provenance for setjmp effect analysis."""

from __future__ import annotations

from ..nodes import (
    IRAssign,
    IRBlock,
    IRDoWhile,
    IRExprStmt,
    IRFor,
    IRIf,
    IRReturn,
    IRSwitch,
    IRVarDecl,
    IRWhile,
)
from .setjmp_effect_model import PointerFlowResult, PointerOrigin, Storage
from .setjmp_pointer_flow_exprs import PointerExpressionFlowMixin
from .setjmp_storage_names import compiler_storage_name

AliasState = dict[Storage, set[PointerOrigin]]


def _copy_state(state: AliasState) -> AliasState:
    return {storage: set(origins) for storage, origins in state.items()}


def _join_states(*states: AliasState) -> AliasState:
    joined: AliasState = {}
    for state in states:
        for storage, origins in state.items():
            joined.setdefault(storage, set()).update(origins)
    return joined


class PointerFlow(PointerExpressionFlowMixin):
    """Interpret pointer values while retaining structured storage identity."""

    def __init__(self, function, globals_by_name, type_facts, effect_lookup):
        self.function = function
        self.type_facts = type_facts
        self.effect_lookup = effect_lookup
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
                compiler_owned=compiler_storage_name(parameter.name),
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
            compiler_owned=compiler_storage_name(declaration.name),
        )
        self.bindings[declaration.name] = storage
        self.result.storages[id(declaration)] = storage
        return storage

    def _block(self, block: IRBlock | None, state: AliasState, *, scoped: bool = True) -> AliasState:
        if block is None:
            return state
        saved_bindings = dict(self.bindings)
        current = _copy_state(state)
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
            if storage.is_pointer and not storage.is_array:
                current[storage] = set(origins)
                if origins and not storage.automatic:
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
            left = self._block(statement.then_block, _copy_state(current))
            right = self._block(statement.else_block, _copy_state(current))
            return _join_states(left, right)
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
        entry = _copy_state(state)
        header = _copy_state(state)
        for _ in range(16):
            _, conditioned = self._expression(statement.condition, _copy_state(header))
            body = self._block(statement.body, conditioned)
            updated = _join_states(entry, body)
            if updated == header:
                return updated
            header = updated
        return self._widen(header)

    def _for(self, statement: IRFor, state: AliasState) -> AliasState:
        saved_bindings = dict(self.bindings)
        current = self._statement(statement.init, state) if statement.init is not None else _copy_state(state)
        entry = _copy_state(current)
        header = _copy_state(current)
        for _ in range(16):
            _, conditioned = self._expression(statement.condition, _copy_state(header))
            body = self._block(statement.body, conditioned)
            _, back = self._expression(statement.update, body)
            updated = _join_states(entry, back)
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
        exits = [_copy_state(entry)]
        fallthrough = None
        for case in statement.cases:
            start = _join_states(entry, fallthrough or {})
            _, start = self._expression(case.value, start)
            output = self._block(IRBlock(case.body), start)
            if case.falls_through:
                fallthrough = output
            else:
                exits.append(output)
                fallthrough = None
        if fallthrough is not None:
            exits.append(fallthrough)
        return _join_states(*exits)

    @staticmethod
    def _widen(state: AliasState) -> AliasState:
        all_origins = set().union(*state.values()) if state else set()
        return {storage: set(all_origins if storage.is_pointer else origins) for storage, origins in state.items()}


def analyze_pointer_flow(function, globals_by_name, type_facts, effect_lookup):
    return PointerFlow(function, globals_by_name, type_facts, effect_lookup).run()


__all__ = ["analyze_pointer_flow"]
