"""Every consumer that dispatches on a conditional expression knows the comma operator (C row 19).

``CommaExpr`` is C's comma operator, produced only as the root of a C-``for``
initializer or update (docs/design/c-compatibility.md, "Stage 16 r19"). btrc's
analyzer, validators and lowerers dispatch on ``kind`` and silently skip a kind
they do not know ("Kind coverage"), so every btrc file that names
``NK_TERNARY_EXPR`` -- the closest existing compound expression -- either
handles ``NK_COMMA_EXPR`` or is listed below with the reason a header root can
never reach it. The Python compiler's dataclass walkers descend into a new
constructor on their own; its explicit ``TernaryExpr`` sites follow the same
rule. A listed file that starts naming the comma must drop its entry.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BTRC = REPO / "src/compiler/btrc"
PYTHON = REPO / "src/compiler/python"

# A CommaExpr is a discarded header root: never a stored, returned, passed,
# folded or ownership-classified value, and never an operand of another
# expression. Files whose ternary sites only classify such values are exempt.
VALUE_ONLY = "classifies a stored, passed or returned value; a header comma is discarded"
BTRC_EXEMPT = {
    "analyzer/validation/Calls.btrc": "classifies a source-macro argument; a header comma is no argument",
    "analyzer/validation/Constants.btrc": "folds a constant expression; a header comma is never folded",
    "analyzer/validation/ControlFlow.btrc": "nullable flow narrows a ternary's branches and classifies stored values; a header comma is walked as plain children",
    "analyzer/validation/Ownership.btrc": VALUE_ONLY,
    "analyzer/validation/Storage.btrc": VALUE_ONLY,
    "analyzer/validation/Types.btrc": VALUE_ONLY,
    "ir/lowering/Callables.btrc": VALUE_ONLY,
    "ir/lowering/Concurrency.btrc": VALUE_ONLY,
    "ir/lowering/ownership/Operands.btrc": "orders an expression's operands; a header comma is no operand",
    "ir/lowering/ownership/Semantics.btrc": VALUE_ONLY,
}
PYTHON_EXEMPT = {
    "analyzer/aggregates.py": VALUE_ONLY,
    "analyzer/calls.py": "classifies a source-macro argument; a header comma is no argument",
    "analyzer/ownership.py": VALUE_ONLY,
    "analyzer/storage.py": VALUE_ONLY,
    "ir/lowering/calls.py": VALUE_ONLY,
    "ir/lowering/ownership.py": "classifies values and operands; a header comma is neither",
    "ir/lowering/statements.py": VALUE_ONLY,
}

_BTRC_TERNARY = re.compile(r"\bNK_TERNARY_EXPR\b")
_BTRC_COMMA = re.compile(r"\bNK_COMMA_EXPR\b")
_PYTHON_TERNARY = re.compile(r"(?<![\w.])(?:ast\.)?TernaryExpr\b")
_PYTHON_COMMA = re.compile(r"(?<![\w])(?:ast\.)?CommaExpr\b")

# The walkers a header comma must reach in btrcc, each naming the kind.
BTRC_REQUIRED = (
    "parser/Parser.btrc",
    "syntax/Identity.btrc",
    "analyzer/Expressions.btrc",
    "analyzer/Generics.btrc",
    "analyzer/GPU.btrc",
    "analyzer/Realtime.btrc",
    "analyzer/validation/Borrows.btrc",
    "analyzer/validation/Expressions.btrc",
    "ir/gpu/Wgsl.btrc",
    "ir/lowering/CallableFlow.btrc",
    "ir/lowering/Expressions.btrc",
)


def _files(root: Path, suffix: str, pattern: re.Pattern[str]) -> set[str]:
    found = set()
    for path in sorted(root.rglob(f"*{suffix}")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("generated/") or relative.endswith("/generated.py"):
            continue
        if pattern.search(path.read_text()):
            found.add(relative)
    return found


def test_every_btrc_ternary_site_handles_the_comma_or_is_exempt() -> None:
    ternary = _files(BTRC, ".btrc", _BTRC_TERNARY)
    comma = _files(BTRC, ".btrc", _BTRC_COMMA)
    assert sorted(ternary - comma - set(BTRC_EXEMPT)) == []
    assert sorted(set(BTRC_EXEMPT) & comma) == [], "an exempt file now names NK_COMMA_EXPR; drop its entry"
    assert sorted(set(BTRC_EXEMPT) - ternary) == [], "an exempt file no longer names NK_TERNARY_EXPR"


def test_every_python_ternary_site_handles_the_comma_or_is_exempt() -> None:
    ternary = _files(PYTHON, ".py", _PYTHON_TERNARY)
    comma = _files(PYTHON, ".py", _PYTHON_COMMA)
    assert sorted(ternary - comma - set(PYTHON_EXEMPT)) == []
    assert sorted(set(PYTHON_EXEMPT) & comma) == [], "an exempt module now names CommaExpr; drop its entry"
    assert sorted(set(PYTHON_EXEMPT) - ternary) == [], "an exempt module no longer names TernaryExpr"


def test_header_walkers_name_the_comma() -> None:
    comma = _files(BTRC, ".btrc", _BTRC_COMMA)
    assert sorted(set(BTRC_REQUIRED) - comma) == []
