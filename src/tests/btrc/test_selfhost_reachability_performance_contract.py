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
    generator = (SELFHOST / "irgen.btrc").read_text()
    globals_source = (SELFHOST / "global_reachability.btrc").read_text()
    parameters_source = (SELFHOST / "parameter_usage.btrc").read_text()
    start = generator.index("void collectFuncRefs(")
    end = generator.index("\n}\n\nvoid eliminateDeadFunctions", start)
    collector = generator[start:end]
    global_start = globals_source.index("void collectGlobalRefs(")
    global_end = globals_source.index(
        "\n}\n\nvoid enqueueGlobalFunctionRefs",
        global_start,
    )
    global_collector = globals_source[global_start:global_end]
    parameter_start = parameters_source.index("void collectParameterUses(")
    parameter_end = parameters_source.index(
        "\n}\n\nvoid consumeUnusedParameters",
        parameter_start,
    )
    parameter_collector = parameters_source[parameter_start:parameter_end]

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
