"""Performance contracts for self-hosted ARC cycle classification."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def test_runtime_cycle_queries_cache_positive_and_negative_results() -> None:
    generator = (SELFHOST / "irgen.btrc").read_text()
    managed = (SELFHOST / "managed_value_lowering.btrc").read_text()
    start = managed.index("bool irManagedRuntimeCanCycle(")
    end = managed.index("\n}", start)
    implementation = managed[start:end]

    assert "cyclableRuntimeTypeKnown" in generator
    assert "cyclableRuntimeTypeValues" in generator
    assert "cyclableRuntimeTypeKnown.has(runtimeType)" in implementation
    assert "cyclableRuntimeTypeValues.get(runtimeType)" in implementation
    assert "cyclableRuntimeTypeValues.put(runtimeType, result)" in implementation
