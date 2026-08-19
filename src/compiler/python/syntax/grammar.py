"""Owned loading and parsing of the language's lexical EBNF contract."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType


@dataclass(frozen=True)
class GrammarInfo:
    """Immutable lexical information derived from ``grammar.ebnf``."""

    keywords: frozenset[str]
    operators: tuple[str, ...]
    keyword_to_token: Mapping[str, str]
    op_to_token: Mapping[str, str]
    annotations: frozenset[str]
    annotation_to_token: Mapping[str, str]


class EbnfGrammarParser:
    """Parse the lexical portion of one EBNF document.

    Token names are derived here so the grammar remains the only keyword and
    operator inventory.  The parser has no process-global state and can be
    reused safely for generated-code tools and tests.
    """

    _CHAR_NAMES: Mapping[str, str] = MappingProxyType(
        {
            "+": "PLUS",
            "-": "MINUS",
            "*": "STAR",
            "/": "SLASH",
            "%": "PERCENT",
            "=": "EQ",
            "<": "LT",
            ">": "GT",
            "!": "BANG",
            "&": "AMP",
            "|": "PIPE",
            "^": "CARET",
            "~": "TILDE",
            "?": "QUESTION",
            ".": "DOT",
            ",": "COMMA",
            ";": "SEMICOLON",
            ":": "COLON",
            "(": "LPAREN",
            ")": "RPAREN",
            "[": "LBRACKET",
            "]": "RBRACKET",
            "{": "LBRACE",
            "}": "RBRACE",
        }
    )
    _SPECIAL_OPERATORS: Mapping[str, str] = MappingProxyType(
        {
            "->": "ARROW",
            "=>": "FAT_ARROW",
        }
    )

    def parse(self, text: str) -> GrammarInfo:
        """Return an immutable lexical snapshot from EBNF source text."""

        lexical_body = self.extract_brace_block(text, "@lexical")
        if lexical_body is None:
            raise ValueError("No @lexical section found in grammar")

        keyword_body = self.extract_brace_block(lexical_body, "@keywords")
        keywords = self._words_without_comments(keyword_body)

        operator_body = self.extract_brace_block(lexical_body, "@operators")
        operators = self._operators_without_comments(operator_body)

        annotation_body = self.extract_brace_block(lexical_body, "@annotations")
        annotations = self._words_without_comments(annotation_body)

        return GrammarInfo(
            keywords=frozenset(keywords),
            operators=tuple(operators),
            keyword_to_token=MappingProxyType({keyword: keyword.upper() for keyword in keywords}),
            op_to_token=MappingProxyType({operator: self.operator_token_name(operator) for operator in operators}),
            annotations=frozenset(annotations),
            annotation_to_token=MappingProxyType(
                {annotation: f"AT_{annotation.upper()}" for annotation in annotations}
            ),
        )

    def operator_token_name(self, operator: str) -> str:
        """Derive the ``TokenKind`` member name for an operator."""

        special = self._SPECIAL_OPERATORS.get(operator)
        if special is not None:
            return special
        if len(operator) == 1:
            name = self._CHAR_NAMES.get(operator)
            if name is None:
                raise ValueError(f"No character name for {operator!r}. Add it to EbnfGrammarParser._CHAR_NAMES.")
            return name

        parts: list[str] = []
        for character in operator:
            name = self._CHAR_NAMES.get(character)
            if name is None:
                raise ValueError(
                    f"No character name for {character!r} in operator {operator!r}. "
                    "Add it to EbnfGrammarParser._CHAR_NAMES."
                )
            parts.append(name)
        return "_".join(parts)

    def extract_brace_block(self, text: str, marker: str) -> str | None:
        """Extract a marker's balanced brace body, ignoring literal braces."""

        match = re.compile(re.escape(marker) + r"\s*\{").search(text)
        if match is None:
            return None
        brace_start = match.end() - 1
        depth = 1
        index = brace_start + 1
        while index < len(text) and depth > 0:
            character = text[index]
            if character == "-" and index + 1 < len(text) and text[index + 1] == "-":
                while index < len(text) and text[index] != "\n":
                    index += 1
                continue
            if character == "(" and index + 1 < len(text) and text[index + 1] == "*":
                index += 2
                while index + 1 < len(text) and not (text[index] == "*" and text[index + 1] == ")"):
                    index += 1
                index += 2
                continue
            if character == "/" and index + 1 < len(text) and text[index + 1] != "/":
                index += 1
                while index < len(text) and text[index] not in ("/", "\n"):
                    if text[index] == "\\":
                        index += 1
                    index += 1
                if index < len(text) and text[index] == "/":
                    index += 1
                continue
            if character == '"':
                index += 1
                while index < len(text) and text[index] != '"':
                    if text[index] == "\\":
                        index += 1
                    index += 1
                index += 1
                continue
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            index += 1
        if depth != 0:
            return None
        return text[brace_start + 1 : index - 1]

    @staticmethod
    def _words_without_comments(body: str | None) -> tuple[str, ...]:
        if body is None:
            return ()
        body = re.sub(r"--[^\n]*", "", body)
        return tuple(re.findall(r"[a-zA-Z_]\w*", body))

    @staticmethod
    def _operators_without_comments(body: str | None) -> tuple[str, ...]:
        if body is None:
            return ()
        operators = [operator for operator in re.findall(r'--[^\n]*|"([^"]+)"', body) if operator]
        return tuple(sorted(operators, key=lambda operator: (-len(operator), operator)))


class GrammarRepository:
    """Own one grammar path and its immutable, lazily loaded snapshot."""

    def __init__(self, path: str, parser: EbnfGrammarParser | None = None) -> None:
        self._path = os.path.abspath(path)
        self._parser = parser or EbnfGrammarParser()
        self._snapshot: GrammarInfo | None = None

    @classmethod
    def canonical(cls) -> GrammarRepository:
        language_directory = Path(__file__).resolve().parents[3] / "language"
        return cls(str(language_directory / "grammar.ebnf"))

    @property
    def path(self) -> str:
        return self._path

    def load(self) -> GrammarInfo:
        """Read and parse the owned grammar once for this repository."""

        if self._snapshot is None:
            with open(self._path, encoding="utf-8") as grammar_file:
                self._snapshot = self._parser.parse(grammar_file.read())
        return self._snapshot
