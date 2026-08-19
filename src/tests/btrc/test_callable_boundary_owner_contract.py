"""Ownership contracts for self-hosted callback ABI boundary policy."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def _source(relative: str) -> str:
    return (SELFHOST / relative).read_text()


def test_callable_boundary_behavior_has_one_domain_owner() -> None:
    callables = _source("ir/lowering/callables.btrc")
    lowerer = _source("ir/lowering/lowerer.btrc")
    stage = _source("ir/stage.btrc")

    assert "class CallableBoundaryContext {" in callables
    assert "class CallableValueSemantics {" in callables
    assert "class CallableBoundaryPolicy {" in callables
    assert "import ./lowering/callables.btrc;" in stage
    assert "import ./lowering/callable_flow.btrc;" in stage
    assert "CallableValueSemantics callableValues =" in lowerer
    assert "CallableBoundaryPolicy callableBoundaries =" in lowerer
    assert "CallableBoundaryPolicy(callableValues);" in lowerer

    for value_operation in (
        "public int expressionAbi(",
        "public bool lexicalIdentifier(",
        "public bool managedReturnCallable(",
        "public Node? canonicalType(",
        "public Node arrayElement(",
        "public Node? structDeclaration(",
        "public Vector<string> captureNames(",
    ):
        assert value_operation in callables
    for boundary_operation in (
        "public void rejectPersistentStorage(",
        "public void rejectAggregateInitializer(",
        "public void rejectAssignment(",
        "public void rejectUnsafeArguments(",
    ):
        assert boundary_operation in callables
    for duplicated_value_policy in (
        "private Node? canonicalType(",
        "private bool managedValueType(",
        "private Node arrayElement(",
        "private Node? structDeclaration(",
    ):
        policy = callables.split("class CallableBoundaryPolicy {", 1)[1]
        assert duplicated_value_policy not in policy

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


def test_callable_environment_classification_uses_registered_receiver_domains() -> None:
    analyzed = _source("analyzer/models.btrc")
    declarations = _source("analyzer/declarations.btrc")
    values = _source("ir/lowering/callables.btrc")

    assert "public Map<string, Node> interfaceTable;" in analyzed
    assert "public Node? interfaceMethod(" in analyzed
    assert "self.analyzed.interfaceTable.put(d.name, d);" in declarations
    assert "self.analysis.interfaceMethod(" in values
    assert "private bool builtinMethodRequiresEnvironment(" in values
    for exact_builtin in (
        'receiverType.base == "Thread"',
        'methodName == "join"',
        'receiverType.base == "Mutex"',
        'methodName == "get"',
        'methodName == "set"',
        'methodName == "destroy"',
        "SemanticTypeSystem.stringMethodResult(methodName) != null",
    ):
        assert exact_builtin in values


def test_callable_boundary_policy_is_per_lowerer_and_context_is_per_operation() -> None:
    callables = _source("ir/lowering/callables.btrc")
    flow = _source("ir/lowering/callable_flow.btrc")
    stage = _source("ir/stage.btrc")
    lowerer = _source("ir/lowering/lowerer.btrc")
    context = callables.split("class CallableBoundaryContext {", 1)[1].split(
        "class CallableValueSemantics {", 1
    )[0]
    owner = callables.split("class CallableBoundaryPolicy {", 1)[1].split(
        "class CallableLambdaPlan {", 1
    )[0]
    composition_state = lowerer.split("public IRLowerer(", 1)[0]

    assert lowerer.count("CallableValueSemantics callableValues =") == 1
    assert "CallableFlowState" not in lowerer
    assert lowerer.count("CallableBoundaryPolicy callableBoundaries =") == 1
    assert "private CallableValueSemantics" not in composition_state
    assert "private CallableFlowState" not in composition_state
    assert "private CallableBoundaryPolicy" not in composition_state
    assert "public CallableBoundaryContext boundaryContext(" in flow
    assert "self.ownedBindings," in flow
    assert "self.ambiguousBindings," in flow
    assert "self.declarations," in flow
    assert "self.environmentFunctions," in flow
    assert "self.environmentStorage);" in flow
    assert stage.index("import ./lowering/callables.btrc;") < stage.index(
        "import ./lowering/callable_flow.btrc;"
    )
    assert stage.index("import ./lowering/callable_flow.btrc;") < stage.index(
        "import ./lowering/lowerer.btrc;"
    )

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
        "public bool resolvesParameters()",
        "public Map<string, Node> parameterTypes()",
        "public bool hasVariable(",
        "public Node variableType(",
        "public int abiFor(",
        "public bool declaresCallable(",
    ):
        assert context_operation in context

    # The reusable policy keeps immutable classification only. Per-body facts
    # live on the explicitly constructed CallableFlowState.
    private_state = [
        line.strip() for line in owner.splitlines() if line.startswith("    private ") and line.rstrip().endswith(";")
    ]
    assert private_state == ["private CallableValueSemantics values;"]
    assert "private Map<" not in owner


def test_callable_flow_state_exclusively_owns_mutable_provenance() -> None:
    flow = _source("ir/lowering/callable_flow.btrc")
    lowerer = _source("ir/lowering/lowerer.btrc")

    for state in (
        "private Map<string, bool> ownedBindings;",
        "private Map<string, bool> ambiguousBindings;",
        "private Map<string, string> environmentFunctions;",
        "private Map<string, string> environmentStorage;",
        "private Vector<string> declarations;",
        "private Vector<int> scopeStarts;",
        "private Vector<CallableExceptionalCapture> exceptionCaptures;",
        "private Vector<CallableLoopCapture> loopCaptures;",
    ):
        assert state in flow

    for operation in (
        "public CallableFlowSnapshot snapshot()",
        "public void restore(CallableFlowSnapshot flow)",
        "public void join(Vector<CallableFlowSnapshot> flows)",
        "public CallableExceptionalCapture beginExceptionalCapture(",
        "public void recordExceptional()",
        "public CallableLoopCapture beginLoopCapture()",
        "public CallableSwitchCapture beginSwitchCapture(",
        "public void recordControlExit(",
        "public CallableFlowSnapshot beginScope()",
        "public void declare(string name)",
        "public void finishScope(CallableFlowSnapshot enclosing)",
    ):
        assert operation in flow

    for composition_root_state in (
        "ownedCallableBindings",
        "ambiguousCallableBindings",
        "callableScopeDeclarations",
        "callableScopeStarts",
        "callableExceptionCaptures",
        "callableLoopCaptures",
    ):
        assert composition_root_state not in lowerer


def test_callable_flow_is_per_function_and_reentrant() -> None:
    flow = _source("ir/lowering/callable_flow.btrc")
    functions = _source("ir/lowering/functions.btrc")

    assert "public CallableFlowState() {" in flow
    assert "class CallableEvaluationPlan {" not in flow
    assert "class CallableFlowStateSnapshot {" not in flow
    assert "isolateInto(" not in flow
    assert "restoreIsolated(" not in flow
    assert "CallableFlowState" not in functions.split("class FunctionLowerer {", 1)[0]
    assert functions.count(
        "CallableFlowState callableFlow = CallableFlowState();"
    ) == 2
    assert "self.callableFlow" not in functions

    owner = flow.split("class CallableFlowState {", 1)[1]
    assert not any(line.startswith(("Map<", "Vector<", "CallableFlow")) for line in owner.splitlines())
