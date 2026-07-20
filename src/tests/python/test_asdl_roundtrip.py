"""Round-trip guard for the generated AST node classes.

``src/compiler/python/ast_nodes.py`` is generated from
``src/language/ast.asdl`` by ``src/compiler/python/ast/asdl_python.py`` and must
never be hand-edited (see CLAUDE.md). This test re-runs the generator and
asserts that its output is byte-identical to the checked-in file, so any ASDL
or generator change that lands without a matching ``make ast-generate`` is
caught immediately.
"""

import subprocess
import sys
from pathlib import Path

# tests/ -> python/ -> compiler/ -> src/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_GENERATOR = _REPO_ROOT / "src" / "compiler" / "python" / "ast" / "asdl_python.py"
_BTRC_GENERATOR = _REPO_ROOT / "src" / "compiler" / "python" / "ast" / "gen_btrc_ast.py"
_ASDL = _REPO_ROOT / "src" / "language" / "ast.asdl"
_GENERATED = _REPO_ROOT / "src" / "compiler" / "python" / "ast_nodes.py"
_BTRC_GENERATED = _REPO_ROOT / "src" / "compiler" / "btrc" / "ast" / "node.btrc"


def _generate(generator: Path) -> str:
    return subprocess.run(
        [sys.executable, str(generator), str(_ASDL)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_ast_nodes_matches_fresh_generation():
    """The checked-in ast_nodes.py equals a fresh generator run, byte for byte."""
    fresh = _generate(_GENERATOR)
    checked_in = _GENERATED.read_text()
    assert fresh == checked_in, (
        "ast_nodes.py is out of sync with ast.asdl / asdl_python.py. "
        "Regenerate it with `make ast-generate` (do not hand-edit)."
    )


def test_btrc_ast_nodes_match_fresh_generation():
    fresh = _generate(_BTRC_GENERATOR)
    assert fresh == _BTRC_GENERATED.read_text(), (
        "btrc ast/node.btrc is out of sync with ast.asdl / gen_btrc_ast.py. "
        "Regenerate it with `make ast-generate-btrc` (do not hand-edit)."
    )


def test_ast_generators_are_deterministic():
    for generator in (_GENERATOR, _BTRC_GENERATOR):
        assert _generate(generator) == _generate(generator)
