"""Lossless lexical structure for source-preserving formatting.

The compiler lexer remains the authority for language validity. This scanner
retains the trivia that compiler tokens intentionally discard, allowing layout
edits without interpreting comment or literal contents as code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from src.compiler.python.syntax.tokens import TokenVocabulary


class LexemeKind(Enum):
    WORD = auto()
    NUMBER = auto()
    SYMBOL = auto()
    STRING = auto()
    CHARACTER = auto()
    LINE_COMMENT = auto()
    BLOCK_COMMENT = auto()
    PREPROCESSOR = auto()
    WHITESPACE = auto()
    NEWLINE = auto()


@dataclass(frozen=True, slots=True)
class Lexeme:
    kind: LexemeKind
    text: str
    start: int
    end: int
    line: int
    column: int
    end_line: int

    @property
    def is_trivia(self) -> bool:
        return self.kind in {
            LexemeKind.WHITESPACE,
            LexemeKind.NEWLINE,
            LexemeKind.LINE_COMMENT,
            LexemeKind.BLOCK_COMMENT,
        }

    @property
    def is_comment(self) -> bool:
        return self.kind in {LexemeKind.LINE_COMMENT, LexemeKind.BLOCK_COMMENT}


class LosslessScanner:
    """Split source into code and protected trivia without losing a byte."""

    def __init__(self, source: str) -> None:
        self.source = source
        self._vocabulary = TokenVocabulary.canonical()
        self._position = 0
        self._line = 1
        self._column = 1
        self._line_prefix = True

    def scan(self) -> tuple[Lexeme, ...]:
        result: list[Lexeme] = []
        while self._position < len(self.source):
            start = self._position
            line = self._line
            column = self._column
            kind = self._scan_one()
            result.append(
                Lexeme(
                    kind=kind,
                    text=self.source[start : self._position],
                    start=start,
                    end=self._position,
                    line=line,
                    column=column,
                    end_line=self._line,
                )
            )
        return tuple(result)

    def _scan_one(self) -> LexemeKind:
        character = self.source[self._position]
        if character in " \t\f\v":
            while self._peek() in " \t\f\v":
                self._advance()
            return LexemeKind.WHITESPACE
        if character in "\r\n":
            self._consume_newline()
            return LexemeKind.NEWLINE
        if self.source.startswith("//", self._position):
            while self._position < len(self.source) and self._peek() not in "\r\n":
                self._advance()
            return LexemeKind.LINE_COMMENT
        if self.source.startswith("/*", self._position):
            self._advance(2)
            while self._position < len(self.source) and not self.source.startswith("*/", self._position):
                if self._peek() in "\r\n":
                    self._consume_newline(in_token=True)
                else:
                    self._advance()
            if self.source.startswith("*/", self._position):
                self._advance(2)
            return LexemeKind.BLOCK_COMMENT
        if character == "#" and self._line_prefix:
            self._scan_preprocessor()
            return LexemeKind.PREPROCESSOR
        if character == '"':
            self._scan_string()
            return LexemeKind.STRING
        if character == "'":
            self._scan_quoted("'")
            return LexemeKind.CHARACTER
        if character == "_" or (character.isascii() and character.isalpha()):
            self._advance()
            while (next_character := self._peek()) == "_" or (next_character.isascii() and next_character.isalnum()):
                self._advance()
            return LexemeKind.WORD
        if character.isascii() and character.isdigit():
            self._scan_number()
            return LexemeKind.NUMBER

        match = self._vocabulary.match_operator(self.source, self._position)
        self._advance(match[1] if match is not None else 1)
        return LexemeKind.SYMBOL

    def _scan_string(self) -> None:
        if self.source.startswith('"""', self._position):
            self._advance(3)
            while self._position < len(self.source):
                if self.source.startswith('"""', self._position):
                    self._advance(3)
                    return
                if self._peek() == "\\":
                    self._advance()
                    if self._position < len(self.source):
                        if self._peek() in "\r\n":
                            self._consume_newline(in_token=True)
                        else:
                            self._advance()
                elif self._peek() in "\r\n":
                    self._consume_newline(in_token=True)
                else:
                    self._advance()
            return
        self._scan_quoted('"')

    def _scan_quoted(self, delimiter: str) -> None:
        self._advance()
        while self._position < len(self.source):
            character = self._peek()
            if character == "\\":
                self._advance()
                if self._position < len(self.source):
                    if self._peek() in "\r\n":
                        self._consume_newline(in_token=True)
                    else:
                        self._advance()
            elif character == delimiter:
                self._advance()
                return
            elif character in "\r\n":
                self._consume_newline(in_token=True)
            else:
                self._advance()

    def _scan_number(self) -> None:
        self._advance()
        exponent = False
        while self._position < len(self.source):
            character = self._peek()
            if character == "_" or (character.isascii() and character.isalnum()):
                exponent = character in "eEpP"
                self._advance()
            elif (character == "." and self._peek(1) != ".") or (character in "+-" and exponent):
                exponent = False
                self._advance()
            else:
                return

    def _scan_preprocessor(self) -> None:
        while self._position < len(self.source):
            if self._peek() in "\r\n":
                if self._preprocessor_is_spliced():
                    self._consume_newline(in_token=True)
                    continue
                return
            self._advance()

    def _preprocessor_is_spliced(self) -> bool:
        cursor = self._position - 1
        while cursor >= 0 and self.source[cursor] in " \t":
            cursor -= 1
        return cursor >= 0 and (
            self.source[cursor] == "\\" or (cursor >= 2 and self.source[cursor - 2 : cursor + 1] == "??/")
        )

    def _peek(self, offset: int = 0) -> str:
        position = self._position + offset
        return self.source[position] if position < len(self.source) else "\0"

    def _advance(self, width: int = 1) -> None:
        for _ in range(width):
            character = self.source[self._position]
            self._position += 1
            self._column += 1
            if character not in " \t\f\v":
                self._line_prefix = False

    def _consume_newline(self, *, in_token: bool = False) -> None:
        if self._peek() == "\r":
            self._position += 1
            if self._peek() == "\n":
                self._position += 1
        else:
            self._position += 1
        self._line += 1
        self._column = 1
        self._line_prefix = True
        if in_token:
            # The next physical line is still lexically inside the token. The
            # flag only controls whether a later '#' can begin a directive.
            self._line_prefix = False
