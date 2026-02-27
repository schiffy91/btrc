"""ASDL file parser.

Reads a Zephyr ASDL file and produces a data structure representing
the module definition. Used by asdl_python.py and asdl_btrc.py to
generate language-specific AST node definitions.

ASDL grammar (simplified):
    module     = "module" id "{" { type } "}"
    type       = id "=" constructor { "|" constructor } [attributes]
    constructor = id ["(" field { "," field } ")"]
    field      = type_id ["?" | "*"] id
    attributes = "attributes" "(" field { "," field } ")"
    type_id    = "identifier" | "string" | "int" | "float" | "bool" | id
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import re


# --- Data model ---

@dataclass
class Field:
    """A single field in a constructor or attributes."""
    type: str          # "expr", "stmt", "string", "int", "bool", etc.
    name: str          # field name
    seq: bool = False  # True if * (sequence)
    opt: bool = False  # True if ? (optional)


@dataclass
class Constructor:
    """A single constructor (variant) of a sum type, or a product type."""
    name: str
    fields: list[Field] = field(default_factory=list)


@dataclass
class Type:
    """A named type definition. Can be a sum type (multiple constructors)
    or a product type (single constructor)."""
    name: str
    constructors: list[Constructor] = field(default_factory=list)
    attributes: list[Field] = field(default_factory=list)


@dataclass
class Module:
    """The top-level ASDL module."""
    name: str
    types: list[Type] = field(default_factory=list)


# --- Tokenizer ---

_TOKEN_RE = re.compile(r"""
    (--[^\n]*)           |  # line comment
    ([a-zA-Z_][a-zA-Z0-9_]*) |  # identifier
    ([{}()|,=?*])         |  # punctuation
    (\s+)                    # whitespace
""", re.VERBOSE)


def _tokenize(source: str) -> list[str]:
    """Tokenize ASDL source, stripping comments and whitespace."""
    tokens = []
    for m in _TOKEN_RE.finditer(source):
        comment, ident, punct, ws = m.groups()
        if comment or ws:
            continue
        if ident:
            tokens.append(ident)
        elif punct:
            tokens.append(punct)
    return tokens


# --- Parser ---

class ASDLParser:
    """Recursive descent parser for ASDL."""

    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> Optional[str]:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _advance(self) -> str:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, expected: str) -> str:
        tok = self._advance()
        if tok != expected:
            raise SyntaxError(
                f"Expected {expected!r}, got {tok!r} at token {self.pos}")
        return tok

    def parse_module(self) -> Module:
        """module = 'module' id '{' { type } '}'"""
        self._expect("module")
        name = self._advance()
        self._expect("{")
        types = []
        while self._peek() != "}":
            types.append(self._parse_type())
        self._expect("}")
        return Module(name=name, types=types)

    def _parse_type(self) -> Type:
        """type = id '=' constructor { '|' constructor } [attributes]"""
        name = self._advance()
        self._expect("=")
        constructors = [self._parse_constructor()]
        while self._peek() == "|":
            self._advance()  # consume '|'
            constructors.append(self._parse_constructor())

        attributes = []
        if self._peek() == "attributes":
            self._advance()  # consume 'attributes'
            self._expect("(")
            attributes = self._parse_field_list()
            self._expect(")")

        return Type(name=name, constructors=constructors,
                    attributes=attributes)

    def _parse_constructor(self) -> Constructor:
        """constructor = id ['(' field { ',' field } ')']"""
        name = self._advance()
        fields = []
        if self._peek() == "(":
            self._advance()  # consume '('
            fields = self._parse_field_list()
            self._expect(")")
        return Constructor(name=name, fields=fields)

    def _parse_field_list(self) -> list[Field]:
        """field { ',' field }"""
        if self._peek() == ")":
            return []
        fields = [self._parse_field()]
        while self._peek() == ",":
            self._advance()  # consume ','
            if self._peek() == ")":
                break  # trailing comma
            fields.append(self._parse_field())
        return fields

    def _parse_field(self) -> Field:
        """field = type_id ['?' | '*'] id"""
        type_name = self._advance()
        seq = False
        opt = False
        if self._peek() == "*":
            self._advance()
            seq = True
        elif self._peek() == "?":
            self._advance()
            opt = True
        name = self._advance()
        return Field(type=type_name, name=name, seq=seq, opt=opt)


def parse(source: str) -> Module:
    """Parse an ASDL source string into a Module."""
    tokens = _tokenize(source)
    parser = ASDLParser(tokens)
    return parser.parse_module()


def parse_file(path: str) -> Module:
    """Parse an ASDL file into a Module."""
    with open(path) as f:
        return parse(f.read())
