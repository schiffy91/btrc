"""The checked-in LSP catalog must match the canonical compiler generator."""

from pathlib import Path

from tools.compiler_codegen.builtins import BuiltinCatalogGenerator

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKED_IN = REPO_ROOT / "src" / "devex" / "lsp" / "catalog" / "generated.py"


def test_checked_in_builtins_matches_generator_output():
    artifact = BuiltinCatalogGenerator(REPO_ROOT).artifacts()[0]

    assert REPO_ROOT.joinpath(*artifact.path.parts) == CHECKED_IN
    assert artifact.content == CHECKED_IN.read_bytes(), (
        "src/devex/lsp/catalog/generated.py is stale — regenerate it with `make compiler-codegen-generate`"
    )
