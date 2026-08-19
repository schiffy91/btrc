"""ASDL schema values and the parser that owns their construction."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AsdlField:
    """One typed field in an ASDL constructor or attribute list."""

    type_name: str
    name: str
    is_sequence: bool = False
    is_optional: bool = False


@dataclass(frozen=True, slots=True)
class AsdlConstructor:
    """One constructor in an ASDL product or sum type."""

    name: str
    fields: tuple[AsdlField, ...] = ()


@dataclass(frozen=True, slots=True)
class AsdlType:
    """One named ASDL product or sum type."""

    name: str
    constructors: tuple[AsdlConstructor, ...] = ()
    attributes: tuple[AsdlField, ...] = ()


@dataclass(frozen=True, slots=True)
class AsdlModule:
    """The immutable root of a parsed ASDL schema."""

    name: str
    types: tuple[AsdlType, ...] = ()


class AsdlSchemaParser:
    """Parse one Zephyr ASDL source document into immutable schema values."""

    _TOKEN_PATTERN = re.compile(
        r"""
        (--[^\n]*)                 |  # line comment
        ([a-zA-Z_][a-zA-Z0-9_]*)  |  # identifier
        ([{}()|,=?*])              |  # punctuation
        (\s+)                         # whitespace
        """,
        re.VERBOSE,
    )

    def __init__(self, source: str):
        self._tokens = self._tokenize(source)
        self._position = 0

    def parse(self) -> AsdlModule:
        """Parse the configured source document."""

        self._expect("module")
        name = self._advance()
        self._expect("{")
        types: list[AsdlType] = []
        while self._peek() != "}":
            types.append(self._parse_type())
        self._expect("}")
        return AsdlModule(name=name, types=tuple(types))

    def _tokenize(self, source: str) -> tuple[str, ...]:
        tokens: list[str] = []
        for match in self._TOKEN_PATTERN.finditer(source):
            comment, identifier, punctuation, whitespace = match.groups()
            if comment or whitespace:
                continue
            if identifier:
                tokens.append(identifier)
            elif punctuation:
                tokens.append(punctuation)
        return tuple(tokens)

    def _peek(self) -> str | None:
        if self._position < len(self._tokens):
            return self._tokens[self._position]
        return None

    def _advance(self) -> str:
        token = self._tokens[self._position]
        self._position += 1
        return token

    def _expect(self, expected: str) -> str:
        token = self._advance()
        if token != expected:
            raise SyntaxError(
                f"Expected {expected!r}, got {token!r} at token {self._position}"
            )
        return token

    def _parse_type(self) -> AsdlType:
        name = self._advance()
        self._expect("=")
        constructors = [self._parse_constructor()]
        while self._peek() == "|":
            self._advance()
            constructors.append(self._parse_constructor())

        attributes: tuple[AsdlField, ...] = ()
        if self._peek() == "attributes":
            self._advance()
            self._expect("(")
            attributes = self._parse_field_list()
            self._expect(")")

        return AsdlType(
            name=name,
            constructors=tuple(constructors),
            attributes=attributes,
        )

    def _parse_constructor(self) -> AsdlConstructor:
        name = self._advance()
        fields: tuple[AsdlField, ...] = ()
        if self._peek() == "(":
            self._advance()
            fields = self._parse_field_list()
            self._expect(")")
        return AsdlConstructor(name=name, fields=fields)

    def _parse_field_list(self) -> tuple[AsdlField, ...]:
        if self._peek() == ")":
            return ()
        fields = [self._parse_field()]
        while self._peek() == ",":
            self._advance()
            if self._peek() == ")":
                break
            fields.append(self._parse_field())
        return tuple(fields)

    def _parse_field(self) -> AsdlField:
        type_name = self._advance()
        is_sequence = False
        is_optional = False
        if self._peek() == "*":
            self._advance()
            is_sequence = True
        elif self._peek() == "?":
            self._advance()
            is_optional = True
        name = self._advance()
        return AsdlField(
            type_name=type_name,
            name=name,
            is_sequence=is_sequence,
            is_optional=is_optional,
        )
