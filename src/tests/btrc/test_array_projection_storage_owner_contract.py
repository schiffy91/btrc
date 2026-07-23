"""Ownership contract for self-hosted array projection storage semantics."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"
PYTHON_ANALYZER = REPO / "src/compiler/python/analyzer"


def test_array_projection_storage_has_one_stateful_domain_owner() -> None:
    storage = (SELFHOST / "semantic_validation_array_storage.btrc").read_text()
    borrows = (SELFHOST / "semantic_validation_opaque_borrows.btrc").read_text()

    owner = storage.split("class SemanticArrayProjectionStorage {", 1)[1]
    private_state = [
        line.strip()
        for line in owner.splitlines()
        if line.startswith("    private ") and line.rstrip().endswith(";")
    ]

    assert private_state == [
        "private SemanticValidationState state;",
        "private Map<string, Node> vars;",
    ]
    assert "private Node? representedType(" in owner
    assert "public bool embedsBacking(" in owner
    assert "SemanticArrayProjectionStorage(state, vars)" in borrows
    assert "semanticOpaqueProjectionEmbedsStorage(" not in borrows


def test_reference_frontend_delegates_projection_shape_to_array_owner() -> None:
    arrays = (PYTHON_ANALYZER / "array_contracts.py").read_text()
    borrows = (PYTHON_ANALYZER / "opaque_borrows.py").read_text()

    assert "class ArrayContractsMixin:" in arrays
    assert "def _array_projection_storage_type(" in arrays
    assert "self._array_field_value_type(member)" in arrays
    assert "self._array_projection_storage_type(expression)" in borrows
