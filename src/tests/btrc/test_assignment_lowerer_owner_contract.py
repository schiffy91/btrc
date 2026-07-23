"""Ownership contracts for self-hosted assignment lowering."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def _source(relative: str) -> str:
    return (SELFHOST / relative).read_text()


def test_assignment_behavior_has_one_real_owner_and_no_free_api() -> None:
    assignment = _source("assignment_lowering.btrc")
    irgen = _source("irgen.btrc")
    boundary = _source("ownership_assignment_boundary.btrc")
    stage = _source("ir/stage.btrc")

    assert "class AssignmentLowerer {" in assignment
    assert not re.search(
        r"^(?:IRNode|Node|bool|int|string|void)\??\s+\w+\s*\(",
        assignment,
        re.MULTILINE,
    )
    assert "lowerAssignmentExpression(" not in assignment
    assert "lowerPlainAssignment(" not in assignment

    assert "class IRGen {" in irgen
    assert "public AssignmentLowerer assignments;" in irgen
    assert irgen.count("self.assignments = AssignmentLowerer(") == 1
    assert "return self.assignments.lower(self, node, varTypes);" in irgen
    assert "generator.assignments.lowerPlain(" in boundary
    assert "lowerPlainAssignment(" not in boundary
    assert stage.count('#include "../assignment_lowering.btrc"') == 1
    assert stage.index('#include "../assignment_lowering.btrc"') < stage.index('#include "../irgen.btrc"')


def test_assignment_owner_keeps_only_durable_domain_collaborators() -> None:
    assignment = _source("assignment_lowering.btrc")
    owner = assignment.split("class AssignmentLowerer {", 1)[1]
    private_state = [
        line.strip() for line in owner.splitlines() if line.startswith("    private ") and line.rstrip().endswith(";")
    ]
    assert private_state == [
        "private Analyzed analysis;",
        "private CallableBoundaryPolicy callableBoundaries;",
        "private CallableFlowState callableFlow;",
    ]
    assert "private IRGen" not in owner
    assert "self.generator" not in owner
    assert "class IRNode lower(" not in owner
    assert "public IRNode lower(" in owner
    assert "public IRNode lowerPlain(" in owner


def test_assignment_recursion_host_dependency_surface_is_assignment_scoped() -> None:
    assignment = _source("assignment_lowering.btrc")
    dependencies = set(re.findall(r"\bgenerator\.([A-Za-z_]\w*)", assignment))
    assert dependencies == {
        "assignmentCallableContext",
        "callableValueEscapes",
        "directGenericTargetC",
        "inGenericMethod",
        "lowerAssignedValue",
        "lowerBraceInit",
        "lowerDirectCompound",
        "lowerDirectStore",
        "lowerExpr",
        "lowerIndirectAssignment",
        "lowerListLiteral",
        "lowerManagedFieldAssignment",
        "lowerMapLiteral",
        "rejectClosureEscape",
        "resolvedExpressionType",
        "upcastClassPointer",
    }

    for unrelated_state in (
        "managedStack",
        "scopeStarts",
        "currentReturn",
        "gpuHost",
        "runtimeHelpers",
        "curModule",
    ):
        assert unrelated_state not in assignment
