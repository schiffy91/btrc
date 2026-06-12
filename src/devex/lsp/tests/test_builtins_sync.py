"""builtins.py is generated from the stdlib by gen_builtins.py; it must never
drift from what the generator produces (the generator is deterministic)."""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
GENERATOR = REPO_ROOT / "src" / "language" / "ast" / "gen_builtins.py"
CHECKED_IN = REPO_ROOT / "src" / "devex" / "lsp" / "builtins.py"


def test_checked_in_builtins_matches_generator_output(tmp_path):
    spec = importlib.util.spec_from_file_location("gen_builtins_check", GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    out = tmp_path / "builtins_generated.py"
    mod.OUTPUT = str(out)
    mod.main()

    assert out.read_text() == CHECKED_IN.read_text(), (
        "src/devex/lsp/builtins.py is stale — regenerate it with "
        "`make stubs-generate` (python3 src/language/ast/gen_builtins.py)"
    )
