"""Token type definitions for the btrc language."""

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
    CLASS = auto()
    PUBLIC = auto()
    PRIVATE = auto()
    SELF = auto()
    IN = auto()
    PARALLEL = auto()
    STRING = auto()
    BOOL = auto()
    TRUE = auto()
    FALSE = auto()
    NEW = auto()
    DELETE = auto()
    NULL = auto()
    TRY = auto()
    CATCH = auto()
    THROW = auto()
    EXTENDS = auto()
    VAR = auto()

    # Built-in types
    LIST = auto()
    MAP = auto()
    ARRAY = auto()

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


# Keyword lookup table: string -> TokenType
KEYWORDS: dict[str, TokenType] = {
    # C keywords
    "auto": TokenType.AUTO,
    "break": TokenType.BREAK,
    "case": TokenType.CASE,
    "char": TokenType.CHAR,
    "const": TokenType.CONST,
    "continue": TokenType.CONTINUE,
    "default": TokenType.DEFAULT,
    "do": TokenType.DO,
    "double": TokenType.DOUBLE,
    "else": TokenType.ELSE,
    "enum": TokenType.ENUM,
    "extern": TokenType.EXTERN,
    "float": TokenType.FLOAT,
    "for": TokenType.FOR,
    "goto": TokenType.GOTO,
    "if": TokenType.IF,
    "int": TokenType.INT,
    "long": TokenType.LONG,
    "register": TokenType.REGISTER,
    "return": TokenType.RETURN,
    "short": TokenType.SHORT,
    "signed": TokenType.SIGNED,
    "sizeof": TokenType.SIZEOF,
    "static": TokenType.STATIC,
    "struct": TokenType.STRUCT,
    "switch": TokenType.SWITCH,
    "typedef": TokenType.TYPEDEF,
    "union": TokenType.UNION,
    "unsigned": TokenType.UNSIGNED,
    "void": TokenType.VOID,
    "volatile": TokenType.VOLATILE,
    "while": TokenType.WHILE,
    # btrc keywords
    "class": TokenType.CLASS,
    "public": TokenType.PUBLIC,
    "private": TokenType.PRIVATE,
    "self": TokenType.SELF,
    "in": TokenType.IN,
    "parallel": TokenType.PARALLEL,
    "string": TokenType.STRING,
    "bool": TokenType.BOOL,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "new": TokenType.NEW,
    "delete": TokenType.DELETE,
    "null": TokenType.NULL,
    "try": TokenType.TRY,
    "catch": TokenType.CATCH,
    "throw": TokenType.THROW,
    "extends": TokenType.EXTENDS,
    "var": TokenType.VAR,
    # Built-in types
    "List": TokenType.LIST,
    "Map": TokenType.MAP,
    "Array": TokenType.ARRAY,
}

# Set of token types that represent type keywords (used by parser for disambiguation)
TYPE_KEYWORDS: set[TokenType] = {
    TokenType.VOID, TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE,
    TokenType.CHAR, TokenType.SHORT, TokenType.LONG, TokenType.UNSIGNED,
    TokenType.SIGNED, TokenType.STRING, TokenType.BOOL,
    TokenType.LIST, TokenType.MAP, TokenType.ARRAY,
    TokenType.STRUCT, TokenType.ENUM, TokenType.UNION,
    TokenType.CONST, TokenType.STATIC, TokenType.EXTERN, TokenType.VOLATILE,
}
