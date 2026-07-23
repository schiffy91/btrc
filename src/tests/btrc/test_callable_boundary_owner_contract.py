"""Ownership contracts for self-hosted callback ABI boundary policy."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def _source(relative: str) -> str:
    return (SELFHOST / relative).read_text()


def test_callable_boundary_behavior_has_one_domain_owner() -> None:
    policy = _source("callable_boundary_policy.btrc")
    stage = _source("ir/stage.btrc")

    assert "class CallableBoundaryContext {" in policy
    assert "class CallableBoundaryPolicy {" in policy
    assert "private Analyzed analysis;" in policy
    assert "IRGen" not in policy
    assert not (SELFHOST / "callable_boundary_lowering.btrc").exists()
    assert not (SELFHOST / "callable_argument_boundaries.btrc").exists()
    assert '#include "../callable_argument_boundaries.btrc"' not in stage
    assert stage.index('#include "../callable_boundary_policy.btrc"') < stage.index('#include "../irgen.btrc"')

    for owned_operation in (
        "public int expressionAbi(",
        "public bool lexicalIdentifier(",
        "public void rejectPersistentStorage(",
        "public void rejectAggregateInitializer(",
        "public void rejectAssignment(",
        "public Vector<Node> functionPointerParameters(",
        "public void rejectUnsafeArguments(",
    ):
        assert owned_operation in policy

    combined = "\n".join(path.read_text() for path in SELFHOST.rglob("*.btrc"))
    for obsolete_loose_behavior in (
        "callableBoundaryCanonicalType(",
        "callableBoundaryManagedType(",
        "callableBoundaryUnsafeValue(",
        "callableBoundaryFunctionPointerParameters(",
        "rejectPersistentCallableBoundary(",
        "rejectAggregateCallableInitializerBoundary(",
        "rejectErasingCallableAssignmentBoundary(",
        "rejectUnsafeManagedCallbackArgumentBoundary(",
        "rejectUnsafeManagedCallbackArgumentsBoundary(",
    ):
        assert obsolete_loose_behavior not in combined


def test_callable_boundary_policy_is_per_lowerer_and_context_is_per_operation() -> None:
    policy = _source("callable_boundary_policy.btrc")
    irgen = _source("irgen.btrc")
    context = policy.split("class CallableBoundaryContext {", 1)[1].split("class CallableBoundaryPolicy {", 1)[0]
    owner = policy.split("class CallableBoundaryPolicy {", 1)[1]

    assert "public CallableBoundaryPolicy callableBoundaries;" in irgen
    assert irgen.count("self.callableBoundaries = CallableBoundaryPolicy(analyzed);") == 1
    assert "public CallableBoundaryContext callableBoundaryContext(" in irgen
    assert "self.activeTypeMap," in irgen
    assert "self.ownedCallableBindings," in irgen
    assert "self.ambiguousCallableBindings," in irgen
    assert "self.callableScopeDeclarations);" in irgen

    for operation_evidence in (
        "private Map<string, Node> variableTypes;",
        "private Map<string, Node> typeParameters;",
        "private bool resolvesTypeParameters;",
        "private Map<string, bool> ownedCallables;",
        "private Map<string, bool> ambiguousCallables;",
        "private Vector<string> lexicalCallableDeclarations;",
    ):
        assert operation_evidence in context
    for context_operation in (
        "public Node resolveType(",
        "public bool hasVariable(",
        "public Node variableType(",
        "public int abiFor(",
        "public bool declaresCallable(",
    ):
        assert context_operation in context

    # The reusable policy keeps only its immutable semantic environment. All
    # mutable lowering evidence is supplied by an operation-local context, so
    # two IRGen instances cannot share callback provenance through ambient state.
    private_state = [
        line.strip() for line in owner.splitlines() if line.startswith("    private ") and line.rstrip().endswith(";")
    ]
    assert private_state == ["private Analyzed analysis;"]
    assert "private Map<" not in owner
