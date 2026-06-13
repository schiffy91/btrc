"""Per-file compilation units for the btrc LSP.

Every file is lexed and parsed in its own coordinate space — import lines are
blanked (not stripped) so token and AST positions match the editor exactly.
Caching and composition live in workspace.py.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field

from src.compiler.python.cache_keys import toolchain_hash
from src.compiler.python.frontend import (
    _BTRC_IMPORT_RE,
    _BTRC_INCLUDE_RE,
    _defined_stdlib_names,
)
from src.compiler.python.lexer import Lexer, LexerError
from src.compiler.python.parser.core import ParseError
from src.compiler.python.parser.parser import Parser
from src.compiler.python.tokens import Token, TokenType


def _compute_unit_cache_version() -> str:
    """Content hash of every compiler source that shapes a FileUnit pickle.

    Derived (not hand-bumped) so stale cached units are impossible: any edit
    to the grammar, the ASDL/AST, the lexer, the token definitions, or the
    parser changes the hash and orphans old pickles. Shared with the
    compiler's own caches (see cache_keys.toolchain_hash)."""
    return toolchain_hash("frontend")


_UNIT_CACHE_VERSION = _compute_unit_cache_version()


@dataclass
class FileUnit:
    """One file's lex/parse output, positions native to that file."""

    path: str  # absolute path
    source: str
    content_hash: str
    tokens: list[Token] = field(default_factory=list)
    decls: list = field(default_factory=list)
    name_positions: list[tuple[int, int]] = field(default_factory=list)  # parallel to decls
    # Parallel to decls; for ClassDecl entries, parallel to its members.
    member_name_positions: list[list[tuple[int, int]]] = field(default_factory=list)
    import_specs: list[tuple[int, str]] = field(default_factory=list)  # (1-based line, spec)
    defined_names: frozenset[str] = frozenset()
    lex_error: LexerError | None = None
    parse_error: ParseError | None = None
    # Lazy line -> tokens index (built by unit_line_index, excluded from
    # equality so cached units compare by content).
    _line_index: dict[int, list[Token]] | None = field(default=None, repr=False, compare=False)

    @property
    def error(self) -> Exception | None:
        return self.lex_error or self.parse_error


def _blank_import_lines(source: str) -> tuple[str, list[tuple[int, str]]]:
    """Replace import/include lines with blanks, preserving line numbers."""
    out_lines: list[str] = []
    specs: list[tuple[int, str]] = []
    for line_number, line in enumerate(source.split("\n"), start=1):
        m = _BTRC_IMPORT_RE.match(line)
        if m:
            specs.append((line_number, m.group(1)))
            out_lines.append("")
            continue
        m = _BTRC_INCLUDE_RE.match(line)
        if m:
            specs.append((line_number, m.group(1)))
            out_lines.append("")
            continue
        out_lines.append(line)
    return "\n".join(out_lines), specs


def _decl_name(decl) -> str | None:
    return getattr(decl, "name", None) or getattr(decl, "alias", None)


def _compute_name_positions(
    decls: list, tokens: list[Token]
) -> tuple[list[tuple[int, int]], list[list[tuple[int, int]]]]:
    """Position of each decl's (and class member's) *name* token.

    Editors expect go-to-definition to land on the name, not the leading
    keyword/type the node records. One forward token walk covers everything
    because decls and members appear in source order.
    """
    positions: list[tuple[int, int]] = []
    member_positions: list[list[tuple[int, int]]] = []
    n = len(tokens)
    state = {"ptr": 0}

    def name_pos(node) -> tuple[int, int]:
        line = getattr(node, "line", 0)
        col = getattr(node, "col", 0)
        name = _decl_name(node)
        if not name:
            return (line, col)
        ptr = state["ptr"]
        while ptr < n and (tokens[ptr].line, tokens[ptr].col) < (line, col):
            ptr += 1
        state["ptr"] = ptr
        scan = ptr
        while scan < n:
            if tokens[scan].value == name:
                return (tokens[scan].line, tokens[scan].col)
            scan += 1
        return (line, col)

    for decl in decls:
        positions.append(name_pos(decl))
        members = getattr(decl, "members", None)
        if members:
            member_positions.append([name_pos(m) for m in members])
        else:
            member_positions.append([])
    return positions, member_positions


def parse_unit(path: str, source: str) -> FileUnit:
    """Lex and parse one file in its own coordinate space."""
    clean, specs = _blank_import_lines(source)
    content_hash = hashlib.sha256(source.encode()).hexdigest()
    unit = FileUnit(
        path=os.path.abspath(path),
        source=source,
        content_hash=content_hash,
        import_specs=specs,
        defined_names=frozenset(_defined_stdlib_names(source)),
    )
    try:
        unit.tokens = Lexer(clean, os.path.basename(path)).tokenize()
    except LexerError as e:
        unit.lex_error = e
        return unit
    try:
        program = Parser(unit.tokens).parse()
    except ParseError as e:
        unit.parse_error = e
        return unit
    unit.decls = program.declarations
    for decl in unit.decls:
        decl.source_file = unit.path
    unit.name_positions, unit.member_name_positions = _compute_name_positions(
        unit.decls, unit.tokens
    )
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
