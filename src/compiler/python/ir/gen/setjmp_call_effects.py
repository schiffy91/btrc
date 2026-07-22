"""Interprocedural pointer effects used by C11 setjmp qualification."""

from __future__ import annotations

from dataclasses import dataclass

from ...hosted_abi import hosted_function
from ...hosted_abi_model import (
    CONSUME,
    MUTATE,
    RETURN_ALIAS,
    RETURN_OPAQUE,
    UNKNOWN,
)
from ..nodes import IRModule
from .setjmp_effect_model import (
    FunctionEffect,
    ParameterEffect,
    PointerFlowResult,
    Storage,
)
from .setjmp_pointer_flow import analyze_pointer_flow
from .setjmp_pointer_types import (
    OPAQUE_POINTER_DEPTH,
    PointerTypeFacts,
    pointer_type_facts,
)
from .setjmp_storage_names import compiler_storage_name


def _merge_effect(left: FunctionEffect, right: FunctionEffect) -> FunctionEffect:
    return FunctionEffect(
        writes=left.writes | right.writes,
        captures=left.captures | right.captures,
        returns=left.returns | right.returns,
        unknown_return=left.unknown_return or right.unknown_return,
    )


def _unknown_effect(count: int) -> FunctionEffect:
    parameters = frozenset(ParameterEffect(index) for index in range(count))
    return FunctionEffect(
        writes=parameters,
        captures=parameters,
        unknown_return=True,
    )


def _hosted_effect(name: str, count: int) -> FunctionEffect | None:
    spec = hosted_function(name)
    if spec is None:
        return None
    if spec.parameters is None:
        return _unknown_effect(count)
    writes = set()
    captures = set()
    for index in range(count):
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


def _external_effect(declaration, type_facts: PointerTypeFacts) -> FunctionEffect:
    hosted = _hosted_effect(declaration.name, len(declaration.params))
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


def _global_storages(module, type_facts) -> dict[str, Storage]:
    return {
        declaration.name: Storage(
            name=declaration.name,
            identity=id(declaration),
            kind="global",
            pointer_depth=type_facts.pointer_depth(declaration.c_type),
            is_array=declaration.array_size is not None or declaration.is_unsized_array,
            compiler_owned=compiler_storage_name(declaration.name),
        )
        for declaration in module.global_decls
    }


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


def _flow_effect(flow: PointerFlowResult, parameters) -> FunctionEffect:
    writes = set()
    for origins in flow.writes.values():
        writes.update(origins)
    return FunctionEffect(
        writes=_parameter_effects(writes, parameters),
        captures=_parameter_effects(flow.captures, parameters),
        returns=_parameter_effects(flow.returns, parameters),
    )


@dataclass(frozen=True)
class SetjmpCallEffects:
    function_effects: dict[str, FunctionEffect]
    external_effects: dict[str, FunctionEffect]
    flow: PointerFlowResult

    def effect_for(self, callee: object, count: int) -> FunctionEffect:
        if not isinstance(callee, str):
            return _unknown_effect(count)
        if callee in self.function_effects:
            return self.function_effects[callee]
        if callee in self.external_effects:
            return self.external_effects[callee]
        return _hosted_effect(callee, count) or _unknown_effect(count)

    def written_arguments(self, callee: object, count: int) -> frozenset[int] | None:
        effect = self.effect_for(callee, count)
        return frozenset(item.index for item in effect.writes)

    def pointer_roots(self, value: object) -> set[str]:
        return {origin.storage.name for origin in self.flow.origins.get(id(value), ()) if origin.depth == 0}


def build_setjmp_call_effects(module: IRModule) -> dict[str, SetjmpCallEffects]:
    """Compute write, return-alias, and capture summaries to a fixed point."""

    type_facts = pointer_type_facts(module)
    definitions = {function.name: function for function in module.function_defs}
    external = {
        declaration.name: _external_effect(declaration, type_facts)
        for declaration in module.function_decls
        if declaration.name not in definitions
    }
    globals_by_name = _global_storages(module, type_facts)
    summaries = {name: FunctionEffect() for name in definitions}
    flows: dict[str, PointerFlowResult] = {}

    def lookup(callee, count):
        if isinstance(callee, str) and callee in summaries:
            return summaries[callee]
        if isinstance(callee, str) and callee in external:
            return external[callee]
        if isinstance(callee, str):
            return _hosted_effect(callee, count) or _unknown_effect(count)
        return _unknown_effect(count)

    # The monotone summary lattice is finite: for each parameter, an effect
    # depth is either the saturated opaque sentinel or one of its declared
    # pointer levels. PointerFlow never manufactures a larger exact depth.
    changed = True
    while changed:
        changed = False
        for name, function in definitions.items():
            flow = analyze_pointer_flow(function, globals_by_name, type_facts, lookup)
            parameters = [flow.storages[id(parameter)] for parameter in function.params]
            summary = _merge_effect(summaries[name], _flow_effect(flow, parameters))
            flows[name] = flow
            if summary != summaries[name]:
                summaries[name] = summary
                changed = True

    # Refresh contextual node facts after the last summary growth.
    flows = {
        name: analyze_pointer_flow(function, globals_by_name, type_facts, lookup)
        for name, function in definitions.items()
    }
    return {name: SetjmpCallEffects(summaries, external, flows[name]) for name in definitions}


__all__ = ["SetjmpCallEffects", "build_setjmp_call_effects"]
