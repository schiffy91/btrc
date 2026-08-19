"""Round-trip guards for the unified ASDL-derived AST catalog."""

from pathlib import Path
from pathlib import PurePosixPath

from tools.compiler_codegen.ast import AstCatalogGenerator

# tests/ -> python/ -> compiler/ -> src/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PYTHON_AST = PurePosixPath("src/compiler/python/syntax/ast/generated.py")
_BTRC_AST = PurePosixPath("src/compiler/btrc/generated/ast/node.btrc")


def _artifacts() -> dict[PurePosixPath, bytes]:
    return {
        artifact.path: artifact.content
        for artifact in AstCatalogGenerator(_REPO_ROOT).artifacts()
    }


def test_python_ast_matches_fresh_generation():
    """The checked-in Python AST equals the catalog artifact byte for byte."""

    assert _artifacts()[_PYTHON_AST] == (_REPO_ROOT / _PYTHON_AST).read_bytes(), (
        "syntax/ast/generated.py is out of sync with the unified AST catalog. "
        "Regenerate it with `make ast-generate` (do not hand-edit)."
    )


def test_btrc_ast_matches_fresh_generation():
    assert _artifacts()[_BTRC_AST] == (_REPO_ROOT / _BTRC_AST).read_bytes(), (
        "btrc generated/ast/node.btrc is out of sync with the unified AST catalog. "
        "Regenerate it with `make ast-generate-btrc` (do not hand-edit)."
    )


def test_ast_generators_are_deterministic():
    assert _artifacts() == _artifacts()
