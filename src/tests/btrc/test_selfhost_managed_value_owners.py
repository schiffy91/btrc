"""Owner and lifecycle contracts for self-hosted managed-value lowering."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def _source(name: str) -> str:
    return (SELFHOST / name).read_text()


def test_managed_domains_are_real_injected_compilation_owners() -> None:
    analyzer = _source("analyzer/analyzer.btrc")
    pipeline = _source("pipeline/pipeline.btrc")
    lowerer = _source("ir/lowering/lowerer.btrc")
    stage = _source("analyzer/stage.btrc")

    assert "import ./ownership/values.btrc;" in stage
    assert "import ./ownership/cycles.btrc;" in stage
    assert "private ManagedValueSemantics managedValues;" in analyzer
    assert "private CycleSemantics cycles;" in analyzer
    assert "self.managedValues = ManagedValueSemantics(self.analysis);" in analyzer
    assert "self.cycles = CycleSemantics(" in analyzer
    assert "analyzer.managedValueSemantics(), analyzer.cycleSemantics()," in pipeline
    assert "ManagedValueSemantics managedValues," in lowerer
    assert "CycleSemantics cycles," in lowerer
    assert "ManagedLifetimeLowerer(" in lowerer
    assert "analyzed, managedValues, cycles," in lowerer
    assert "SemanticAnalyzer" not in lowerer


def test_managed_owner_modules_have_no_loose_behavior() -> None:
    for name in (
        "analyzer/ownership/values.btrc",
        "analyzer/ownership/cycles.btrc",
        "ir/lowering/ownership/lifetime.btrc",
        "ir/optimization/cleanup.btrc",
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
    registry = _source("ir/lowering/ownership/lifetime.btrc")
    validator = _source("ir/optimization/cleanup.btrc")
    optimizer = _source("ir/optimization/optimizer.btrc")
    lowerer = _source("ir/lowering/lowerer.btrc")
    lower = lowerer[lowerer.index("public IRModule lower(") :]
    optimize = optimizer[
        optimizer.index("public void optimize(") : optimizer.index("private void eliminateUnreachable(")
    ]

    assert "class CleanupSlotRegistry {" in registry
    assert "public IRNode registerSlot(" in registry
    assert "public IRNode register(" not in registry
    assert ".register(" not in "\n".join(path.read_text() for path in SELFHOST.rglob("*.btrc"))
    assert "private CleanupSlotRegistry cleanupSlots;" in lowerer
    assert "self.cleanupSlots = CleanupSlotRegistry();" in lowerer
    reset = lower.index("self.cleanupSlots.reset();")
    finalize = lower.index("self.cleanupSlots.finalize(module);")
    assert reset < finalize
    assert "CleanupSlotValidator(module).validate();" not in lower
    assert "CleanupSlotValidator(module).validate();" in optimize
    for obsolete_field in (
        "cleanupTakeAdapters",
        "arcSlotAdapters",
        "mutexValueAdapters",
        "cleanupTakeAdapterDefinitions",
        "cleanupSlotCounter",
        "cleanupTakeAdaptersFinalized",
    ):
        assert f"public {obsolete_field}" not in lowerer

    assert "class CleanupSlotValidator {" in validator
    duplicate_check = validator.index("if (used.has(metadata.site))")
    record_use = validator.index("used.put(metadata.site, true)")
    assert duplicate_check < record_use
    assert "metadata.c_type != declared.c_type" in validator
    assert "metadata.take_function" in validator
    assert "!= declared.take_function" in validator


def test_isolated_scope_snapshots_active_cleanup_markers_exactly() -> None:
    functions = _source("ir/lowering/functions.btrc")
    lifetime = _source("ir/lowering/ownership/lifetime.btrc")
    snapshot = lifetime[
        lifetime.index("class ManagedLifetimeSnapshot {") : lifetime.index("class CleanupSlotRegistry {")
    ]
    isolate = lifetime[
        lifetime.index("public ManagedLifetimeSnapshot isolate()") : lifetime.index("private void clearState()")
    ]

    assert "public Vector<string> activeCleanupMarkers;" in snapshot
    assert "public ManagedLifetimeSnapshot lifetime;" in functions
    assert "snap.lifetime = self.managedLifetime.isolate();" in functions
    assert "self.managedLifetime.restore(snap.lifetime);" in functions
    assert "snapshot.activeCleanupMarkers" in isolate
    assert "self.activeCleanupMarkers.put(" in isolate


def test_old_global_managed_and_cycle_query_apis_are_absent() -> None:
    source = "\n".join(path.read_text() for path in SELFHOST.rglob("*.btrc"))
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
        "validateCleanupSlots(",
    ):
        assert obsolete not in source


def test_aggregate_ordering_uses_bounded_owners_and_typed_plans() -> None:
    aggregate = _source("ir/lowering/aggregates.btrc")
    ordering = _source("ir/lowering/ownership/operands.btrc")
    boundary = _source("ir/lowering/ownership/calls.btrc")
    releases = _source("ir/lowering/ownership/managed_types.btrc")
    lowerer = _source("ir/lowering/lowerer.btrc")
    release_slot = releases[releases.index("class ManagedReleaseSlot {") : releases.index("class ManagedTypeLowerer {")]

    assert "class OwnershipOperandEnvironment {" in ordering
    assert "private Map<string, Node> variableTypes;" in ordering
    assert "private Map<string, Node> typeParameters;" in ordering
    assert "class OwnershipOperandPlanner {" in ordering
    assert "private Analyzed analyzed;" in ordering
    assert "private OperatorSemantics operators;" in ordering
    assert "public bool requiresOrder(" in ordering
    assert "public bool hasEffect(" in ordering
    assert "public bool reorderInert(" in ordering
    assert "public void requireType(" in ordering

    assert "class AggregateEvaluationPlan {" in aggregate
    assert "class AggregateOperandPlan {" in aggregate
    assert "private ManagedValueSemantics managedValues;" in aggregate
    assert "private OwnershipOperandPlanner operandPlanner;" in aggregate
    assert "public bool requiresOrder(" not in aggregate

    for obsolete_loose_behavior in (
        "ownershipExpressionHasEffect(",
        "ownershipExpressionReorderInert(",
        "ownershipRequireType(",
        "ownershipOperandCType(",
    ):
        assert obsolete_loose_behavior not in boundary
        assert obsolete_loose_behavior not in lowerer

    assert "class ManagedReleaseSlotPlan {" in releases
    assert "class ManagedReleaseSlotPlanner {" in releases
    assert "private OwnershipOperandPlanner operandPlanner;" in releases
    assert "operandPlanner" not in release_slot
    assert "resolvedExpressionType" not in release_slot
    assert "generator.aggregateValues" not in releases
    assert "self.operandPlanner.requiresOrder(" in releases
    assert "private ManagedReleaseSlotPlanner releaseSlots;" in releases
    assert "self.releaseSlots = ManagedReleaseSlotPlanner(" in releases
    assert "OwnershipOperandPlanner operandPlanner = OwnershipOperandPlanner(" in lowerer
    assert "AggregateValueLowerer aggregateValues = AggregateValueLowerer(" in lowerer
    assert "analyzed, managedValues, operandPlanner);" in lowerer
