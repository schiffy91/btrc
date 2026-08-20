"""Correctness and complexity contracts for self-hosted member lookup."""

from pathlib import Path

from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def _function(source: str, signature: str) -> str:
    start = source.index(signature)
    end = source.index("\n    }", start)
    return source[start:end]


def test_member_queries_use_complete_constant_time_indexes() -> None:
    analyzer = (SELFHOST / "analyzer/models.btrc").read_text()
    index = (SELFHOST / "analyzer/declarations.btrc").read_text()
    types = (SELFHOST / "analyzer/types.btrc").read_text()
    analyzer_stage = (SELFHOST / "analyzer/stage.btrc").read_text()

    for signature in (
        "    public Node? classMember(",
        "    public Node? classMethod(",
        "    public Node? classConstructor(",
        "    public Node? genericClassMethod(",
        "    public Node? genericClassConstructor(",
    ):
        query = _function(analyzer, signature)
        assert ".members" not in query
        assert "while (" not in query
        assert "Index.has(" in query

    generic_query = _function(types, "    class Node? genericMember(")
    assert ".members" not in generic_query
    assert "while (" not in generic_query
    assert "Analyzed.memberKey(" in generic_query
    assert "genericMemberIndex.has(" in generic_query

    registration_end = index.index("/* Canonical physical storage")
    assert index.index("self.indexAnalyzedMembers(self.analyzed);") < registration_end
    assert "analyzed.memberIndexReady = true;" in index
    assert "import ./models.btrc;" in analyzer_stage
    assert "import ./types.btrc;" in analyzer_stage
    assert "import ./declarations.btrc;" in analyzer_stage
    assert "#include" not in analyzer_stage


def test_indexed_method_namespace_ignores_child_value_member(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Base {
            public int action() { return 42; }
        }
        class Child extends Base {
            public int action;
            public Child() { self.action = 0; }
        }
        int main() {
            Child value = new Child();
            int result = value.action();
            delete value;
            return result == 42 ? 0 : 1;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    _strict_build_and_run(generated, tmp_path / "indexed-member-namespace")
