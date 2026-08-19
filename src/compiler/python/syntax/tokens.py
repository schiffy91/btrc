"""Token vocabulary and preprocessor value types for the btrc language.

TokenKind lookup tables are validated against src/language/grammar.ebnf when
the canonical vocabulary is first requested.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from functools import lru_cache
from types import MappingProxyType

from .grammar import GrammarInfo, GrammarRepository


class TokenKind(Enum):
    # Literals
    INT_LIT = auto()
    FLOAT_LIT = auto()
    STRING_LIT = auto()
    CHAR_LIT = auto()
    IDENT = auto()

    # C keywords
    AUTO = auto()
    BREAK = auto()
    CASE = auto()
    CHAR = auto()
    CONST = auto()
    CONTINUE = auto()
    DEFAULT = auto()
    DO = auto()
    DOUBLE = auto()
    ELSE = auto()
    ENUM = auto()
    EXTERN = auto()
    FLOAT = auto()
    FOR = auto()
    GOTO = auto()
    IF = auto()
    INT = auto()
    LONG = auto()
    REGISTER = auto()
    RETURN = auto()
    SHORT = auto()
    SIGNED = auto()
    SIZEOF = auto()
    STATIC = auto()
    STRUCT = auto()
    SWITCH = auto()
    TYPEDEF = auto()
    UNION = auto()
    UNSIGNED = auto()
    VOID = auto()
    VOLATILE = auto()
    WHILE = auto()

    # btrc keywords
    ABSTRACT = auto()
    BOOL = auto()
    CATCH = auto()
    CLASS = auto()
    DELETE = auto()
    EXTENDS = auto()
    FALSE = auto()
    FINALLY = auto()
    FUNCTION = auto()
    IMPLEMENTS = auto()
    IMPORT = auto()
    IN = auto()
    INTERFACE = auto()
    KEEP = auto()
    NEW = auto()
    NULL = auto()
    OVERRIDE = auto()
    PARALLEL = auto()
    PRIVATE = auto()
    PUBLIC = auto()
    RELEASE = auto()
    SELF = auto()
    SPAWN = auto()
    STRING = auto()
    SUPER = auto()
    THROW = auto()
    TRUE = auto()
    TRY = auto()
    VAR = auto()

    # Annotations (validated against grammar @annotations section)
    AT_GPU = auto()

    # Operators
    PLUS = auto()  # +
    MINUS = auto()  # -
    STAR = auto()  # *
    SLASH = auto()  # /
    PERCENT = auto()  # %
    EQ = auto()  # =
    EQ_EQ = auto()  # ==
    BANG_EQ = auto()  # !=
    LT = auto()  # <
    GT = auto()  # >
    LT_EQ = auto()  # <=
    GT_EQ = auto()  # >=
    AMP_AMP = auto()  # &&
    PIPE_PIPE = auto()  # ||
    BANG = auto()  # !
    AMP = auto()  # &
    PIPE = auto()  # |
    CARET = auto()  # ^
    TILDE = auto()  # ~
    LT_LT = auto()  # <<
    GT_GT = auto()  # >>
    PLUS_EQ = auto()  # +=
    MINUS_EQ = auto()  # -=
    STAR_EQ = auto()  # *=
    SLASH_EQ = auto()  # /=
    PERCENT_EQ = auto()  # %=
    AMP_EQ = auto()  # &=
    PIPE_EQ = auto()  # |=
    CARET_EQ = auto()  # ^=
    LT_LT_EQ = auto()  # <<=
    GT_GT_EQ = auto()  # >>=
    PLUS_PLUS = auto()  # ++
    MINUS_MINUS = auto()  # --
    ARROW = auto()  # ->
    FAT_ARROW = auto()  # =>
    DOT = auto()  # .
    QUESTION = auto()  # ?
    QUESTION_DOT = auto()  # ?.
    QUESTION_QUESTION = auto()  # ??
    COLON = auto()  # :
    COMMA = auto()  # ,
    SEMICOLON = auto()  # ;

    # Delimiters
    LPAREN = auto()  # (
    RPAREN = auto()  # )
    LBRACKET = auto()  # [
    RBRACKET = auto()  # ]
    LBRACE = auto()  # {
    RBRACE = auto()  # }

    # Special
    PREPROCESSOR = auto()
    FSTRING_LIT = auto()  # f"..." raw content (without quotes)
    PATH_SPEC = auto()  # raw import path: ./x.btrc, ../y, /abs, ~/home
    EOF = auto()


@dataclass
class Token:
    type: TokenKind
    value: str
    line: int
    col: int

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.col})"


_HORIZONTAL_SPACE = "[ \\t\\f\\v\\r]"
_SOURCE_DIRECTIVE = re.compile(
    f"^{_HORIZONTAL_SPACE}*#{_HORIZONTAL_SPACE}*(define|undef)\\b(.*)$",
    re.DOTALL,
)
_SOURCE_SYMBOL = re.compile(
    f"^{_HORIZONTAL_SPACE}+([A-Za-z_][A-Za-z0-9_]*)(.*)$",
    re.DOTALL,
)
_SOURCE_IDENTIFIER = re.compile("^[A-Za-z_][A-Za-z0-9_]*$")
_LINE_SPLICE = re.compile("(?:\\\\|\\?\\?/)\\r?\\n")
_TOKEN_PASTE_SPELLINGS = ("##", "%:%:", "??=??=")


@dataclass(frozen=True, slots=True)
class SourceSymbolDirective:
    """One parsed ``#define``/``#undef`` and its structural queries."""

    operation: str
    name: str
    parameters: frozenset[str] = frozenset()
    replacement: str = ""
    parameter_order: tuple[str, ...] = ()
    function_like: bool = False
    variadic: bool = False
    invalid_parameters: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> SourceSymbolDirective | None:
        """Parse the symbol-bearing portion of one define/undef directive."""
        text = cls._normalize_preprocessing(text)
        directive_match = _SOURCE_DIRECTIVE.fullmatch(text)
        if directive_match is None:
            return None
        operation, payload = directive_match.groups()
        name_match = _SOURCE_SYMBOL.fullmatch(payload)
        if name_match is None:
            return None
        name, suffix = name_match.groups()
        if operation == "undef":
            return cls(operation, name)
        if not suffix.startswith("("):
            return cls(operation, name, replacement=suffix.lstrip())
        close = suffix.find(")")
        if close < 0:
            return cls(operation, name, replacement=suffix, function_like=True)
        parameter_text = suffix[1:close].strip()
        raw_parameters = () if not parameter_text else tuple(item.strip() for item in parameter_text.split(","))
        parameter_order: list[str] = []
        invalid_parameters: list[str] = []
        variadic = False
        for index, parameter in enumerate(raw_parameters):
            if parameter == "...":
                if variadic or index != len(raw_parameters) - 1:
                    invalid_parameters.append(parameter)
                variadic = True
            elif not _SOURCE_IDENTIFIER.fullmatch(parameter) or parameter in parameter_order:
                invalid_parameters.append(parameter)
            else:
                parameter_order.append(parameter)
        parameters = set(parameter_order)
        if variadic:
            parameters.add("__VA_ARGS__")
        return cls(
            operation,
            name,
            parameters=frozenset(parameters),
            replacement=suffix[close + 1 :].lstrip(),
            parameter_order=tuple(parameter_order),
            function_like=True,
            variadic=variadic,
            invalid_parameters=tuple(invalid_parameters),
        )

    @property
    def expected_arity(self) -> int | None:
        """Return exact arity, or ``None`` for a variadic definition."""
        return None if self.variadic else len(self.parameter_order)

    @property
    def minimum_arity(self) -> int:
        """Return the representable strict-C11 minimum invocation arity."""
        if self.variadic and self.parameter_order:
            return len(self.parameter_order) + 1
        return len(self.parameter_order)

    def accepts_arity(self, argument_count: int) -> bool:
        if not self.function_like or self.invalid_parameters:
            return False
        expected = self.expected_arity
        return argument_count >= self.minimum_arity if expected is None else argument_count == expected

    def replacement_identifiers(self) -> tuple[str, ...]:
        """Return code identifiers, excluding parameters and literal/comment text."""
        if self.operation != "define":
            return ()
        identifiers: list[str] = []
        text = self.replacement
        index = 0
        while index < len(text):
            value = text[index]
            if value in {'"', "'"}:
                index = self._skip_quoted(text, index, value)
                continue
            if text.startswith("//", index):
                break
            if text.startswith("/*", index):
                close = text.find("*/", index + 2)
                index = len(text) if close < 0 else close + 2
                continue
            if value == "_" or value.isalpha():
                end = index + 1
                while end < len(text) and (text[end] == "_" or text[end].isalnum()):
                    end += 1
                identifier = text[index:end]
                if identifier not in self.parameters and identifier not in identifiers:
                    identifiers.append(identifier)
                index = end
                continue
            index += 1
        return tuple(identifiers)

    def replacement_member_identifiers(self) -> tuple[str, ...]:
        """Return replacement identifiers used after ``.`` or ``->``."""
        if self.operation != "define":
            return ()
        members: list[str] = []
        text = self.replacement
        index = 0
        while index < len(text):
            value = text[index]
            if value in {'"', "'"}:
                index = self._skip_quoted(text, index, value)
                continue
            if text.startswith("//", index):
                break
            if value == "_" or value.isalpha():
                end = index + 1
                while end < len(text) and (text[end] == "_" or text[end].isalnum()):
                    end += 1
                previous = index - 1
                while previous >= 0 and text[previous].isspace():
                    previous -= 1
                member_access = previous >= 0 and text[previous] == "."
                member_access = member_access or (previous >= 1 and text[previous - 1 : previous + 1] == "->")
                identifier = text[index:end]
                if member_access and identifier not in self.parameters and (identifier not in members):
                    members.append(identifier)
                index = end
                continue
            index += 1
        return tuple(members)

    def uses_token_paste(self) -> bool:
        """Whether executable replacement text contains a C token-paste operator."""
        if self.operation != "define":
            return False
        text = self.replacement
        index = 0
        while index < len(text):
            value = text[index]
            if value in {'"', "'"}:
                index = self._skip_quoted(text, index, value)
                continue
            if text.startswith("//", index):
                return False
            if text.startswith("/*", index):
                close = text.find("*/", index + 2)
                index = len(text) if close < 0 else close + 2
                continue
            if any(text.startswith(spelling, index) for spelling in _TOKEN_PASTE_SPELLINGS):
                return True
            index += 1
        return False

    def single_call(self) -> tuple[str, tuple[str, ...]] | None:
        """Return a narrow exact ``callee(arg, ...)`` replacement shape."""
        if not self.function_like:
            return None
        text = self.replacement.split("//", 1)[0].strip()
        text = self.unwrap_identifier_groups(text, require_identifier=False)
        match = re.match("([A-Za-z_][A-Za-z0-9_]*)", text)
        if match is None:
            return None
        callee = match.group(1)
        index = match.end()
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text) or text[index] != "(":
            return None
        close = self._matching_parenthesis(text, index)
        if close is None or text[close + 1 :].strip():
            return None
        return (callee, tuple(self._split_call_arguments(text[index + 1 : close])))

    @classmethod
    def unwrapped_identifier(cls, text: str) -> str | None:
        """Return one identifier through redundant grouping parentheses."""
        value = cls.unwrap_identifier_groups(text, require_identifier=False)
        return value if _SOURCE_IDENTIFIER.fullmatch(value) else None

    @classmethod
    def unwrap_identifier_groups(cls, text: str, *, require_identifier: bool = True) -> str:
        text = text.strip()
        while text.startswith("("):
            close = cls._matching_parenthesis(text, 0)
            if close is None or text[close + 1 :].strip():
                break
            text = text[1:close].strip()
        if require_identifier and (not _SOURCE_IDENTIFIER.fullmatch(text)):
            return ""
        return text

    @classmethod
    def _normalize_preprocessing(cls, text: str) -> str:
        text = _LINE_SPLICE.sub("", text)
        normalized: list[str] = []
        index = 0
        while index < len(text):
            if text[index] in {'"', "'"}:
                end = cls._skip_quoted(text, index, text[index])
                normalized.append(text[index:end])
                index = end
            elif text.startswith("/*", index):
                close = text.find("*/", index + 2)
                normalized.append(" ")
                index = len(text) if close < 0 else close + 2
            else:
                normalized.append(text[index])
                index += 1
        return "".join(normalized)

    @classmethod
    def _matching_parenthesis(cls, text: str, start: int) -> int | None:
        depth = 0
        index = start
        while index < len(text):
            value = text[index]
            if value in {'"', "'"}:
                index = cls._skip_quoted(text, index, value)
                continue
            if value == "(":
                depth += 1
            elif value == ")":
                depth -= 1
                if depth == 0:
                    return index
            index += 1
        return None

    @classmethod
    def _split_call_arguments(cls, text: str) -> list[str]:
        if not text.strip():
            return []
        arguments: list[str] = []
        start = 0
        depth = 0
        index = 0
        while index < len(text):
            value = text[index]
            if value in {'"', "'"}:
                index = cls._skip_quoted(text, index, value)
                continue
            if value in "([{":
                depth += 1
            elif value in ")]}":
                depth -= 1
            elif value == "," and depth == 0:
                arguments.append(text[start:index].strip())
                start = index + 1
            index += 1
        arguments.append(text[start:].strip())
        return arguments

    @staticmethod
    def _skip_quoted(text: str, index: int, quote: str) -> int:
        index += 1
        while index < len(text):
            if text[index] == "\\":
                index += 2
            elif text[index] == quote:
                return index + 1
            else:
                index += 1
        return index


class TokenVocabulary:
    """Own validated token lookup tables and longest-operator matching."""

    def __init__(self, grammar: GrammarInfo) -> None:
        self.grammar = grammar
        self.keywords = self._token_table(
            grammar.keywords,
            grammar.keyword_to_token,
            "keyword",
        )
        self.operators = self._token_table(
            grammar.operators,
            grammar.op_to_token,
            "operator",
        )
        self.annotations = self._token_table(
            grammar.annotations,
            grammar.annotation_to_token,
            "annotation",
        )
        self._operator_trie = self._build_operator_trie()

    @classmethod
    @lru_cache(maxsize=1)
    def canonical(cls) -> TokenVocabulary:
        """Return the immutable vocabulary for the canonical grammar."""

        return cls(GrammarRepository.canonical().load())

    @staticmethod
    def _token_table(
        spellings: Iterable[str],
        token_names: Mapping[str, str],
        kind: str,
    ) -> Mapping[str, TokenKind]:
        table: dict[str, TokenKind] = {}
        for spelling in spellings:
            token_name = token_names[spelling]
            try:
                table[spelling] = TokenKind[token_name]
            except KeyError as error:
                raise RuntimeError(
                    f"Grammar {kind} {spelling!r} maps to TokenKind.{token_name} "
                    "which does not exist in the TokenKind enum. Add it to syntax/tokens.py."
                ) from error
        return MappingProxyType(table)

    def _build_operator_trie(self) -> dict:
        root: dict = {}
        for operator, token_type in self.operators.items():
            node = root
            for character in operator:
                node = node.setdefault(character, {})
            node[""] = token_type
        return root

    def match_operator(self, source: str, position: int) -> tuple[TokenKind, int] | None:
        """Return the longest grammar operator beginning at ``position``."""

        node = self._operator_trie
        best: tuple[TokenKind, int] | None = None
        offset = 0
        while position + offset < len(source):
            character = source[position + offset]
            child = node.get(character)
            if not isinstance(child, dict):
                break
            node = child
            offset += 1
            token_type = node.get("")
            if isinstance(token_type, TokenKind):
                best = (token_type, offset)
        return best


# Set of token types that represent type keywords (used by parser for disambiguation)
TYPE_KEYWORDS: frozenset[TokenKind] = frozenset(
    {
        TokenKind.VOID,
        TokenKind.INT,
        TokenKind.FLOAT,
        TokenKind.DOUBLE,
        TokenKind.CHAR,
        TokenKind.SHORT,
        TokenKind.LONG,
        TokenKind.UNSIGNED,
        TokenKind.SIGNED,
        TokenKind.STRING,
        TokenKind.BOOL,
        TokenKind.STRUCT,
        TokenKind.ENUM,
        TokenKind.UNION,
        TokenKind.CONST,
        TokenKind.STATIC,
        TokenKind.EXTERN,
        TokenKind.VOLATILE,
    }
)
