"""EBNF grammar parser for the btrc language.

Reads src/language/grammar.ebnf and extracts:
  - keywords: the set of reserved keywords
  - operators: the list of operators/delimiters (sorted longest-first)
  - keyword_to_token: mapping from keyword string to TokenType name
  - op_to_token: mapping from operator string to TokenType name

The lexer and tokens module import from here to build their lookup tables,
making the grammar the single source of truth for what tokens exist.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


@dataclass
class GrammarInfo:
    """Structured information extracted from the EBNF grammar."""
    keywords: set[str] = field(default_factory=set)
    operators: list[str] = field(default_factory=list)  # sorted longest-first
    keyword_to_token: dict[str, str] = field(default_factory=dict)
    op_to_token: dict[str, str] = field(default_factory=dict)


# Character → TokenType name component (single source for deriving operator names)
_CHAR_NAMES: dict[str, str] = {
    '+': 'PLUS', '-': 'MINUS', '*': 'STAR', '/': 'SLASH', '%': 'PERCENT',
    '=': 'EQ', '<': 'LT', '>': 'GT', '!': 'BANG', '&': 'AMP',
    '|': 'PIPE', '^': 'CARET', '~': 'TILDE', '?': 'QUESTION',
    '.': 'DOT', ',': 'COMMA', ';': 'SEMICOLON', ':': 'COLON',
    '(': 'LPAREN', ')': 'RPAREN', '[': 'LBRACKET', ']': 'RBRACKET',
    '{': 'LBRACE', '}': 'RBRACE',
}

# Operators whose TokenType name doesn't follow the character-join convention
_SPECIAL_OPS: dict[str, str] = {
    '->': 'ARROW',
    '=>': 'FAT_ARROW',
}


def _op_to_token_name(op: str) -> str:
    """Derive a TokenType name from an operator string.

    Single-char operators use _CHAR_NAMES directly (e.g. "+" → "PLUS").
    Multi-char operators join character names with "_" (e.g. "+=" → "PLUS_EQ").
    Special cases (like "->" → "ARROW") are handled by _SPECIAL_OPS.
    """
    if op in _SPECIAL_OPS:
        return _SPECIAL_OPS[op]
    if len(op) == 1:
        name = _CHAR_NAMES.get(op)
        if name is None:
            raise ValueError(f"No character name for {op!r}. Add it to _CHAR_NAMES.")
        return name
    parts = []
    for ch in op:
        name = _CHAR_NAMES.get(ch)
        if name is None:
            raise ValueError(
                f"No character name for {ch!r} in operator {op!r}. "
                f"Add it to _CHAR_NAMES."
            )
        parts.append(name)
    return '_'.join(parts)


def _keyword_to_token_name(kw: str) -> str:
    """Convert a keyword string to its TokenType enum name.

    e.g. "class" -> "CLASS", "if" -> "IF"
    """
    return kw.upper()


def _extract_brace_block(text: str, marker: str) -> str | None:
    """Extract the content between { } after a @marker, handling nested braces."""
    # Find marker followed (possibly with whitespace) by {
    pattern = re.compile(re.escape(marker) + r'\s*\{')
    m = pattern.search(text)
    if m is None:
        return None
    brace_start = m.end() - 1  # position of the '{'
    # Count braces to find the matching close, skipping quoted strings
    # and -- line comments and /.../ regex patterns
    depth = 1
    i = brace_start + 1
    while i < len(text) and depth > 0:
        ch = text[i]
        if ch == '-' and i + 1 < len(text) and text[i + 1] == '-':
            # Line comment: skip to end of line
            while i < len(text) and text[i] != '\n':
                i += 1
            continue
        elif ch == '(' and i + 1 < len(text) and text[i + 1] == '*':
            # Block comment (* ... *)
            i += 2
            while i + 1 < len(text) and not (text[i] == '*' and text[i + 1] == ')'):
                i += 1
            i += 2
            continue
        elif ch == '/':
            # Possible regex pattern: /.../ (not followed by / for //)
            if i + 1 < len(text) and text[i + 1] != '/':
                # Skip regex pattern: scan to next /
                i += 1
                while i < len(text) and text[i] != '/' and text[i] != '\n':
                    if text[i] == '\\':
                        i += 1  # skip escaped char
                    i += 1
                if i < len(text) and text[i] == '/':
                    i += 1  # skip closing /
                continue
        elif ch == '"':
            # Skip quoted string
            i += 1
            while i < len(text) and text[i] != '"':
                if text[i] == '\\':
                    i += 1  # skip escaped char
                i += 1
            i += 1  # skip closing "
            continue
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        i += 1
    if depth != 0:
        return None
    return text[brace_start + 1:i - 1]


def parse_grammar(text: str) -> GrammarInfo:
    """Parse EBNF grammar text and extract lexical information."""
    info = GrammarInfo()

    # Extract @lexical { ... } section
    lexical_body = _extract_brace_block(text, "@lexical")
    if lexical_body is None:
        raise ValueError("No @lexical section found in grammar")

    # Extract @keywords { ... }
    kw_body = _extract_brace_block(lexical_body, "@keywords")
    if kw_body is not None:
        # Strip comments (-- ...)
        kw_body = re.sub(r'--[^\n]*', '', kw_body)
        # Extract all words
        keywords = re.findall(r'[a-zA-Z_]\w*', kw_body)
        info.keywords = set(keywords)
        info.keyword_to_token = {
            kw: _keyword_to_token_name(kw) for kw in keywords
        }

    # Extract @operators { ... }
    op_body = _extract_brace_block(lexical_body, "@operators")
    if op_body is not None:
        # Extract quoted strings, properly handling -- comments.
        # Match either a comment (--...) or a quoted string ("...").
        # Only capture content of quoted strings.
        operators = re.findall(r'--[^\n]*|"([^"]+)"', op_body)
        # Filter out empty matches (from comment captures)
        operators = [op for op in operators if op]
        # Sort longest-first for greedy matching
        operators.sort(key=lambda x: (-len(x), x))
        info.operators = operators
        info.op_to_token = {op: _op_to_token_name(op) for op in operators}

    return info


def parse_file(filepath: str) -> GrammarInfo:
    """Parse an EBNF grammar file."""
    with open(filepath) as f:
        return parse_grammar(f.read())


def _find_grammar_file() -> str:
    """Find src/language/grammar.ebnf relative to this file's location."""
    # This file is at src/compiler/python/ebnf.py
    # Grammar is at src/language/grammar.ebnf
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(project_root, "src", "language", "grammar.ebnf")


# Module-level grammar info, loaded on first access
_grammar_info: GrammarInfo | None = None


def get_grammar_info() -> GrammarInfo:
    """Get the parsed grammar info, loading it on first access."""
    global _grammar_info
    if _grammar_info is None:
        _grammar_info = parse_file(_find_grammar_file())
    return _grammar_info
