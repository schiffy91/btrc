"""Correctness and complexity contracts for self-hosted type reachability."""

from pathlib import Path

from src.tests.btrc.test_semantic_validation import _compile_source

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def test_type_reachability_scans_each_type_field_once() -> None:
    source = (SELFHOST / "ir/optimization/optimizer.btrc").read_text()
    scanner_start = source.index("private void scanTextForKnownNames(")
    scanner_end = source.index("\n    }\n", scanner_start)
    scanner = source[scanner_start:scanner_end]
    collector_start = source.index("private void collectStructRefsNode(")
    collector_end = source.index(
        "\n    }\n\n    private void eliminateDeadStructs", collector_start
    )
    collector = source[collector_start:collector_end]

    assert "while (index < length)" in scanner
    assert "names.has(identifier)" in scanner
    assert "names.keys()" not in scanner
    assert "scanTextForKnownNames(node.c_type" in collector
    assert "scanTextForKnownNames(node.target_type" in collector
    assert "scanTextForNames" not in collector
    assert "node.text" not in collector
    assert "node.callee" not in collector


def test_literal_type_name_does_not_root_an_unreferenced_struct(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        struct DeadType { int value; };
        int main() {
            return "DeadType"[0] == 'D' ? 0 : 1;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)

    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert "typedef struct DeadType" not in emitted
    assert "struct DeadType {" not in emitted
