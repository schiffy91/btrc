"""Exact-name and complexity contracts for self-hosted IR reachability."""

import re
from pathlib import Path

from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def test_structured_reachability_uses_exact_map_membership() -> None:
    optimizer = (SELFHOST / "ir/optimization/optimizer.btrc").read_text().expandtabs(4)
    start = optimizer.index("private void collectFuncRefs(")
    end = optimizer.index("\n    }\n\n    private void eliminateDeadFunctions", start)
    collector = optimizer[start:end]
    global_start = optimizer.index("private void collectGlobalRefs(")
    global_end = optimizer.index(
        "\n    }\n\n    private void enqueueGlobalFunctionRefs",
        global_start,
    )
    global_collector = optimizer[global_start:global_end]
    parameter_start = optimizer.index("private void collectParameterUses(")
    parameter_end = optimizer.index(
        "\n    }\n\n    private void normalizeUnusedParameters",
        parameter_start,
    )
    parameter_collector = optimizer[parameter_start:parameter_end]

    assert "names.has(node.callee)" in collector
    assert "names.has(node.name)" in collector
    assert "scanTextForNames" not in collector
    assert "names.has(node.callee)" in global_collector
    assert "names.has(node.name)" in global_collector
    assert "scanTextForNames" not in global_collector
    assert "names.has(node.name)" in parameter_collector
    assert "scanTextForNames" not in parameter_collector


def test_exact_function_references_survive_without_rooting_substrings(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int exact_target() { return 41; }
        int exact_target_suffix() { return exact_target() + 1; }
        int exact_target_suffix_unused() { return 99; }
        int main() { return exact_target_suffix() == 42 ? 0 : 1; }
    """
    result, generated = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert re.search(r"\bint exact_target\s*\(", emitted)
    assert re.search(r"\bint exact_target_suffix\s*\(", emitted)
    assert not re.search(
        r"\bint exact_target_suffix_unused\s*\(",
        emitted,
    )
    _strict_build_and_run(generated, tmp_path / "exact-reachability")
