"""Context and behavior contracts for self-host expression-type memoization."""

from pathlib import Path

from src.tests.btrc.test_semantic_validation import _compile_source, _strict_build_and_run

REPO = Path(__file__).resolve().parents[3]
IRGEN = REPO / "src/compiler/btrc/irgen.btrc"
ANALYZER = REPO / "src/compiler/btrc/analyzer.btrc"
MEMO = REPO / "src/compiler/btrc/expression_inference_memo.btrc"
GPU_NUMERIC = REPO / "src/compiler/btrc/gpu_numeric.btrc"


def _function(source: str, signature: str, next_signature: str) -> str:
    start = source.index(signature)
    end = source.index(next_signature, start)
    return source[start:end]


def test_cache_is_epoch_scoped_and_bypasses_mutable_contexts() -> None:
    source = IRGEN.read_text()
    memo_source = MEMO.read_text()
    reset = _function(
        source,
        "public void resetExpressionInferenceMemo()",
        "public void resetFuncVarDecls()",
    )
    resolver = _function(
        source,
        "public Node? resolvedExpressionType(",
        "public void typedOperatorFail(",
    )
    generic = _function(
        source,
        "public void emitGenericInstance(",
        "public void emitMethodGenericInstances(",
    )
    method_generic = _function(
        source,
        "public void emitOneMethodGenericInstance(",
        "public Map<string, Node> genericMethodVarTypes(",
    )
    isolated = _function(
        source,
        "public ScopeSnapshot enterIsolatedScope(",
        "public void maybeRegisterCleanup(",
    )
    uncached = _function(
        memo_source,
        "Node? inferSpecializationTypeWithoutMemo(",
        "\n}",
    )
    generate = _function(
        source,
        "public IRModule generate(",
        "public void emitFunctionPointerTypedefs(",
    )
    gpu_lowering = (REPO / "src/compiler/btrc/gpu_lowering.btrc").read_text()
    gpu_fallback = gpu_lowering[gpu_lowering.index("void emitGpuCpuFallback(") :]
    gpu_return = _function(
        gpu_lowering,
        "bool tryLowerGpuCpuReturn(",
        "IRNode? lowerGpuCpuBuiltin(",
    )
    gpu_context = _function(
        GPU_NUMERIC.read_text(),
        "Node? gpuContextualExprType(",
        "void gpuValidateFloatLiteral(",
    )

    assert "beginExpressionInferenceMemo(self.analyzed)" in reset
    assert "if (self.gpuCpu.active)" in resolver
    assert "if (self.callDefaultTypeDepth > 0)" in resolver
    assert "inferSpecializationTypeWithoutMemo(" in resolver
    assert "resetExpressionInferenceMemo();" in generic
    assert "resetExpressionInferenceMemo();" in method_generic
    assert isolated.count("resetExpressionInferenceMemo();") == 2
    assert "expressionInferenceMemoEnabled = false" in uncached
    assert "expressionInferenceMemoEnabled = enabled" in uncached
    assert generate.index("disableExpressionInferenceMemo(self.analyzed)") < generate.index(
        "registerGpuKernels(self, prog, m)"
    )
    assert generate.rindex("disableExpressionInferenceMemo(self.analyzed)") > generate.index("self.collectHelpers(m)")
    assert gpu_fallback.index("gen.resetFuncVarDecls();") < gpu_fallback.index(
        "gen.lowerBlock(declaration.body_node, varTypes)"
    )
    assert "expressionInferenceMemoEnabled = false" in gpu_context
    assert "expressionInferenceMemoEnabled = memoEnabled" in gpu_context
    assert "gpuContextualExprTypeUnmemoized(" in gpu_context
    assert "gpuContextualExprType(" in gpu_return
    assert "inferType(" not in gpu_return


def test_recursive_inference_memo_has_one_miss_per_ast_node() -> None:
    analyzer = ANALYZER.read_text()
    memo = MEMO.read_text()
    raw = _function(
        analyzer,
        "Node? inferTypeRaw(",
        "Node? inferType(",
    )
    cached = _function(
        memo,
        "Node? inferSpecializationType(",
        "Node? inferSpecializationTypeWithoutMemo(",
    )

    # Every recursive child query re-enters the memoized public seam. Once a
    # node is known, the uncached recursive walk is skipped entirely.
    assert raw.count("inferSpecializationType(") >= 10
    assert "inferSpecializationTypeUnmemoized(" not in raw
    assert cached.index("expressionInferenceMemoKnown.has(key)") < cached.index(
        "Node? result = inferSpecializationTypeUnmemoized("
    )
    assert "expressionInferenceMemoKnown.put(key, true)" in cached
    assert "expressionInferenceMemoValues.put(key, result)" in cached


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
