"""Round-trip guard for the generated AST node classes.

``src/compiler/python/ast_nodes.py`` is generated from
``src/language/ast/ast.asdl`` by ``src/language/ast/asdl_python.py`` and must
never be hand-edited (see CLAUDE.md). This test re-runs the generator and
asserts that its output is byte-identical to the checked-in file, so any ASDL
or generator change that lands without a matching ``make ast-generate`` is
caught immediately.
"""

import subprocess
import sys
from pathlib import Path

# tests/ -> python/ -> compiler/ -> src/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_GENERATOR = _REPO_ROOT / "src" / "language" / "ast" / "asdl_python.py"
_ASDL = _REPO_ROOT / "src" / "language" / "ast" / "ast.asdl"
_GENERATED = _REPO_ROOT / "src" / "compiler" / "python" / "ast_nodes.py"


def test_ast_nodes_matches_fresh_generation():
    """The checked-in ast_nodes.py equals a fresh generator run, byte for byte."""
    result = subprocess.run(
        [sys.executable, str(_GENERATOR), str(_ASDL)],
        capture_output=True,
        text=True,
        check=True,
    )
    fresh = result.stdout
    checked_in = _GENERATED.read_text()
    assert fresh == checked_in, (
        "ast_nodes.py is out of sync with ast.asdl / asdl_python.py. "
        "Regenerate it with `make ast-generate` (do not hand-edit)."
    )
