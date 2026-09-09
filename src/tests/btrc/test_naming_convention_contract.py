"""btrc source spells the names it owns in camelCase.

The self-hosted compiler is written in btrc, whose convention is camelCase
members, parameters and locals over PascalCase types. The Python reference
compiler keeps Python's snake_case; neither language borrows the other's
spelling. The one exception is the hosted C ABI: `size_t` and its neighbours
are foreign names that must keep the spelling the C headers gave them, so
the hosted-ABI repository supplies the allowlist instead of a hand-written
one that would drift.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.compiler.python.abi.hosted import HostedAbiRepository
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.syntax.tokens import TokenKind

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"

_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def _foreign_names() -> frozenset[str]:
    """Every C name the hosted ABI lets btrc source spell verbatim."""

    abi = HostedAbiRepository()
    return frozenset(
        abi.function_names
        | abi.macros
        | abi.objects
        | abi.types
        | abi.typedefs
        | abi.owned_names
        | abi.native_names
        | abi.native_internal_names
        | abi.platform_function_names
        | abi.platform_macro_names
        | abi.platform_object_names
        | abi.platform_type_names
        | abi.platform_typedef_names
    )


_FSTRING = re.compile(r'f"(?:[^"\\\n]|\\.)*"')
_INTERPOLATION = re.compile(r"\{[^{}]*\}")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _interpolated_names(text: str) -> set[str]:
    """Identifiers an f-string interpolates.

    The lexer hands back one token for the whole f-string, so a field named
    inside {...} never appears as an IDENT even though the analyzer resolves
    it like any other member access.
    """

    names: set[str] = set()
    for literal in _FSTRING.findall(text):
        for span in _INTERPOLATION.findall(literal):
            names.update(_WORD.findall(span))
    return names


def test_self_hosted_compiler_owns_only_camel_case_names() -> None:
    """No btrc identifier we own may be spelled snake_case."""

    foreign = _foreign_names()
    offenders: dict[str, set[str]] = {}
    sources = sorted(SELFHOST.rglob("*.btrc"))
    assert sources, "no self-hosted compiler sources found"
    for source in sources:
        text = source.read_text()
        spelled = {
            token.value for token in Lexer(text, str(source)).tokenize() if token.type is TokenKind.IDENT
        } | _interpolated_names(text)
        for name in spelled:
            if not _SNAKE_CASE.match(name) or name in foreign:
                continue
            relative = str(source.relative_to(REPO))
            offenders.setdefault(relative, set()).add(name)

    assert not offenders, "btrc sources must spell owned names in camelCase: " + "; ".join(
        f"{path}: {', '.join(sorted(names))}" for path, names in sorted(offenders.items())
    )
