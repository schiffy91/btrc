"""Ownership contract for self-hosted array projection storage semantics."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"
PYTHON_ANALYZER = REPO / "src/compiler/python/analyzer"


def test_array_projection_storage_has_one_stateful_domain_owner() -> None:
    storage = (SELFHOST / "analyzer/validation/storage.btrc").read_text()
    borrows = (SELFHOST / "analyzer/validation/borrows.btrc").read_text()

    owner = storage.split("class StorageValidator {", 1)[1]
    private_state = [
        line.strip()
        for line in owner.splitlines()
        if line.strip().startswith("private ") and line.rstrip().endswith(";")
    ]

    assert private_state == [
        "private SemanticValidationState state;",
        "private OperatorSemantics operators;",
        "private TypeValidator types;",
        "private ConstantValidator constants;",
    ]
    assert "private Node? arrayProjectionRepresentedType(" in owner
    assert "public bool arrayProjectionEmbedsBacking(" in owner
    assert "self.storage.arrayProjectionEmbedsBacking(" in borrows
    assert "semanticOpaqueProjectionEmbedsStorage(" not in borrows


def test_reference_frontend_delegates_projection_shape_to_array_owner() -> None:
    aggregates = (PYTHON_ANALYZER / "aggregates.py").read_text()
    storage = (PYTHON_ANALYZER / "storage.py").read_text()
    ownership = (PYTHON_ANALYZER / "ownership.py").read_text()

    assert "class AggregateAnalyzer:" in aggregates
    assert "def array_projection_storage_type(" in aggregates
    assert "self.array_field_value_type(member)" in aggregates
    assert "class StorageModel:" in storage
    assert "def projection_embeds_storage(" in storage
    assert "self.aggregates.array_projection_storage_type(expression)" in storage
    assert "return self.storage.projection_embeds_storage(expression)" in ownership
