"""Context and behavior contracts for self-host expression-type memoization."""

from pathlib import Path

from src.tests.btrc.test_semantic_validation import _compile_source, _strict_build_and_run

REPO = Path(__file__).resolve().parents[3]
ANALYZER = REPO / "src/compiler/btrc/analyzer/expressions.btrc"
MEMO = ANALYZER
GPU_SEMANTICS = REPO / "src/compiler/btrc/analyzer/gpu.btrc"
LOWERING = REPO / "src/compiler/btrc/ir/lowering"
LOWERER = LOWERING / "lowerer.btrc"
FUNCTIONS = LOWERING / "functions.btrc"
DECLARATIONS = LOWERING / "declarations.btrc"
EXPRESSIONS = LOWERING / "expressions.btrc"
GPU_PIPELINE = REPO / "src/compiler/btrc/ir/gpu/pipeline.btrc"
OWNERSHIP_OPERAND_PLANNER = (
    LOWERING / "ownership/operands.btrc"
)


def _function(source: str, signature: str, next_signature: str) -> str:
    start = source.index(signature)
    end = source.index(next_signature, start)
    return source[start:end]


def test_cache_is_epoch_scoped_and_bypasses_mutable_contexts() -> None:
    lowerer = LOWERER.read_text()
    functions = FUNCTIONS.read_text()
    declarations = DECLARATIONS.read_text()
    expressions = EXPRESSIONS.read_text()
    memo_source = MEMO.read_text()
    reset = _function(
        functions,
        "public void resetExpressionInferenceMemo()",
        "public void resetFuncVarDecls()",
    )
    owned_resolver = _function(
        OWNERSHIP_OPERAND_PLANNER.read_text(),
        "public Node? expressionType(",
        "public bool hasEffect(",
    )
    generic = _function(
        declarations,
        "public void emitGenericInstance(",
        "public void emitClassDecl(",
    )
    method_generic = _function(
        functions,
        "public void emitOneMethodGenericInstance(",
        "public Map<string, Node> genericMethodVarTypes(",
    )
    isolated = _function(
        functions,
        "public ScopeSnapshot enterIsolatedScope(",
        "public void emitOneMethodGenericInstance(",
    )
    uncached = _function(
        memo_source,
        "private Node? inferSpecializationTypeWithoutMemo(",
        "private Node lambdaVoidType()",
    )
    lower = lowerer[lowerer.index("public IRModule lower(") :]
    gpu_fallback = _function(
        functions,
        "public void emitGpuCpuFallback(",
        "public IRFunction lowerFunction(",
    )
    gpu_pipeline = GPU_PIPELINE.read_text()
    gpu_return = _function(
        gpu_pipeline,
        "public GpuStatementResult materializeStatement(",
        "public IRNode dispatchExpression(",
    )
    gpu_types = GPU_SEMANTICS.read_text()
    gpu_context = gpu_types[gpu_types.index("public Node? contextualExprType(") :]

    assert "self.expressionTypes.beginMemo()" in reset
    assert "if (environment.usesGpuInference())" in owned_resolver
    assert "self.gpu.contextualExprType(" in owned_resolver
    assert "if (environment.usesDefaultInference())" in owned_resolver
    assert "self.expressionTypes.inferSpecializationWithoutMemo(" in owned_resolver
    assert "resetExpressionInferenceMemo();" in generic
    assert "resetExpressionInferenceMemo();" in method_generic
    assert isolated.count("resetExpressionInferenceMemo();") == 2
    assert "self.memoEnabled = false" in uncached
    assert "self.memoEnabled = enabled" in uncached
    assert lower.index("self.expressionTypes.disableMemo()") < lower.index(
        "self.gpuPipeline.registerKernels(program, module)"
    )
    assert lower.rindex("self.expressionTypes.disableMemo()") > lower.index(
        "self.cleanupSlots.finalize(module)"
    )
    assert gpu_fallback.index("self.resetFuncVarDecls();") < gpu_fallback.index(
        "self.lowerBody("
    )
    assert "contextualExprTypeUnmemoized(" in gpu_context
    assert "self.expressions.inferSpecializationWithoutMemo(" in gpu_types
    assert "expressionInferenceMemo" not in gpu_types
    assert "self.semantics.contextualExprType(" in gpu_return
    assert "inferType(" not in gpu_return
    assert "class GpuStatementPlan {" in gpu_pipeline
    assert "public GpuStatementPlan planStatement(" in gpu_pipeline
    assert "tryLowerGpuCpuReturn(" not in expressions


def test_recursive_inference_memo_has_one_miss_per_ast_node() -> None:
    analyzer = ANALYZER.read_text()
    memo = MEMO.read_text()
    raw = _function(
        analyzer,
        "private Node? inferTypeRaw(",
        "private Node? inferType(",
    )
    cached = _function(
        memo,
        "private Node? inferSpecializationType(",
        "private Node? inferSpecializationTypeWithoutMemo(",
    )

    # Every recursive child query re-enters the memoized public seam. Once a
    # node is known, the uncached recursive walk is skipped entirely.
    assert raw.count("inferSpecializationType(") >= 10
    assert "inferSpecializationTypeUnmemoized(" not in raw
    assert cached.index("self.memoKnown.has(key)") < cached.index(
        "Node? result = self.inferSpecializationTypeUnmemoized("
    )
    assert "self.memoKnown.put(key, true)" in cached
    assert "self.memoValues.put(key, result)" in cached


def test_shared_generic_ast_is_reinferred_for_each_type_mapping(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <string.h>
        class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public T echo(T value) { return value; }
        }
        int main() {
            Box<int> numbers = Box(0);
            Box<string> words = Box("seed");
            int number = numbers.echo(42);
            string word = words.echo("mapped");
            return number == 42 && strcmp(word, "mapped") == 0 ? 0 : 1;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)

    assert result.returncode == 0, result.stderr
    _strict_build_and_run(generated, tmp_path / "generic-cache-epochs")
