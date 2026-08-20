"""Performance contracts for self-hosted ARC cycle classification."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"
CYCLE_SEMANTICS = SELFHOST / "analyzer/ownership/cycles.btrc"


def test_runtime_cycle_queries_cache_positive_and_negative_results() -> None:
    cycles = CYCLE_SEMANTICS.read_text()
    other_units = "\n".join(path.read_text() for path in SELFHOST.rglob("*.btrc") if path != CYCLE_SEMANTICS)
    start = cycles.index("public bool runtimeTypeMayCycle(")
    end = cycles.index("\n    }", start)
    implementation = cycles[start:end]

    assert "class CycleSemantics {" in cycles
    assert "private Map<string, bool> runtimeTypeKnown;" in cycles
    assert "private Map<string, bool> runtimeTypeMayCycleValues;" in cycles
    assert "self.runtimeTypeKnown.has(runtimeType)" in implementation
    assert "self.runtimeTypeMayCycleValues.get(runtimeType)" in implementation
    assert "self.runtimeTypeKnown.put(runtimeType, true)" in implementation
    assert "self.runtimeTypeMayCycleValues.put(runtimeType, result)" in implementation
    assert "runtimeTypeKnown" not in other_units
    assert "runtimeTypeMayCycleValues" not in other_units


def test_unknown_runtime_types_fail_conservatively() -> None:
    cycles = CYCLE_SEMANTICS.read_text()
    start = cycles.index("private bool computeRuntimeTypeMayCycle(")
    end = cycles.index("public bool runtimeTypeMayCycle(", start)
    implementation = cycles[start:end]

    assert "return true;" in implementation
    assert "Conservatively select the full release path" in implementation
