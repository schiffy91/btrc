"""Token type definitions for the btrc language.

TokenType enum and keyword table are validated against src/language/grammar.ebnf
at import time to ensure the grammar is the single source of truth.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from types import MappingProxyType

from .ebnf import GrammarInfo, GrammarRepository


class TokenType(Enum):
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
    type: TokenType
    value: str
    line: int
    col: int

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.col})"


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

    @staticmethod
    def _token_table(
        spellings: Iterable[str],
        token_names: Mapping[str, str],
        kind: str,
    ) -> Mapping[str, TokenType]:
        table: dict[str, TokenType] = {}
        for spelling in spellings:
            token_name = token_names[spelling]
            try:
                table[spelling] = TokenType[token_name]
            except KeyError as error:
                raise RuntimeError(
                    f"Grammar {kind} {spelling!r} maps to TokenType.{token_name} "
                    "which does not exist in the TokenType enum. Add it to tokens.py."
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

    def match_operator(self, source: str, position: int) -> tuple[TokenType, int] | None:
        """Return the longest grammar operator beginning at ``position``."""

        node = self._operator_trie
        best: tuple[TokenType, int] | None = None
        offset = 0
        while position + offset < len(source):
            character = source[position + offset]
            child = node.get(character)
            if not isinstance(child, dict):
                break
            node = child
            offset += 1
            token_type = node.get("")
            if isinstance(token_type, TokenType):
                best = (token_type, offset)
        return best


# Immutable canonical language data, validated once when token definitions load.
DEFAULT_VOCABULARY = TokenVocabulary(GrammarRepository.canonical().load())

# Set of token types that represent type keywords (used by parser for disambiguation)
TYPE_KEYWORDS: frozenset[TokenType] = frozenset(
    {
        TokenType.VOID,
        TokenType.INT,
        TokenType.FLOAT,
        TokenType.DOUBLE,
        TokenType.CHAR,
        TokenType.SHORT,
        TokenType.LONG,
        TokenType.UNSIGNED,
        TokenType.SIGNED,
        TokenType.STRING,
        TokenType.BOOL,
        TokenType.STRUCT,
        TokenType.ENUM,
        TokenType.UNION,
        TokenType.CONST,
        TokenType.STATIC,
        TokenType.EXTERN,
        TokenType.VOLATILE,
    }
)
