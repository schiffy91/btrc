"""Owned source reads, directive scanning, and import-directory traversal."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .. import frontend_limits
from ..lexer import Lexer
from ..pkg import IncludeResolutionError
from ..tokens import Token, TokenType


class SourceReadError(OSError):
    """A source file could not be read under the compiler's input contract."""


class SourceFileReader:
    """Own bounded, deterministic UTF-8 reads for one compiler application."""

    DEFAULT_MAX_BYTES = 64 * 1024 * 1024

    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        if max_bytes <= 0:
            raise ValueError("source byte limit must be positive")
        self.max_bytes = max_bytes

    def read(self, path: str) -> str:
        """Read one bounded source file and normalize universal newlines."""

        try:
            with open(path, "rb") as source_file:
                encoded = source_file.read(self.max_bytes + 1)
        except FileNotFoundError as error:
            raise SourceReadError(f"source file {path!r} not found") from error
        except OSError as error:
            raise SourceReadError(f"cannot read source file {path!r}: {error}") from error
        if len(encoded) > self.max_bytes:
            raise SourceReadError(f"source file {path!r} exceeds the {self.max_bytes}-byte limit")
        try:
            text = encoded.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise SourceReadError(f"source file {path!r} is not valid UTF-8 at byte {error.start}") from error
        nul = text.find("\0")
        if nul >= 0:
            raise SourceReadError(f"source file {path!r} contains a NUL byte at character {nul}")
        return text.replace("\r\n", "\n").replace("\r", "\n")


@dataclass(frozen=True)
class SourceDirective:
    """One import or deprecated btrc-include with its owned line range."""

    kind: str
    payload: object
    start: int
    end: int


class SourceDirectiveScanner:
    """Own comment-aware import/include discovery through the real lexer."""

    _BTRC_INCLUDE = re.compile(r'^\s*#include\s+[<"]([^>"]+\.btrc)[>"]\s*$')

    def scan(self, source: str) -> list[SourceDirective]:
        """Return directives that own their complete source line range."""

        try:
            tokens = Lexer(source).tokenize()
        except Exception:
            return []  # malformed source: the main lexer/parser owns the error

        first_on_line: dict[int, Token] = {}
        last_on_line: dict[int, Token] = {}
        for token in tokens:
            if token.type == TokenType.EOF:
                continue
            first_on_line.setdefault(token.line, token)
            last_on_line[token.line] = token

        directives: list[SourceDirective] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.type == TokenType.IMPORT and first_on_line.get(token.line) is token:
                spec, next_index = self._parse_spec_tokens(tokens, index + 1)
                if spec is None:
                    index += 1
                    continue
                end_token = tokens[next_index - 1]
                if last_on_line.get(end_token.line) is end_token:
                    directives.append(
                        SourceDirective(
                            "import",
                            spec,
                            token.line,
                            end_token.line,
                        )
                    )
                index = next_index
                continue
            if token.type == TokenType.PREPROCESSOR and first_on_line.get(token.line) is token:
                include_path = self.btrc_include_path(token.value)
                if include_path is not None and last_on_line.get(token.line) is token:
                    directives.append(
                        SourceDirective(
                            "btrc_include",
                            include_path,
                            token.line,
                            token.line,
                        )
                    )
            index += 1
        return directives

    def btrc_include_path(self, preprocessor_text: str) -> str | None:
        """Return a quoted ``.btrc`` include path, or ``None`` for C includes."""

        match = self._BTRC_INCLUDE.match(preprocessor_text)
        return match.group(1) if match else None

    @staticmethod
    def _parse_spec_tokens(
        tokens: list[Token],
        start: int,
    ) -> tuple[object | None, int]:
        from ..parser.parser import Parser

        remaining = list(tokens[start:])
        remaining.append(Token(TokenType.EOF, "", 0, 0))
        parser = Parser(remaining)
        try:
            spec = parser._parse_import_spec()
        except Exception:
            return None, start
        parser._match(TokenType.SEMICOLON)
        return spec, start + parser.pos


class SourceDirectoryScanner:
    """Own bounded, deterministic filesystem traversal for directory imports."""

    _SOURCE_SUFFIXES = (".btrc", ".c")

    def __init__(
        self,
        *,
        max_entries: int | None = None,
        max_files: int | None = None,
    ) -> None:
        self._max_entries = frontend_limits.MAX_IMPORT_SCAN_ENTRIES if max_entries is None else max_entries
        self._max_files = frontend_limits.MAX_RESOLVED_FILES if max_files is None else max_files
        if self._max_entries <= 0 or self._max_files <= 0:
            raise ValueError("import scan limits must be positive")

    def scan(self, root: str, *, recursive: bool) -> list[str]:
        """Return sorted sources without materializing an unbounded listing."""

        matches: list[str] = []
        pending = [root]
        scanned_entries = 0
        try:
            while pending:
                current = pending.pop()
                child_directories: list[str] = []
                with os.scandir(current) as entries:
                    for entry in entries:
                        scanned_entries += 1
                        if scanned_entries > self._max_entries:
                            raise IncludeResolutionError(
                                f"import directory exceeds the {self._max_entries}-entry scan limit: {root!r}"
                            )
                        if recursive and entry.is_dir(follow_symlinks=False):
                            child_directories.append(entry.path)
                        elif entry.is_file() and entry.name.endswith(self._SOURCE_SUFFIXES):
                            if len(matches) >= self._max_files:
                                raise IncludeResolutionError(
                                    f"import directory exceeds the {self._max_files}-file limit: {root!r}"
                                )
                            matches.append(entry.path)
                if recursive:
                    pending.extend(sorted(child_directories, reverse=True))
        except OSError as error:
            raise IncludeResolutionError(f"cannot scan import directory {root!r}: {error}") from error
        return sorted(matches)


__all__ = [
    "SourceDirective",
    "SourceDirectiveScanner",
    "SourceDirectoryScanner",
    "SourceFileReader",
    "SourceReadError",
]
