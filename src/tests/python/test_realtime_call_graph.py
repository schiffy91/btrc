"""Bounded cycle classification and unchanged realtime witness contracts."""

from __future__ import annotations

import itertools

import pytest

from src.compiler.python.analyzer.program import AnalysisSession, DeclarationIndex
from src.compiler.python.analyzer.realtime import RealtimeAnalyzer, RealtimeCallable, RealtimeEdge, RealtimeEffect
from src.compiler.python.runtime.catalog import RuntimeHelperCatalog
from src.compiler.python.syntax.ast import generated as ast
from src.tests.python.test_realtime import realtime_errors


def graph_analyzer(adjacency: dict[str, list[str]]) -> RealtimeAnalyzer:
    analyzer = RealtimeAnalyzer(AnalysisSession(), DeclarationIndex(), RuntimeHelperCatalog())
    analyzer.callables = {
        key: RealtimeCallable(
            key=key,
            label=key,
            declaration=ast.FunctionDecl(return_type=ast.TypeExpr(base="void"), name=key),
            body=None,
            source_file="graph.btrc",
            local_names=frozenset(),
            events=[RealtimeEdge(target, 1, index + 1) for index, target in enumerate(targets)],
        )
        for key, targets in adjacency.items()
    }
    return analyzer


def reachable_cycles(adjacency: dict[str, list[str]]) -> set[str]:
    """Independent per-root reachability oracle, used only for tiny graphs."""
    recursive = set()
    for root in adjacency:
        visited = set()
        pending = list(adjacency[root])
        while pending:
            key = pending.pop()
            if key == root:
                recursive.add(root)
                break
            if key not in visited and key in adjacency:
                visited.add(key)
                pending.extend(adjacency[key])
    return recursive


def test_cycle_components_match_every_three_vertex_directed_graph() -> None:
    edges = list(itertools.product(("a", "b", "c"), repeat=2))
    for mask in range(1 << len(edges)):
        adjacency = {key: [] for key in ("a", "b", "c")}
        for index, (source, target) in enumerate(edges):
            if mask & (1 << index):
                adjacency[source].append(target)
        assert graph_analyzer(adjacency)._recursive_callables() == reachable_cycles(adjacency), adjacency


def test_cycle_membership_ignores_effects_and_external_edges_not_callers() -> None:
    analyzer = graph_analyzer(
        {"caller": ["cycle", "external"], "cycle": ["cycle", "cycle", "leaf"], "leaf": [], "isolated": []}
    )
    analyzer.callables["leaf"].events.append(RealtimeEffect("IO", "read", 9, 4, "leaf.btrc"))
    assert analyzer._recursive_callables() == {"cycle"}
    assert graph_analyzer({})._recursive_callables() == set()


@pytest.mark.parametrize("cyclic", [False, True])
def test_deep_convergent_graph_scans_each_source_event_once(cyclic: bool) -> None:
    # There are exponentially many simple paths, but only 4,003 vertices.
    # The scan budget makes regressions fail promptly, without timing limits.
    layers = 2000
    adjacency = {"entry": ["left0", "right0"], "exit": ["entry"] if cyclic else [], "caller": ["entry"]}
    for layer in range(layers):
        targets = ["exit"] if layer == layers - 1 else [f"left{layer + 1}", f"right{layer + 1}"]
        adjacency[f"left{layer}"] = list(targets)
        adjacency[f"right{layer}"] = list(targets)
    analyzer = graph_analyzer(adjacency)
    total_events = sum(len(callable_.events) for callable_ in analyzer.callables.values())
    scanned = 0

    class BoundedEvents(list):
        def __iter__(self):
            nonlocal scanned
            for event in super().__iter__():
                scanned += 1
                assert scanned <= total_events * 2, "cycle classification revisited convergent source paths"
                yield event

    for callable_ in analyzer.callables.values():
        callable_.events = BoundedEvents(callable_.events)
    expected = set(adjacency) - {"caller"} if cyclic else set()
    assert analyzer._recursive_callables() == expected
    assert scanned == total_events


def test_convergent_realtime_source_is_proven_safe() -> None:
    functions = ["int finish(int value) { return value; }"]
    for layer in reversed(range(40)):
        calls = "finish(value)" if layer == 39 else f"left{layer + 1}(value) + right{layer + 1}(value)"
        functions.extend(
            [f"int left{layer}(int value) {{ return {calls}; }}", f"int right{layer}(int value) {{ return {calls}; }}"]
        )
    functions.append("@realtime int audio(int value) { return left0(value) + right0(value); }")
    assert realtime_errors("\n".join(functions)) == []


@pytest.mark.parametrize("cycle_first", [False, True])
def test_cycle_classification_preserves_source_ordered_witness(cycle_first: bool) -> None:
    analyzer = graph_analyzer(
        {"audio": ["cycle", "effect"] if cycle_first else ["effect", "cycle"], "cycle": ["cycle"], "effect": []}
    )
    effect = RealtimeEffect("IO", "read", 13, 7, "effect.btrc")
    analyzer.callables["effect"].events.append(effect)
    witness = analyzer._fixed_point()["audio"]
    if cycle_first:
        assert witness.effect == RealtimeEffect("blocking", "recursive call cycle", 1, 1, "graph.btrc")
        assert [edge.target for edge in witness.path] == ["cycle", "cycle"]
    else:
        assert witness.effect == effect
        assert [edge.target for edge in witness.path] == ["effect"]


def test_self_recursion_preserves_exact_source_diagnostic() -> None:
    assert realtime_errors("@realtime int audio(int value) { return audio(value); }") == [
        "@realtime callable 'audio' reaches forbidden blocking operation 'recursive call cycle' via audio -> audio at 1:41"
    ]
