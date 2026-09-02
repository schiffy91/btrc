"""Ownership contracts for self-hosted assignment lowering."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def _source(relative: str) -> str:
    return (SELFHOST / relative).read_text()


def test_assignment_behavior_has_one_real_owner_and_no_free_api() -> None:
    assignment = _source("ir/lowering/assignments.btrc")
    expressions = _source("ir/lowering/expressions.btrc")
    composition = _source("ir/lowering/lowerer.btrc")

    assert "class AssignmentLowerer {" in assignment
    assert not re.search(
        r"^(?:IRNode|Node|bool|int|string|void)\??\s+\w+\s*\(",
        assignment,
        re.MULTILINE,
    )
    assert "public AssignmentPlan plan(" in assignment
    assert "public IRNode materializePlain(" in assignment
    assert "private AssignmentLowerer assignments;" in expressions
    assert "self.assignments.plan(" in expressions
    assert "self.assignments.materializePlain(" in expressions
    assert composition.count("AssignmentLowerer(") == 1
    assert "IRGen" not in assignment + expressions + composition


def test_assignment_owner_keeps_only_durable_domain_collaborators() -> None:
    assignment = _source("ir/lowering/assignments.btrc")
    owner = assignment.split("class AssignmentLowerer {", 1)[1]
    private_state = [
        line.strip()
        for line in owner.splitlines()
        if line.strip().startswith("private ") and line.rstrip().endswith(";")
    ]
    assert private_state == [
        "private ExpressionTypeResolver expressionTypes;",
        "private CallableValueSemantics callableValues;",
        "private CallableBoundaryPolicy callableBoundaries;",
    ]
    assert "CallableFlowState callableFlow" in owner
    assert "IRLowerer" not in owner
    assert "ExpressionLowerer" not in owner
    assert "generator" not in owner
    assert "lowerExpr" not in owner
