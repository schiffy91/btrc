"""Every consumer of a string literal also handles adjacent literals (C row 5).

``StringConcat`` is a string constant exactly like ``StringLiteral``: it types
as ``string``, is a static initializer and a static address, stays unmanaged,
formats as ``%s`` and folds under ``sizeof``. btrc's analyzer and validators
dispatch on ``kind`` and silently skip a kind they do not know
(docs/design/c-compatibility.md, "Kind coverage"), so a site that tests for
``NK_STRING_LITERAL`` alone would quietly treat a concatenation as an unknown
expression. Each such site must ask ``StringConstant.isNode`` (or name
``NK_STRING_CONCAT``) instead; the Python compiler's predicates test
``STRING_CONSTANT_NODES``. The few sites that genuinely mean one literal token
are listed with the reason, and their file must handle the concatenation too.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BTRC = REPO / "src/compiler/btrc"
PYTHON = REPO / "src/compiler/python"

# File -> why a bare NK_STRING_LITERAL there means a single literal token.
BTRC_SINGLE_LITERAL_SITES = {
    "parser/Parser.btrc": "builds the literal and the pieces of a concatenation",
    "syntax/Identity.btrc": "renders each constructor canonically",
    "syntax/Literals.btrc": "StringConstant.isNode itself",
    "analyzer/SourceMacros.btrc": "decodes each literal piece of a concatenation",
    "analyzer/Realtime.btrc": "records one effect for a concatenation, then stops",
    "analyzer/validation/Names.btrc": "compares two literals' spellings; concatenations compare piecewise",
    "ir/lowering/Expressions.btrc": "emits one literal's spelling; lowerStringConcat joins the pieces",
}

# Module -> why a bare StringLiteral there means a single literal token.
PYTHON_SINGLE_LITERAL_SITES = {
    "parser/parser.py": "builds the literal and the pieces of a concatenation",
    "analyzer/program.py": "STRING_CONSTANT_NODES and the piece decoder",
    "analyzer/expressions.py": "a lone literal needs no piece resolution",
    "analyzer/gpu.py": "labels each kind; StringConcat has its own label",
    "analyzer/realtime.py": "records one effect for a concatenation, then stops",
    "ir/lowering/expressions.py": "emits one literal's spelling; the concatenation joins the pieces",
}

_BTRC_LITERAL = re.compile(r"\bNK_STRING_LITERAL\b")
_PYTHON_LITERAL = re.compile(r"(?<![\w.])(?:ast\.)?StringLiteral\b(?!\()")


def _sites(root: Path, pattern: re.Pattern[str], suffix: str) -> dict[str, list[str]]:
    sites: dict[str, list[str]] = {}
    for path in sorted(root.rglob(f"*{suffix}")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("generated/") or relative.endswith("/generated.py"):
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ", "#", "//", "/*", "*")) or stripped in {
                "StringLiteral,",
                "StringConcat,",
            }:
                continue
            if pattern.search(line):
                sites.setdefault(relative, []).append(f"{number}: {stripped}")
    return sites


def test_every_btrc_string_literal_site_handles_concatenation() -> None:
    unhandled = {
        relative: [line for line in lines if "NK_STRING_CONCAT" not in line and "StringConstant.isNode" not in line]
        for relative, lines in _sites(BTRC, _BTRC_LITERAL, ".btrc").items()
        if relative not in BTRC_SINGLE_LITERAL_SITES
    }
    assert {relative: lines for relative, lines in unhandled.items() if lines} == {}


def test_every_python_string_literal_site_handles_concatenation() -> None:
    unhandled = {
        relative: [line for line in lines if "StringConcat" not in line and "STRING_CONSTANT_NODES" not in line]
        for relative, lines in _sites(PYTHON, _PYTHON_LITERAL, ".py").items()
        if relative not in PYTHON_SINGLE_LITERAL_SITES
    }
    assert {relative: lines for relative, lines in unhandled.items() if lines} == {}


def test_single_literal_sites_handle_the_concatenation_beside_it() -> None:
    for relative in BTRC_SINGLE_LITERAL_SITES:
        text = (BTRC / relative).read_text()
        assert _BTRC_LITERAL.search(text), f"{relative} no longer names NK_STRING_LITERAL; drop its entry"
        assert "NK_STRING_CONCAT" in text or "StringConstant.isNode" in text, relative
    for relative in PYTHON_SINGLE_LITERAL_SITES:
        text = (PYTHON / relative).read_text()
        assert _PYTHON_LITERAL.search(text), f"{relative} no longer names StringLiteral; drop its entry"
        assert "StringConcat" in text or "STRING_CONSTANT_NODES" in text, relative
