"""Performance contracts for self-hosted ARC cycle classification."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def test_runtime_cycle_queries_cache_positive_and_negative_results() -> None:
    generator = (SELFHOST / "irgen.btrc").read_text()
    cycles = (SELFHOST / "cycle_semantics.btrc").read_text()
    start = cycles.index(
        "public bool runtimeTypeMayCycle(")
    end = cycles.index("\n    }", start)
    implementation = cycles[start:end]

    assert "class CycleMetadata {" in cycles
    assert "private Map<string, bool> runtimeTypeKnown;" in cycles
    assert (
        "private Map<string, bool> runtimeTypeMayCycleValues;"
        in cycles
    )
    assert "self.runtimeTypeKnown.has(runtimeType)" in implementation
    assert (
        "self.runtimeTypeMayCycleValues.get(runtimeType)"
        in implementation
    )
    assert "self.runtimeTypeKnown.put(runtimeType, true)" in implementation
    assert (
        "self.runtimeTypeMayCycleValues.put(runtimeType, result)"
        in implementation
    )
    assert "cyclableRuntimeTypeKnown" not in generator
    assert "cyclableRuntimeTypeValues" not in generator


def test_unknown_runtime_types_fail_conservatively() -> None:
    cycles = (SELFHOST / "cycle_semantics.btrc").read_text()
    start = cycles.index(
        "private bool computeRuntimeTypeMayCycle(")
    end = cycles.index(
        "public bool runtimeTypeMayCycle(", start)
    implementation = cycles[start:end]

    assert "return true;" in implementation
    assert "Conservatively select the full release path" in implementation
