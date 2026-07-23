"""Owner and lifecycle contracts for self-hosted managed-value lowering."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def _source(name: str) -> str:
    return (SELFHOST / name).read_text()


def test_managed_domains_are_real_injected_compilation_owners() -> None:
    analyzer = _source("semantic_analyzer.btrc")
    pipeline = _source("pipeline/pipeline.btrc")
    generator = _source("irgen.btrc")
    stage = _source("analyzer/stage.btrc")

    assert '#include "../managed_value_semantics.btrc"' in stage
    assert '#include "../cycle_semantics.btrc"' in stage
    assert "private ManagedValueSemantics managedValues;" in analyzer
    assert "private CycleMetadata cycles;" in analyzer
    assert "self.managedValues = ManagedValueSemantics(self.analysis);" in analyzer
    assert "self.cycles = CycleMetadata(" in analyzer
    assert "analyzer.managedValueSemantics(), analyzer.cycleMetadata()," in pipeline
    assert "public ManagedValueSemantics managedValues;" in generator
    assert "public CycleMetadata cycles;" in generator


def test_managed_owner_modules_have_no_loose_behavior() -> None:
    for name in (
        "managed_value_semantics.btrc",
        "cycle_semantics.btrc",
        "cleanup_slots.btrc",
        "cleanup_validation.btrc",
    ):
        source = _source(name)
        loose = re.findall(
            r"^(?:bool|void|string|Node\??|IRNode|IRFunction\??|"
            r"IRCleanupSlot)\s+[A-Za-z_]\w*\s*\(",
            source,
            flags=re.MULTILINE,
        )
        assert loose == [], f"{name} has unowned behavior: {loose}"


def test_cleanup_registry_is_per_generation_and_uses_parse_safe_api() -> None:
    registry = _source("cleanup_slots.btrc")
    validator = _source("cleanup_validation.btrc")
    generator = _source("irgen.btrc")
    generate = generator[
        generator.index("public IRModule generate(") :
        generator.index("public void emitFunctionPointerTypedefs(")
    ]

    assert "class CleanupSlotRegistry {" in registry
    assert "public IRNode registerSlot(" in registry
    assert "public IRNode register(" not in registry
    assert ".register(" not in "\n".join(
        path.read_text() for path in SELFHOST.rglob("*.btrc")
    )
    assert "public CleanupSlotRegistry cleanupSlots;" in generator
    reset = generate.index("self.cleanupSlots = CleanupSlotRegistry();")
    finalize = generate.index("self.cleanupSlots.finalize(m);")
    validate = generate.index("CleanupSlotValidator(m).validate();")
    assert reset < finalize < validate
    for obsolete_field in (
        "cleanupTakeAdapters",
        "arcSlotAdapters",
        "mutexValueAdapters",
        "cleanupTakeAdapterDefinitions",
        "cleanupSlotCounter",
        "cleanupTakeAdaptersFinalized",
    ):
        assert f"public {obsolete_field}" not in generator

    assert "class CleanupSlotValidator {" in validator
    duplicate_check = validator.index("if (used.has(metadata.site))")
    record_use = validator.index("used.put(metadata.site, true)")
    assert duplicate_check < record_use
    assert "metadata.c_type != declared.c_type" in validator
    assert "metadata.take_function" in validator
    assert "!= declared.take_function" in validator


def test_isolated_scope_snapshots_active_cleanup_markers_exactly() -> None:
    generator = _source("irgen.btrc")
    snapshot = generator[
        generator.index("class ScopeSnapshot {") :
        generator.index("class IRGen {")
    ]
    isolated = generator[
        generator.index("public ScopeSnapshot enterIsolatedScope(") :
        generator.index("public void maybeRegisterCleanup(")
    ]

    assert "public Vector<string> activeCleanupMarkers;" in snapshot
    assert "snap.activeCleanupMarkers.push(" in isolated
    assert "self.activeCleanupMarkers.remove(" in isolated
    assert "self.activeCleanupMarkers.put(marker, true);" in isolated


def test_old_global_managed_and_cycle_query_apis_are_absent() -> None:
    source = "\n".join(
        path.read_text() for path in SELFHOST.rglob("*.btrc")
    )
    for obsolete in (
        "irManagedType(",
        "irManagedArcType(",
        "irManagedStringType(",
        "irManagedMutexType(",
        "irManagedRuntimeType(",
        "irManagedRuntimeCanCycle(",
        "genericCycleAppendRefs(",
        "bool genericInstanceNeedsVisitor(Analyzed",
        "cycleVisitorName(",
        "managedVisitorSymbol(",
        "registerCleanupSlot(",
        "validateCleanupSlots(",
    ):
        assert obsolete not in source
