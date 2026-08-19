"""Phase 3 polish fixes surfaced by adversarial verification.

1. Deeply nested expressions must yield a clean diagnostic, never a raw
   Python RecursionError traceback (the CLI only caught Lexer/ParseError).
2. C-style for-loop init declarations must carry name_line/name_col on the
   variable's NAME token (the C-for branch forgot to populate them).
"""

import subprocess
import sys
from pathlib import Path

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser

REPO = Path(__file__).resolve().parents[3]


def _compile(tmp_path, source):
    src = tmp_path / "t.btrc"
    src.write_text(source)
    return subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(src), "-o", str(tmp_path / "t.c")],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={"BTRC_CACHE_DIR": str(tmp_path / "cache"), "PATH": "/usr/bin:/bin"},
    )


def test_moderate_nesting_compiles(tmp_path):
    # ~58 parens used to overflow the parser's recursion; now within budget.
    src = "int main() { int x = " + "(" * 58 + "1" + ")" * 58 + "; return 0; }\n"
    r = _compile(tmp_path, src)
    assert r.returncode == 0, r.stderr


def test_pathological_nesting_is_clean_error(tmp_path):
    # Absurd nesting still exceeds the lifted limit, but must be a clean
    # diagnostic with no Python traceback.
    src = "int main() { int x = " + "(" * 8000 + "1" + ")" * 8000 + "; return 0; }\n"
    r = _compile(tmp_path, src)
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
    assert "RecursionError" not in r.stderr
    assert "nested too deeply" in r.stderr


def _var_decls(node, out):
    import dataclasses

    if type(node).__name__ == "VarDeclStmt":
        out.append(node)
    if dataclasses.is_dataclass(node):
        for fld in dataclasses.fields(node):
            v = getattr(node, fld.name)
            for x in v if isinstance(v, list) else [v]:
                if dataclasses.is_dataclass(x):
                    _var_decls(x, out)


def test_cfor_loop_var_has_name_span():
    src = (
        "void f() {\n"
        "    for (int idx = 0; idx < 3; idx = idx + 1) { }\n"
        "    for (var jx = 0; jx < 3; jx = jx + 1) { }\n"
        "}\n"
    )
    prog = Parser(Lexer(src, "t.btrc").tokenize()).parse()
    lines = src.split("\n")
    decls = []
    for d in prog.declarations:
        _var_decls(d, decls)
    by_name = {d.name: d for d in decls}
    for name in ("idx", "jx"):
        d = by_name[name]
        assert d.name_line > 0 and d.name_col > 0, f"{name} span unpopulated"
        landed = lines[d.name_line - 1][d.name_col - 1 : d.name_col - 1 + len(name)]
        assert landed == name, f"{name} span landed on {landed!r}"
