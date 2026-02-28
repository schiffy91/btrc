"""Token type definitions for the btrc language.

TokenType enum and keyword table are validated against src/language/grammar.ebnf
at import time to ensure the grammar is the single source of truth.
"""

from enum import Enum, auto
from dataclasses import dataclass


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

    # Annotation
    AT_GPU = auto()

    # Operators
    PLUS = auto()          # +
    MINUS = auto()         # -
    STAR = auto()          # *
    SLASH = auto()         # /
    PERCENT = auto()       # %
    EQ = auto()            # =
    EQ_EQ = auto()         # ==
    BANG_EQ = auto()       # !=
    LT = auto()            # <
    GT = auto()            # >
    LT_EQ = auto()         # <=
    GT_EQ = auto()         # >=
    AMP_AMP = auto()       # &&
    PIPE_PIPE = auto()     # ||
    BANG = auto()           # !
    AMP = auto()            # &
    PIPE = auto()           # |
    CARET = auto()          # ^
    TILDE = auto()          # ~
    LT_LT = auto()         # <<
    GT_GT = auto()          # >>
    PLUS_EQ = auto()       # +=
    MINUS_EQ = auto()      # -=
    STAR_EQ = auto()       # *=
    SLASH_EQ = auto()      # /=
    PERCENT_EQ = auto()    # %=
    AMP_EQ = auto()        # &=
    PIPE_EQ = auto()       # |=
    CARET_EQ = auto()      # ^=
    LT_LT_EQ = auto()     # <<=
    GT_GT_EQ = auto()      # >>=
    PLUS_PLUS = auto()     # ++
    MINUS_MINUS = auto()   # --
    ARROW = auto()         # ->
    FAT_ARROW = auto()     # =>
    DOT = auto()           # .
    QUESTION = auto()      # ?
    QUESTION_DOT = auto()  # ?.
    QUESTION_QUESTION = auto()  # ??
    COLON = auto()         # :
    COMMA = auto()         # ,
    SEMICOLON = auto()     # ;

    # Delimiters
    LPAREN = auto()        # (
    RPAREN = auto()        # )
    LBRACKET = auto()      # [
    RBRACKET = auto()      # ]
    LBRACE = auto()        # {
    RBRACE = auto()        # }

    # Special
    PREPROCESSOR = auto()
    FSTRING_LIT = auto()   # f"..." raw content (without quotes)
    EOF = auto()


@dataclass
class Token:
    type: TokenType
    value: str
    line: int
    col: int

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.col})"


def _build_keyword_table() -> dict[str, TokenType]:
    """Build keyword lookup table, validated against the grammar."""
    from .ebnf import get_grammar_info
    gi = get_grammar_info()
    table: dict[str, TokenType] = {}
    for kw in gi.keywords:
        token_name = gi.keyword_to_token[kw]
        try:
            table[kw] = TokenType[token_name]
        except KeyError:
            raise RuntimeError(
                f"Grammar keyword {kw!r} maps to TokenType.{token_name} "
                f"which does not exist in the TokenType enum. "
                f"Add it to tokens.py."
            )
    return table


def _build_operator_table() -> dict[str, TokenType]:
    """Build operator lookup table, validated against the grammar."""
    from .ebnf import get_grammar_info
    gi = get_grammar_info()
    table: dict[str, TokenType] = {}
    for op in gi.operators:
        token_name = gi.op_to_token[op]
        try:
            table[op] = TokenType[token_name]
        except KeyError:
            raise RuntimeError(
                f"Grammar operator {op!r} maps to TokenType.{token_name} "
                f"which does not exist in the TokenType enum. "
                f"Add it to tokens.py."
            )
    return table


# Keyword lookup table: string -> TokenType (validated against grammar)
KEYWORDS: dict[str, TokenType] = _build_keyword_table()

# Operator lookup table: string -> TokenType (validated against grammar)
OPERATORS: dict[str, TokenType] = _build_operator_table()

# Set of token types that represent type keywords (used by parser for disambiguation)
TYPE_KEYWORDS: set[TokenType] = {
    TokenType.VOID, TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE,
    TokenType.CHAR, TokenType.SHORT, TokenType.LONG, TokenType.UNSIGNED,
    TokenType.SIGNED, TokenType.STRING, TokenType.BOOL,
    TokenType.STRUCT, TokenType.ENUM, TokenType.UNION,
    TokenType.CONST, TokenType.STATIC, TokenType.EXTERN, TokenType.VOLATILE,
}
