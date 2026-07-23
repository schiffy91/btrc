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
from collections.abc import Iterator
from dataclasses import dataclass, field

from src.compiler.python.artifacts.cache.compiler_cache import ToolchainFingerprint
from src.compiler.python.ast_nodes import (
    ImportDecl,
    PreprocessorDirective,
    RelativePath,
    import_spec,
)
from src.compiler.python.frontend.dependencies import SourceDependencyKind
from src.compiler.python.frontend.stdlib import StdlibRepository
from src.compiler.python.import_scan import CINCLUDE_BTRC_RE
from src.compiler.python.lexer import Lexer, LexerError
from src.compiler.python.parser.core import ParseError
from src.compiler.python.parser.parser import Parser
from src.compiler.python.tokens import Token, TokenType


class FileUnitCacheSchema:
    """Own the derived identity of serialized per-file parse results."""

    _SOURCE_FILES = ("unit_cache.py", "units.py")

    def __init__(
        self,
        fingerprint: ToolchainFingerprint | None = None,
        *,
        source_directory: str | None = None,
    ) -> None:
        self._fingerprint = fingerprint or ToolchainFingerprint()
        self._source_directory = source_directory or os.path.dirname(__file__)

    def current_version(self) -> str:
        """Hash every source contract that shapes a serialized ``FileUnit``."""

        digest = hashlib.sha256(self._fingerprint.digest("frontend").encode())
        for name in self._SOURCE_FILES:
            encoded_name = name.encode()
            digest.update(len(encoded_name).to_bytes(8, "big"))
            digest.update(encoded_name)
            try:
                with open(os.path.join(self._source_directory, name), "rb") as source_file:
                    content = source_file.read()
            except OSError:
                content = b"<missing>"
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return digest.hexdigest()[:16]


_UNIT_CACHE_VERSION = FileUnitCacheSchema().current_version()


@dataclass(frozen=True)
class FileDependency:
    """One parsed source dependency in its native file coordinates."""

    line: int
    spec: import_spec
    kind: SourceDependencyKind


@dataclass(frozen=True)
class FileDependencies:
    """Typed dependencies extracted from one file's declarations."""

    entries: tuple[FileDependency, ...] = ()

    @classmethod
    def from_declarations(cls, declarations: list) -> FileDependencies:
        dependencies: list[FileDependency] = []
        for declaration in declarations:
            if isinstance(declaration, ImportDecl):
                dependencies.append(
                    FileDependency(
                        line=declaration.line,
                        spec=declaration.spec,
                        kind=SourceDependencyKind.IMPORT,
                    )
                )
                continue
            if not isinstance(declaration, PreprocessorDirective):
                continue
            include = CINCLUDE_BTRC_RE.match(declaration.text)
            if include:
                dependencies.append(
                    FileDependency(
                        line=declaration.line,
                        spec=RelativePath(path=include.group(1)),
                        kind=SourceDependencyKind.INCLUDE,
                    )
                )
        return cls(tuple(dependencies))

    def __iter__(self) -> Iterator[FileDependency]:
        return iter(self.entries)


@dataclass
class FileUnit:
    """One file's lex/parse output, positions native to that file."""

    path: str  # absolute path
    source: str
    content_hash: str
    tokens: list[Token] = field(default_factory=list)
    decls: list = field(default_factory=list)
    dependencies: FileDependencies = field(default_factory=FileDependencies)
    defined_names: frozenset[str] = frozenset()
    lex_error: LexerError | None = None
    parse_error: ParseError | None = None
    # Lazy line -> tokens index, excluded from equality so cached units compare
    # by content.
    _line_index: dict[int, list[Token]] | None = field(default=None, repr=False, compare=False)

    @property
    def error(self) -> Exception | None:
        return self.lex_error or self.parse_error

    @classmethod
    def parse(
        cls,
        path: str,
        source: str,
        *,
        stdlib: StdlibRepository | None = None,
    ) -> FileUnit:
        """Lex and parse one file in its own coordinate space."""

        unit = cls(
            path=os.path.abspath(path),
            source=source,
            content_hash=hashlib.sha256(source.encode()).hexdigest(),
            defined_names=frozenset((stdlib or StdlibRepository()).defined_names(source)),
        )
        try:
            unit.tokens = Lexer(source, os.path.basename(path)).tokenize()
        except LexerError as error:
            unit.lex_error = error
            return unit
        try:
            program = Parser(unit.tokens).parse()
        except ParseError as error:
            unit.parse_error = error
            return unit
        unit.decls = program.declarations
        unit.dependencies = FileDependencies.from_declarations(unit.decls)
        for declaration in unit.decls:
            declaration.source_file = unit.path
        return unit

    def token_index(self) -> dict[int, list[Token]]:
        """Return this unit's cached 1-based line-to-token index."""

        if self._line_index is None:
            index: dict[int, list[Token]] = {}
            for token in self.tokens:
                if token.type != TokenType.EOF:
                    index.setdefault(token.line, []).append(token)
            self._line_index = index
        return self._line_index
