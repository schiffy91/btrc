"""Per-file compilation units for the btrc LSP.

Every file is lexed and parsed in its own coordinate space — in native editor
coordinates, with no preprocessing — so token and AST positions match the
editor exactly. ``import`` is a real keyword now, so each file's ImportDecl
nodes carry true line/col and are read directly. Caching and composition live
in workspace.py.

Name positions are no longer reconstructed here: every named decl/member
carries its own ``name_line``/``name_col`` (populated by the parser), read
directly by the definition and symbol providers. The old token-rescan
side-table has been retired.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field

from src.compiler.python.ast_nodes import ImportDecl
from src.compiler.python.cache_keys import toolchain_hash
from src.compiler.python.frontend import _defined_stdlib_names
from src.compiler.python.lexer import Lexer, LexerError
from src.compiler.python.parser.core import ParseError
from src.compiler.python.parser.parser import Parser
from src.compiler.python.tokens import Token, TokenType


def _compute_unit_cache_version() -> str:
    """Content hash of every source that shapes a serialized ``FileUnit``.

    Derived (not hand-bumped) so stale cached units are impossible: any edit
    to the grammar, the ASDL/AST, the lexer, the token definitions, or the
    parser changes the hash and orphans old entries. LSP unit extraction and
    the JSON codec are included in addition to the compiler frontend hash.
    """
    digest = hashlib.sha256(toolchain_hash("frontend").encode())
    lsp_dir = os.path.dirname(__file__)
    for name in ("unit_cache.py", "units.py"):
        encoded_name = name.encode()
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        try:
            with open(os.path.join(lsp_dir, name), "rb") as source_file:
                content = source_file.read()
        except OSError:
            content = b"<missing>"
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()[:16]


_UNIT_CACHE_VERSION = _compute_unit_cache_version()


@dataclass
class FileUnit:
    """One file's lex/parse output, positions native to that file."""

    path: str  # absolute path
    source: str
    content_hash: str
    tokens: list[Token] = field(default_factory=list)
    decls: list = field(default_factory=list)
    # (1-based line, import_spec node) — read from this file's ImportDecl nodes.
    import_specs: list[tuple[int, object]] = field(default_factory=list)
    defined_names: frozenset[str] = frozenset()
    lex_error: LexerError | None = None
    parse_error: ParseError | None = None
    # Lazy line -> tokens index (built by unit_line_index, excluded from
    # equality so cached units compare by content).
    _line_index: dict[int, list[Token]] | None = field(default=None, repr=False, compare=False)

    @property
    def error(self) -> Exception | None:
        return self.lex_error or self.parse_error


def _collect_import_specs(decls: list) -> list[tuple[int, object]]:
    """Read ``(line, spec)`` from this file's ImportDecl nodes.

    ``#include "X.btrc"`` is the deprecated alias for a relative import: it
    parses as a PreprocessorDirective, so it is rewritten here to a RelativePath
    spec, while ``#include <...>`` / ``#include "....h"`` stay real C includes.
    """
    from src.compiler.python.ast_nodes import PreprocessorDirective, RelativePath
    from src.compiler.python.import_scan import CINCLUDE_BTRC_RE

    specs: list[tuple[int, object]] = []
    for decl in decls:
        if isinstance(decl, ImportDecl):
            specs.append((decl.line, decl.spec))
        elif isinstance(decl, PreprocessorDirective):
            m = CINCLUDE_BTRC_RE.match(decl.text)
            if m:
                specs.append((decl.line, RelativePath(path=m.group(1))))
    return specs


def parse_unit(path: str, source: str) -> FileUnit:
    """Lex and parse one file in its own coordinate space (no preprocessing)."""
    content_hash = hashlib.sha256(source.encode()).hexdigest()
    unit = FileUnit(
        path=os.path.abspath(path),
        source=source,
        content_hash=content_hash,
        defined_names=frozenset(_defined_stdlib_names(source)),
    )
    try:
        unit.tokens = Lexer(source, os.path.basename(path)).tokenize()
    except LexerError as e:
        unit.lex_error = e
        return unit
    try:
        program = Parser(unit.tokens).parse()
    except ParseError as e:
        unit.parse_error = e
        return unit
    unit.decls = program.declarations
    unit.import_specs = _collect_import_specs(unit.decls)
    for decl in unit.decls:
        decl.source_file = unit.path
    return unit


def line_token_index(tokens: list[Token]) -> dict[int, list[Token]]:
    """Index tokens by 1-based line for O(1) position lookup."""
    index: dict[int, list[Token]] = {}
    for tok in tokens:
        if tok.type == TokenType.EOF:
            continue
        index.setdefault(tok.line, []).append(tok)
    return index


def unit_line_index(unit: FileUnit) -> dict[int, list[Token]]:
    """Per-unit cached line -> tokens index (units are cached across runs)."""
    if unit._line_index is None:
        unit._line_index = line_token_index(unit.tokens)
    return unit._line_index
