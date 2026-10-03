"""Syntax-validated, source-preserving BTRC formatting engine."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from itertools import pairwise, zip_longest
from typing import ClassVar

from src.compiler.python.lexer.lexer import Lexer, LexerError
from src.compiler.python.parser.parser import ParseError, Parser

from .lexing import Lexeme, LexemeKind, LosslessScanner
from .model import StyleConfig


class FormatError(Exception):
    """A source file cannot be formatted without changing its token contract."""

    def __init__(self, message: str, line: int = 1, column: int = 1) -> None:
        self.line = line
        self.column = column
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PhysicalLine:
    number: int
    start: int
    content_end: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class Construct:
    kind: str
    start_index: int
    open_index: int
    close_index: int
    body_open_index: int | None = None


@dataclass(frozen=True, slots=True)
class FunctionSpan:
    construct: Construct
    body_close_index: int
    parent_brace_index: int | None


@dataclass(frozen=True, slots=True)
class StatementSpan:
    start_index: int
    end_index: int


class SourceView:
    """Indexed lossless tokens and balanced structural delimiters."""

    _OPEN_TO_CLOSE: ClassVar[dict[str, str]] = {"(": ")", "[": "]", "{": "}"}
    _CLOSE_TO_OPEN: ClassVar[dict[str, str]] = {close: open_ for open_, close in _OPEN_TO_CLOSE.items()}
    _TYPE_CONTAINERS = frozenset({"class", "interface", "struct", "enum"})
    _CONTROL_WORDS = frozenset({"if", "for", "while", "switch", "catch"})
    # Headers whose body may be a single unbraced statement (C11 6.8.4, 6.8.5):
    # the parenthesized condition of these words, or the bare keyword itself.
    _BODY_CONDITION_WORDS = frozenset({"if", "for", "while"})
    _BODY_KEYWORDS = frozenset({"else", "do"})

    def __init__(self, source: str) -> None:
        self.source = source
        self.lexemes = LosslessScanner(source).scan()
        self._lexeme_starts = tuple(lexeme.start for lexeme in self.lexemes)
        self.significant = tuple(lexeme for lexeme in self.lexemes if not lexeme.is_trivia)
        self.lines = self._physical_lines(source)
        self.pairs = self._delimiter_pairs()
        self._containing_braces = self._index_containing_braces()
        self.class_braces = self._class_braces()
        self._construct_cache: tuple[Construct, ...] | None = None
        self._function_span_cache: tuple[FunctionSpan, ...] | None = None

    @staticmethod
    def _physical_lines(source: str) -> tuple[PhysicalLine, ...]:
        result: list[PhysicalLine] = []
        position = 0
        number = 1
        while position < len(source):
            newline = source.find("\n", position)
            if newline < 0:
                result.append(PhysicalLine(number, position, len(source), len(source), source[position:]))
                position = len(source)
            else:
                content_end = newline - 1 if newline > position and source[newline - 1] == "\r" else newline
                result.append(PhysicalLine(number, position, content_end, newline + 1, source[position:content_end]))
                position = newline + 1
            number += 1
        if not source or source.endswith(("\n", "\r")):
            result.append(PhysicalLine(number, len(source), len(source), len(source), ""))
        return tuple(result)

    def _delimiter_pairs(self) -> dict[int, int]:
        stacks: dict[str, list[int]] = {opening: [] for opening in self._OPEN_TO_CLOSE}
        result: dict[int, int] = {}
        for index, lexeme in enumerate(self.significant):
            if lexeme.kind is not LexemeKind.SYMBOL:
                continue
            if lexeme.text in stacks:
                stacks[lexeme.text].append(index)
                continue
            opening = self._CLOSE_TO_OPEN.get(lexeme.text)
            if opening is None or not stacks[opening]:
                continue
            open_index = stacks[opening].pop()
            result[open_index] = index
            result[index] = open_index
        return result

    def _class_braces(self) -> frozenset[int]:
        result: set[int] = set()
        for index, lexeme in enumerate(self.significant):
            if lexeme.text != "{":
                continue
            cursor = index - 1
            while cursor >= 0 and self.significant[cursor].text not in {";", "{", "}"}:
                if self.significant[cursor].text in self._TYPE_CONTAINERS:
                    result.add(index)
                    break
                cursor -= 1
        return frozenset(result)

    def type_headers(self) -> tuple[StatementSpan, ...]:
        """Each type declaration's header, from its first token to its body's ``{``.

        A header holding ``=`` or parentheses declares a variable or function
        of a ``struct`` type rather than a type body, so it is not one.
        """
        result: list[StatementSpan] = []
        for open_index in sorted(self.class_braces):
            start_index = self._declaration_start(open_index)
            if not any(lexeme.text in {"=", "(", ")"} for lexeme in self.significant[start_index:open_index]):
                result.append(StatementSpan(start_index, open_index))
        return tuple(result)

    def _index_containing_braces(self) -> tuple[int | None, ...]:
        result: list[int | None] = []
        stack: list[int] = []
        for index, lexeme in enumerate(self.significant):
            result.append(stack[-1] if stack else None)
            if lexeme.text == "{":
                stack.append(index)
            elif lexeme.text == "}" and stack:
                stack.pop()
        return tuple(result)

    def constructs(self) -> tuple[Construct, ...]:
        if self._construct_cache is not None:
            return self._construct_cache
        result: list[Construct] = []
        for open_index, open_lexeme in enumerate(self.significant):
            if open_lexeme.text != "(" or open_index not in self.pairs:
                continue
            close_index = self.pairs[open_index]
            previous = self.significant[open_index - 1] if open_index else None
            if previous is not None and previous.text in self._CONTROL_WORDS:
                result.append(Construct("condition", open_index - 1, open_index, close_index))
                continue
            if previous is None or previous.kind is not LexemeKind.WORD:
                continue
            next_index = close_index + 1
            if next_index >= len(self.significant) or self.significant[next_index].text not in {"{", ";"}:
                continue
            start_index = self._declaration_start(open_index - 1)
            if not self._looks_like_signature(start_index, open_index, next_index):
                continue
            body_open = next_index if self.significant[next_index].text == "{" else None
            result.append(Construct("signature", start_index, open_index, close_index, body_open))
        self._construct_cache = tuple(result)
        return self._construct_cache

    def function_spans(self) -> tuple[FunctionSpan, ...]:
        if self._function_span_cache is not None:
            return self._function_span_cache
        spans: list[FunctionSpan] = []
        for construct in self.constructs():
            body_open = construct.body_open_index
            if construct.kind != "signature" or body_open is None or body_open not in self.pairs:
                continue
            spans.append(
                FunctionSpan(
                    construct=construct,
                    body_close_index=self.pairs[body_open],
                    parent_brace_index=self.containing_brace(construct.start_index),
                )
            )
        self._function_span_cache = tuple(spans)
        return self._function_span_cache

    def statement_spans(self) -> tuple[StatementSpan, ...]:
        signature_semicolons = {
            construct.close_index + 1
            for construct in self.constructs()
            if construct.kind == "signature"
            and construct.close_index + 1 < len(self.significant)
            and self.significant[construct.close_index + 1].text == ";"
        }
        result: list[StatementSpan] = []
        paren_depth = 0
        for index, lexeme in enumerate(self.significant):
            if lexeme.text == "(":
                paren_depth += 1
                continue
            if lexeme.text == ")":
                paren_depth = max(paren_depth - 1, 0)
                continue
            if lexeme.text != ";" or paren_depth or index in signature_semicolons:
                continue
            start_index = self._statement_start(index)
            if start_index >= index or self.significant[start_index].text == "import":
                continue
            result.append(StatementSpan(start_index, index))
        return tuple(result)

    def containing_brace(self, significant_index: int) -> int | None:
        return self._containing_braces[significant_index]

    def _declaration_start(self, name_index: int) -> int:
        cursor = name_index - 1
        while cursor >= 0:
            lexeme = self.significant[cursor]
            if lexeme.text in {";", "{", "}"} or lexeme.kind is LexemeKind.PREPROCESSOR:
                return cursor + 1
            if lexeme.text == "import":
                import_line = lexeme.line
                cursor += 1
                while cursor < name_index and self.significant[cursor].line == import_line:
                    cursor += 1
                return cursor
            cursor -= 1
        return 0

    def ends_body_header(self, index: int) -> bool:
        """Whether the significant lexeme at *index* ends a header that a body follows.

        That is ``else``, ``do``, or the ``)`` closing an ``if``/``while``/``for``
        condition. A statement after it is the header's (possibly unbraced) body.
        """
        lexeme = self.significant[index]
        if lexeme.kind is LexemeKind.WORD:
            return lexeme.text in self._BODY_KEYWORDS
        if lexeme.text != ")":
            return False
        open_index = self.pairs.get(index)
        return (
            open_index is not None
            and open_index > 0
            and self.significant[open_index - 1].kind is LexemeKind.WORD
            and self.significant[open_index - 1].text in self._BODY_CONDITION_WORDS
        )

    def _statement_start(self, end_index: int) -> int:
        balances = {")": 0, "]": 0}
        matching_close = {"(": ")", "[": "]"}
        cursor = end_index - 1
        while cursor >= 0:
            lexeme = self.significant[cursor]
            if not any(balances.values()) and self.ends_body_header(cursor):
                # An unbraced body starts after its header, never with it.
                return cursor + 1
            if lexeme.text == "}":
                open_index = self.pairs.get(cursor)
                if open_index is None or not self._brace_is_expression(open_index):
                    return cursor + 1
                cursor = open_index - 1
                continue
            if lexeme.text in balances:
                balances[lexeme.text] += 1
            elif lexeme.text in matching_close:
                close = matching_close[lexeme.text]
                if balances[close]:
                    balances[close] -= 1
            elif not any(balances.values()):
                if lexeme.text in {";", "{"} or lexeme.kind is LexemeKind.PREPROCESSOR:
                    return cursor + 1
                if lexeme.text == "import":
                    import_line = lexeme.line
                    cursor += 1
                    while cursor < end_index and self.significant[cursor].line == import_line:
                        cursor += 1
                    return cursor
            cursor -= 1
        return 0

    def _brace_is_expression(self, open_index: int) -> bool:
        if open_index == 0:
            return False
        return self.significant[open_index - 1].text in {
            "=",
            "(",
            "[",
            "{",
            ",",
            ":",
            "return",
        }

    def _looks_like_signature(self, start_index: int, open_index: int, next_index: int) -> bool:
        prefix = self.significant[start_index:open_index]
        if any(lexeme.text in {"=", ".", "?.", "->", "return", "new"} for lexeme in prefix):
            return False
        if self.significant[next_index].text == "{":
            return True
        parent = self.containing_brace(start_index)
        if parent in self.class_braces:
            return True
        words = [lexeme for lexeme in prefix if lexeme.kind is LexemeKind.WORD]
        return parent is None and len(words) >= 2

    def lexemes_between(self, start: int, end: int) -> tuple[Lexeme, ...]:
        first = bisect_left(self._lexeme_starts, start)
        last = bisect_left(self._lexeme_starts, end)
        return tuple(lexeme for lexeme in self.lexemes[first:last] if lexeme.end <= end)

    def protected_line_starts(self) -> frozenset[int]:
        protected: set[int] = set()
        for lexeme in self.lexemes:
            if lexeme.kind not in {LexemeKind.STRING, LexemeKind.BLOCK_COMMENT, LexemeKind.PREPROCESSOR}:
                continue
            protected.update(range(lexeme.line + 1, lexeme.end_line + 1))
        return frozenset(protected)

    def comments(self) -> tuple[str, ...]:
        return tuple(lexeme.text for lexeme in self.lexemes if lexeme.is_comment)


class BtrcFormatter:
    """Apply one complete style policy while preserving source semantics."""

    _LEADING_CONTINUATION_TOKENS = frozenset(
        {
            ".",
            "?.",
            "&&",
            "||",
            "+",
            "-",
            "*",
            "/",
            "%",
            "==",
            "!=",
            "<",
            ">",
            "<=",
            ">=",
            "?",
            ":",
        }
    )
    _TRAILING_CONTINUATION_TOKENS = _LEADING_CONTINUATION_TOKENS | frozenset(
        {
            "=",
            "+=",
            "-=",
            "*=",
            "/=",
            "%=",
            "&=",
            "|=",
            "^=",
            "<<=",
            ">>=",
        }
    )
    _ALWAYS_BINARY_OPERATORS = frozenset(
        {
            "/",
            "%",
            "=",
            "==",
            "!=",
            "<",
            ">",
            "<=",
            ">=",
            "&&",
            "||",
            "|",
            "^",
            "<<",
            ">>",
            "+=",
            "-=",
            "*=",
            "/=",
            "%=",
            "&=",
            "|=",
            "^=",
            "<<=",
            ">>=",
            "=>",
            "?",
            "??",
            ":",
            ",",
        }
    )
    _AMBIGUOUS_PREFIX_OPERATORS = frozenset({"+", "-", "*", "&"})
    _PREFIX_CONTEXT_TOKENS = _ALWAYS_BINARY_OPERATORS | frozenset(
        {
            "(",
            "[",
            "{",
            "}",
            ";",
            "!",
            "~",
            "++",
            "--",
        }
    )

    def __init__(self, style: StyleConfig | None = None) -> None:
        self.style = style or StyleConfig()

    def format(self, source: str, filename: str = "<memory>") -> str:
        original_tokens = self._validated_tokens(source, filename)
        grouped_source = self._normalize_import_groups(source)
        grouped_tokens = (
            original_tokens if grouped_source == source else self._validated_tokens(grouped_source, filename)
        )
        original_comments = SourceView(source).comments()
        formatted = source
        for _ in range(6):
            previous = formatted
            formatted = self._normalize_import_groups(formatted)
            formatted = self._format_constructs(formatted)
            formatted = self._format_statements(formatted)
            formatted = self._compact_trivial_functions(formatted)
            formatted = self._normalize_blank_lines(formatted)
            formatted = self._normalize_indentation(formatted)
            if formatted == previous:
                break
        else:  # pragma: no cover - a defensive invariant, exercised by fuzzing
            raise FormatError("formatter did not converge")

        if formatted == source:
            return source
        formatted_tokens = self._validated_tokens(formatted, filename)
        if formatted_tokens not in {original_tokens, grouped_tokens}:
            line = self.first_changed_line(source, formatted)
            raise FormatError("formatting would change the compiler token stream", line, 1)
        if SourceView(formatted).comments() != original_comments:
            line = self.first_changed_line(source, formatted)
            raise FormatError("formatting would change comment contents or order", line, 1)
        return formatted

    def _format_statements(self, source: str) -> str:
        if not self.style.single_line_statements:
            return source
        view = SourceView(source)
        edits: list[tuple[int, int, str]] = []
        for statement in view.statement_spans():
            first = view.significant[statement.start_index]
            last = view.significant[statement.end_index]
            start = first.start
            end = last.end
            lexemes = view.lexemes_between(start, end)
            if self._statement_has_protected_layout(lexemes):
                continue
            if not self.style.single_line_data and self._statement_has_structural_data(view, statement):
                continue
            collapsed = self._collapse_lexemes(lexemes, "statement")
            line_prefix = source[source.rfind("\n", 0, start) + 1 : start]
            exceeds_width = (
                self.style.line_width > 0
                and len((line_prefix + collapsed).expandtabs(self.style.indent_width)) > self.style.line_width
            )
            if first.line == last.line and not exceeds_width:
                continue
            replacement = self._render_statement_multiline(view, statement) if exceeds_width else collapsed
            if replacement != source[start:end]:
                edits.append((start, end, replacement))
        return self._apply_edits(source, edits)

    @classmethod
    def _statement_has_protected_layout(cls, lexemes: tuple[Lexeme, ...]) -> bool:
        return cls._splits_adjacent_strings(lexemes) or any(
            lexeme.kind in {LexemeKind.LINE_COMMENT, LexemeKind.BLOCK_COMMENT, LexemeKind.PREPROCESSOR}
            or (lexeme.kind is LexemeKind.STRING and lexeme.line != lexeme.end_line)
            for lexeme in lexemes
        )

    @staticmethod
    def _splits_adjacent_strings(lexemes: tuple[Lexeme, ...]) -> bool:
        """Whether adjacent string-literal pieces sit on separate lines.

        Breaking a long literal into pieces on their own lines is the author's
        layout; collapsing it would undo the reason to concatenate.
        """
        previous = None
        for lexeme in lexemes:
            if lexeme.kind in {LexemeKind.WHITESPACE, LexemeKind.NEWLINE}:
                continue
            if (
                previous is not None
                and previous.kind is LexemeKind.STRING
                and lexeme.kind in {LexemeKind.STRING, LexemeKind.WORD}
                and lexeme.line > previous.end_line
            ):
                return True
            previous = lexeme
        return False

    @staticmethod
    def _statement_has_structural_data(view: SourceView, statement: StatementSpan) -> bool:
        tokens = view.significant
        for index in range(statement.start_index, statement.end_index):
            lexeme = tokens[index]
            if lexeme.text == "{" and view.pairs.get(index, index) < statement.end_index:
                return True
            if lexeme.text not in {"[", "("} or index not in view.pairs:
                continue
            close_index = view.pairs[index]
            if close_index >= statement.end_index or lexeme.line == tokens[close_index].line:
                continue
            previous = tokens[index - 1].text if index > statement.start_index else ""
            if lexeme.text == "[" and previous in {"=", "(", "[", "{", ",", ":", "return"}:
                return True
            if (
                lexeme.text == "("
                and previous in {"=", "return"}
                and any(token.text == "," for token in tokens[index + 1 : close_index])
            ):
                return True
        return False

    def _render_statement_multiline(self, view: SourceView, statement: StatementSpan) -> str:
        tokens = view.significant
        call = self._statement_breakable_call(view, statement)
        if call is not None:
            open_index, close_index = call
            prefix = self._collapse_lexemes(
                view.lexemes_between(tokens[statement.start_index].start, tokens[open_index].start),
                "statement",
            )
            contents = tuple(tokens[open_index + 1 : close_index])
            if any(token.text == "," for token in contents):
                segments = self._split_multiline_segments(contents, "signature")
            else:
                segments = self._split_boolean_segments(contents)
            suffix = self._collapse_lexemes(
                view.lexemes_between(tokens[close_index].end, tokens[statement.end_index].end),
                "statement",
            )
            lines = [prefix + "(" if self.style.opening_paren == "same-line" else prefix]
            if self.style.opening_paren == "next-line":
                lines.append("(")
            lines.extend(self._collapse_lexemes(segment, "statement") for segment in segments if segment)
            closing = ")" + suffix
            if self.style.multiline_closing_paren == "own-line":
                lines.append(closing)
            elif len(lines) == 1:
                lines[0] += closing
            else:
                lines[-1] += closing
            return "\n".join(lines)

        statement_tokens = tuple(tokens[statement.start_index : statement.end_index + 1])
        boolean_segments = self._split_boolean_segments(statement_tokens)
        if len(boolean_segments) > 1:
            return "\n".join(self._collapse_lexemes(segment, "statement") for segment in boolean_segments)
        return self._collapse_lexemes(
            view.lexemes_between(tokens[statement.start_index].start, tokens[statement.end_index].end),
            "statement",
        )

    @staticmethod
    def _statement_breakable_call(view: SourceView, statement: StatementSpan) -> tuple[int, int] | None:
        tokens = view.significant
        candidates: list[tuple[int, int]] = []
        for index in range(statement.start_index, statement.end_index):
            if tokens[index].text != "(" or index not in view.pairs:
                continue
            close_index = view.pairs[index]
            if close_index >= statement.end_index or index == statement.start_index:
                continue
            previous = tokens[index - 1]
            if previous.kind is not LexemeKind.WORD and previous.text not in {")", "]", ">"}:
                continue
            depth = 0
            breakable = False
            for token in tokens[index + 1 : close_index]:
                if token.text in {"(", "["}:
                    depth += 1
                elif token.text in {")", "]"}:
                    depth = max(depth - 1, 0)
                elif depth == 0 and token.text in {",", "&&", "||"}:
                    breakable = True
                    break
            if breakable:
                candidates.append((index, close_index))
        return max(candidates, key=lambda pair: pair[1] - pair[0], default=None)

    @staticmethod
    def _split_boolean_segments(lexemes: tuple[Lexeme, ...]) -> tuple[tuple[Lexeme, ...], ...]:
        result: list[tuple[Lexeme, ...]] = []
        current: list[Lexeme] = []
        paren_depth = 0
        bracket_depth = 0
        for lexeme in lexemes:
            if lexeme.text == "(":
                paren_depth += 1
            elif lexeme.text == ")":
                paren_depth = max(paren_depth - 1, 0)
            elif lexeme.text == "[":
                bracket_depth += 1
            elif lexeme.text == "]":
                bracket_depth = max(bracket_depth - 1, 0)
            if lexeme.text in {"&&", "||"} and paren_depth == bracket_depth == 0 and current:
                result.append(tuple(current))
                current = []
            current.append(lexeme)
        if current:
            result.append(tuple(current))
        return tuple(result)

    def _normalize_import_groups(self, source: str) -> str:
        """Stable-partition the leading import header into two style groups.

        Import order is retained within each category. A header containing
        standalone comment lines is left in place because moving a comment
        independently of its declaration would destroy its ownership.
        """

        if not self.style.group_imports:
            return source

        view = SourceView(source)
        imports: list[tuple[int, int, str]] = []
        depth = 0
        for index, lexeme in enumerate(view.significant):
            if lexeme.text == "{":
                depth += 1
            elif lexeme.text == "}":
                depth = max(depth - 1, 0)
            if depth:
                continue
            category: str | None = None
            if lexeme.kind is LexemeKind.PREPROCESSOR and lexeme.text.lstrip().startswith("#include"):
                category = "external"
            elif lexeme.text == "import":
                following = view.significant[index + 1] if index + 1 < len(view.significant) else None
                category = "stdlib" if following is not None and following.text == "Library" else "external"
            if category is None:
                continue
            start_line = lexeme.line - 1
            end_line = max(lexeme.end_line - 1, start_line)
            imports.append((start_line, end_line, category))

        if len(imports) < 2:
            return source
        first_start = imports[0][0]
        last_end = imports[-1][1]
        lines = [line.text for line in view.lines]
        import_lines = {line for start, end, _ in imports for line in range(start, end + 1)}
        if any(lines[line].strip() and line not in import_lines for line in range(first_start, last_end + 1)):
            return source
        if any(lexeme.is_comment and first_start + 1 <= lexeme.line <= last_end + 1 for lexeme in view.lexemes):
            return source

        units: list[tuple[str, str]] = []
        for start, end, category in imports:
            units.append((category, "\n".join(lines[start : end + 1]).strip("\n")))
        standard = [text for category, text in units if category == "stdlib"]
        external = [text for category, text in units if category == "external"]
        groups = [group for group in (standard, external) if group]
        within = "\n" * (self.style.blank_lines_within_import_groups + 1)
        between = "\n" * (self.style.blank_lines_between_import_groups + 1)
        replacement = between.join(within.join(group) for group in groups)

        start_offset = view.lines[first_start].start
        end_offset = view.lines[last_end].content_end
        return source[:start_offset] + replacement + source[end_offset:]

    @staticmethod
    def first_changed_line(before: str, after: str) -> int:
        for line, (left, right) in enumerate(zip_longest(before.splitlines(), after.splitlines()), 1):
            if left != right:
                return line
        return 1

    @staticmethod
    def _validated_tokens(source: str, filename: str) -> tuple[tuple[object, str], ...]:
        try:
            tokens = Lexer(source, filename).tokenize()
            signature = tuple((token.type, token.value) for token in tokens)
            Parser(list(tokens)).parse()
            return signature
        except (LexerError, ParseError) as error:
            raise FormatError(str(error), getattr(error, "line", 1), getattr(error, "col", 1)) from error

    def _format_constructs(self, source: str) -> str:
        view = SourceView(source)
        edits: list[tuple[int, int, str]] = []
        for construct in view.constructs():
            start = view.significant[construct.start_index].start
            end = view.significant[construct.close_index].end
            lexemes = view.lexemes_between(start, end)
            if any(lexeme.kind is LexemeKind.LINE_COMMENT for lexeme in lexemes) or self._splits_adjacent_strings(
                lexemes
            ):
                continue
            wants_single_line = (
                self.style.single_line_signatures
                if construct.kind == "signature"
                else self.style.single_line_conditions
            )
            collapsed = self._collapse_lexemes(lexemes, construct.kind)
            opening_line = view.significant[construct.open_index].line
            closing_line = view.significant[construct.close_index].line
            explicitly_multiline = opening_line != closing_line
            line_prefix = source[source.rfind("\n", 0, start) + 1 : start]
            exceeds_width = (
                self.style.line_width > 0
                and len(line_prefix.expandtabs(self.style.indent_width) + collapsed) > self.style.line_width
            )

            if wants_single_line and self.style.opening_paren == "same-line" and not exceeds_width:
                replacement = collapsed
            elif explicitly_multiline or exceeds_width or self.style.opening_paren == "next-line":
                replacement = self._render_multiline(lexemes, construct)
            else:
                continue
            if replacement != source[start:end]:
                edits.append((start, end, replacement))
        return self._apply_edits(source, edits)

    def _render_multiline(self, lexemes: tuple[Lexeme, ...], construct: Construct) -> str:
        meaningful = tuple(
            lexeme for lexeme in lexemes if lexeme.kind not in {LexemeKind.WHITESPACE, LexemeKind.NEWLINE}
        )
        open_position = next(index for index, lexeme in enumerate(meaningful) if lexeme.text == "(")
        close_position = (
            len(meaningful) - 1 - next(index for index, lexeme in enumerate(reversed(meaningful)) if lexeme.text == ")")
        )
        header = self._collapse_lexemes(meaningful[:open_position], construct.kind)
        contents = meaningful[open_position + 1 : close_position]
        segments = self._split_multiline_segments(contents, construct.kind)

        attached_open = " (" if construct.kind == "condition" else "("
        lines = [header + attached_open if self.style.opening_paren == "same-line" else header]
        if self.style.opening_paren == "next-line":
            lines.append("(")
        lines.extend(self._collapse_lexemes(segment, construct.kind) for segment in segments if segment)
        if self.style.multiline_closing_paren == "own-line":
            lines.append(")")
        elif len(lines) == 1:
            lines[0] += ")"
        else:
            lines[-1] += ")"
        return "\n".join(lines)

    @staticmethod
    def _split_multiline_segments(lexemes: tuple[Lexeme, ...], kind: str) -> tuple[tuple[Lexeme, ...], ...]:
        if not lexemes:
            return ()
        result: list[tuple[Lexeme, ...]] = []
        current: list[Lexeme] = []
        paren_depth = 0
        bracket_depth = 0
        for lexeme in lexemes:
            text = lexeme.text
            if text == "(":
                paren_depth += 1
            elif text == ")":
                paren_depth -= 1
            elif text == "[":
                bracket_depth += 1
            elif text == "]":
                bracket_depth -= 1
            split_before = kind == "condition" and text in {"&&", "||"} and paren_depth == bracket_depth == 0
            if split_before and current:
                result.append(tuple(current))
                current = []
            current.append(lexeme)
            split_after = kind == "signature" and text == "," and paren_depth == bracket_depth == 0
            if split_after:
                result.append(tuple(current))
                current = []
        if current:
            result.append(tuple(current))
        return tuple(result)

    @staticmethod
    def _collapse_lexemes(lexemes: tuple[Lexeme, ...], construct_kind: str) -> str:
        meaningful = [lexeme for lexeme in lexemes if lexeme.kind not in {LexemeKind.WHITESPACE, LexemeKind.NEWLINE}]
        if not meaningful:
            return ""
        pieces: list[str] = [meaningful[0].text]
        for index, current in enumerate(meaningful[1:], start=1):
            previous = meaningful[index - 1]
            before_previous = meaningful[index - 2] if index > 1 else None
            gap_had_space = previous.end < current.start
            following = meaningful[index + 1] if index + 1 < len(meaningful) else None
            if BtrcFormatter._keeps_declarator_space(
                previous, current, following, gap_had_space
            ) or BtrcFormatter._needs_space(
                before_previous,
                previous,
                current,
                gap_had_space,
                construct_kind,
            ):
                pieces.append(" ")
            pieces.append(current.text)
        return "".join(pieces).strip()

    @staticmethod
    def _keeps_declarator_space(
        previous: Lexeme, current: Lexeme, following: Lexeme | None, gap_had_space: bool
    ) -> bool:
        """Keep a written space in ``int (*cb)(int)``: a C function-pointer
        declarator, which a call such as ``f(*p)`` writes without one."""
        return (
            gap_had_space
            and previous.kind is LexemeKind.WORD
            and current.text == "("
            and following is not None
            and following.text == "*"
        )

    @staticmethod
    def _needs_space(
        before_previous: Lexeme | None,
        previous: Lexeme,
        current: Lexeme,
        gap_had_space: bool,
        construct_kind: str,
    ) -> bool:
        if previous.is_comment or current.is_comment:
            return True
        if (
            previous.kind is LexemeKind.WORD
            and previous.text == "f"
            and current.kind is LexemeKind.STRING
            and not gap_had_space
        ):
            return False
        if current.text in {")", "]", ",", ";", ".", "?.", "->"}:
            return False
        if previous.text in {"(", "[", ".", "?.", "->"}:
            return False
        if current.text == "(":
            if previous.text in SourceView._CONTROL_WORDS or previous.text in {"return", "throw"}:
                return True
            if previous.text in BtrcFormatter._ALWAYS_BINARY_OPERATORS:
                return True
            if previous.text in BtrcFormatter._AMBIGUOUS_PREFIX_OPERATORS:
                return not BtrcFormatter._is_prefix_operator(before_previous)
            if previous.text in {"!", "~", "++", "--"}:
                return False
            return False
        if previous.text == ",":
            return True
        if previous.kind in {
            LexemeKind.WORD,
            LexemeKind.NUMBER,
            LexemeKind.STRING,
            LexemeKind.CHARACTER,
        } and current.kind in {
            LexemeKind.WORD,
            LexemeKind.NUMBER,
            LexemeKind.STRING,
            LexemeKind.CHARACTER,
        }:
            return True
        return gap_had_space

    @staticmethod
    def _is_prefix_operator(before_operator: Lexeme | None) -> bool:
        if before_operator is None:
            return True
        if before_operator.text in BtrcFormatter._PREFIX_CONTEXT_TOKENS:
            return True
        return before_operator.kind is LexemeKind.WORD and before_operator.text in {
            "return",
            "throw",
            "case",
        }

    @classmethod
    def _line_starts_with_continuation(cls, first: Lexeme | None, previous: Lexeme | None) -> bool:
        if first is None or first.text not in cls._LEADING_CONTINUATION_TOKENS:
            return False
        if first.text in cls._AMBIGUOUS_PREFIX_OPERATORS:
            return not cls._is_prefix_operator(previous)
        return True

    @staticmethod
    def _continues_adjacent_strings(
        first: Lexeme | None, previous: Lexeme | None, previous_first: Lexeme | None
    ) -> bool:
        """A line continuing the string-literal pieces the previous line ended with.

        A quoted import may omit its ';', so the path a previous ``import``
        line ends with is never a piece the next line continues.
        """
        return (
            first is not None
            and previous is not None
            and previous.kind is LexemeKind.STRING
            and first.kind in {LexemeKind.STRING, LexemeKind.WORD}
            and not (previous_first is not None and previous_first.text == "import")
        )

    def _compact_trivial_functions(self, source: str) -> str:
        if not self.style.compact_trivial_functions:
            return source
        view = SourceView(source)
        edits: list[tuple[int, int, str]] = []
        for span in view.function_spans():
            construct = span.construct
            body_open = construct.body_open_index
            assert body_open is not None
            body_lexemes = view.significant[body_open + 1 : span.body_close_index]
            if any(lexeme.text in {"{", "}"} for lexeme in body_lexemes):
                continue
            semicolons = sum(lexeme.text == ";" for lexeme in body_lexemes)
            if body_lexemes and semicolons != 1:
                continue
            start = view.significant[construct.start_index].start
            end = view.significant[span.body_close_index].end
            # Comments, directives and string pieces the author split across
            # lines keep the function's layout.
            if self._statement_has_protected_layout(tuple(view.lexemes_between(start, end))):
                continue
            header_end = view.significant[construct.close_index].end
            header = self._collapse_lexemes(view.lexemes_between(start, header_end), "signature")
            body_start = view.significant[body_open].end
            body_end = view.significant[span.body_close_index].start
            body = self._collapse_lexemes(view.lexemes_between(body_start, body_end), "body")
            replacement = f"{header} {{ {body} }}" if body else f"{header} {{}}"
            line_prefix = source[source.rfind("\n", 0, start) + 1 : start]
            if (
                self.style.line_width
                and len((line_prefix + replacement).expandtabs(self.style.indent_width)) > self.style.line_width
            ):
                continue
            if replacement != source[start:end]:
                edits.append((start, end, replacement))
        return self._apply_edits(source, edits)

    def _normalize_blank_lines(self, source: str) -> str:
        view = SourceView(source)
        lines = [line.text for line in view.lines]
        gaps: dict[tuple[int, int], int] = {}

        self._collect_import_gaps(view, gaps)
        self._collect_function_gaps(view, gaps)
        self._collect_class_gaps(view, gaps)
        self._collect_field_gaps(view, gaps)

        for (left, right), count in sorted(gaps.items(), reverse=True):
            if right <= left or any(lines[index].strip() for index in range(left + 1, right)):
                continue
            lines[left + 1 : right] = [""] * count
        had_final_newline = source.endswith("\n")
        rendered = "\n".join(lines)
        if had_final_newline and not rendered.endswith("\n"):
            rendered += "\n"
        if not had_final_newline:
            rendered = rendered.rstrip("\n")
        return rendered

    def _collect_import_gaps(self, view: SourceView, gaps: dict[tuple[int, int], int]) -> None:
        depth = 0
        imports: list[tuple[int, str]] = []
        for lexeme in view.significant:
            if lexeme.text == "{":
                depth += 1
            elif lexeme.text == "}":
                depth = max(depth - 1, 0)
            if depth:
                continue
            category: str | None = None
            if lexeme.kind is LexemeKind.PREPROCESSOR and lexeme.text.lstrip().startswith("#include"):
                category = "external"
            elif lexeme.text == "import":
                following = next(
                    (candidate for candidate in view.significant if candidate.start >= lexeme.end),
                    None,
                )
                category = "stdlib" if following is not None and following.text == "Library" else "external"
            if category is not None and (not imports or imports[-1][0] != lexeme.line - 1):
                imports.append((lexeme.line - 1, category))
        for (left, left_category), (right, right_category) in pairwise(imports):
            count = (
                self.style.blank_lines_within_import_groups
                if left_category == right_category
                else self.style.blank_lines_between_import_groups
            )
            gaps[(left, right)] = count

    def _collect_function_gaps(self, view: SourceView, gaps: dict[tuple[int, int], int]) -> None:
        by_parent: dict[int | None, list[FunctionSpan]] = {}
        for span in view.function_spans():
            by_parent.setdefault(span.parent_brace_index, []).append(span)
        for spans in by_parent.values():
            spans.sort(key=lambda span: span.construct.start_index)
            for left, right in pairwise(spans):
                left_line = view.significant[left.body_close_index].line - 1
                right_line = view.significant[right.construct.start_index].line - 1
                gaps[(left_line, right_line)] = self.style.blank_lines_between_functions

    def _collect_class_gaps(self, view: SourceView, gaps: dict[tuple[int, int], int]) -> None:
        for open_index in view.class_braces:
            close_index = view.pairs.get(open_index)
            if close_index is None:
                continue
            open_line = view.significant[open_index].line - 1
            close_line = view.significant[close_index].line - 1
            first = next(
                (lexeme for lexeme in view.significant[open_index + 1 : close_index] if lexeme.line - 1 > open_line),
                None,
            )
            last = next(
                (
                    lexeme
                    for lexeme in reversed(view.significant[open_index + 1 : close_index])
                    if lexeme.line - 1 < close_line
                ),
                None,
            )
            if first is not None:
                gaps[(open_line, first.line - 1)] = self.style.blank_lines_after_class_opening
            if last is not None:
                gaps[(last.line - 1, close_line)] = self.style.blank_lines_before_class_closing

    def _collect_field_gaps(self, view: SourceView, gaps: dict[tuple[int, int], int]) -> None:
        signature_semicolons = {
            construct.close_index + 1
            for construct in view.constructs()
            if construct.kind == "signature"
            and construct.close_index + 1 < len(view.significant)
            and view.significant[construct.close_index + 1].text == ";"
        }
        for class_open in view.class_braces:
            class_close = view.pairs.get(class_open)
            if class_close is None:
                continue
            fields: list[int] = []
            nested_braces = 0
            for index in range(class_open + 1, class_close):
                text = view.significant[index].text
                if text == "{":
                    nested_braces += 1
                elif text == "}":
                    nested_braces = max(nested_braces - 1, 0)
                elif text == ";" and nested_braces == 0 and index not in signature_semicolons:
                    fields.append(index)
            for left, right in pairwise(fields):
                gaps[(view.significant[left].line - 1, view.significant[right].line - 1)] = (
                    self.style.blank_lines_between_fields
                )

    def _normalize_indentation(self, source: str) -> str:
        view = SourceView(source)
        protected = view.protected_line_starts()
        tokens_by_line: dict[int, list[Lexeme]] = {}
        for lexeme in view.significant:
            tokens_by_line.setdefault(lexeme.line, []).append(lexeme)

        last_index_by_line: dict[int, int] = {}
        index_of: dict[int, int] = {}
        for index, lexeme in enumerate(view.significant):
            last_index_by_line[lexeme.line] = index
            index_of[id(lexeme)] = index

        # A wrapped type header: every line after the keyword's continues it,
        # except one that opens the body, and the body nests one level in from
        # the keyword's line however the header wraps.
        type_header_continuations: dict[int, bool] = {}
        type_body_braces: set[int] = set()
        for header in view.type_headers():
            type_body_braces.add(header.end_index)
            header_line = view.significant[header.start_index].line
            for index in range(header.start_index, header.end_index + 1):
                lexeme = view.significant[index]
                if lexeme.line != header_line and lexeme.line not in type_header_continuations:
                    type_header_continuations[lexeme.line] = index != header.end_index

        brace_depth = 0
        paren_depth = 0
        previous_token: Lexeme | None = None
        # Unbraced bodies indent one level past their header. ``body_extra`` is
        # the extra indentation of the current statement; ``header_extra`` is
        # set while the previous line ended a header (``if (...)``, ``else``,
        # ``do``); ``pending_ifs`` holds the extra of each unbraced ``if`` that
        # a later ``else`` may still bind to. Each brace saves and restores them.
        # ``pending_dos`` holds, for each ``do`` whose closing ``while`` is still
        # to come, its extra and how many ifs were pending at the ``do``: the
        # ifs opened inside its body close with it. ``line_extra`` is the
        # current line's extra, plus one on a continuation line outside
        # parentheses, which is what a header or '{' on that line nests past;
        # a brace frame keeps it with the ``body_extra`` to restore.
        body_extra = 0
        header_extra: int | None = None
        pending_ifs: list[int] = []
        pending_dos: list[tuple[int, int]] = []
        brace_frames: list[tuple[int, int, list[int], list[tuple[int, int]]]] = []
        previous_first: Lexeme | None = None
        rendered: list[str] = []
        for line in view.lines:
            text = line.text
            line_tokens = tokens_by_line.get(line.number, [])
            line_extra = 0
            if line.number in protected:
                rendered.append(text)
            elif not text.strip():
                rendered.append("")
            else:
                first_token = line_tokens[0] if line_tokens else None
                first = first_token.text if first_token is not None else ""
                if line_tokens and line_tokens[0].kind is LexemeKind.PREPROCESSOR:
                    level = 0
                else:
                    continued = (
                        (paren_depth > 0 and first not in {")", "]"})
                        or self._line_starts_with_continuation(first_token, previous_token)
                        or (previous_token is not None and previous_token.text in self._TRAILING_CONTINUATION_TOKENS)
                        or self._continues_adjacent_strings(first_token, previous_token, previous_first)
                    )
                    continued = type_header_continuations.get(line.number, continued)
                    if continued or first == "}" or (paren_depth > 0 and first in {")", "]"}):
                        # A closing ')' or ']' line stays with its statement.
                        pass
                    elif header_extra is not None:
                        body_extra = header_extra + (0 if first == "{" else 1)
                    elif first == "else":
                        # The nearest if still open for an else.
                        if pending_ifs:
                            body_extra = pending_ifs.pop()
                    elif first == "while" and pending_dos:
                        # A do-while's closing ``while`` aligns with its ``do``;
                        # the ifs enclosing that do stay open for an else.
                        body_extra, open_ifs = pending_dos.pop()
                        del pending_ifs[open_ifs:]
                    else:
                        body_extra = 0
                        pending_ifs.clear()
                    outer_extra = sum(frame[0] for frame in brace_frames)
                    level = brace_depth - (1 if first == "}" else 0) + outer_extra
                    if first != "}":
                        level += body_extra
                    if continued:
                        level += 1
                    if continued and paren_depth == 0:
                        # A header or '{' on a continuation line outside any
                        # parentheses (after ``case X:``, a lambda after ``=``)
                        # nests its body past the continuation; inside
                        # parentheses every body line is already continued.
                        line_extra += 1
                rendered.append(self.style.indentation(max(level, 0)) + text.lstrip(" \t").rstrip(" \t"))

            line_extra += body_extra
            for position, lexeme in enumerate(line_tokens):
                index = index_of[id(lexeme)]
                if lexeme.kind is LexemeKind.WORD:
                    if lexeme.text == "do":
                        pending_dos.append((line_extra, len(pending_ifs)))
                    elif position == 0:
                        # A line-first else or while was bound above.
                        continue
                    elif lexeme.text == "else" and pending_ifs:
                        pending_ifs.pop()
                    elif lexeme.text == "while" and pending_dos and view.significant[index - 1].text in {";", "}"}:
                        # A while right after a statement closes the open do.
                        del pending_ifs[pending_dos.pop()[1] :]
                    continue
                if lexeme.kind is not LexemeKind.SYMBOL:
                    continue
                if lexeme.text == "{":
                    brace_depth += 1
                    # A type body nests past its header's first line, not past
                    # the continuation line its '{' may close the header on.
                    frame_extra = body_extra if index in type_body_braces else line_extra
                    brace_frames.append((frame_extra, body_extra, pending_ifs, pending_dos))
                    body_extra = line_extra = 0
                    pending_ifs = []
                    pending_dos = []
                elif lexeme.text == "}":
                    brace_depth = max(brace_depth - 1, 0)
                    if brace_frames:
                        line_extra, body_extra, pending_ifs, pending_dos = brace_frames.pop()
                elif lexeme.text in {"(", "["}:
                    paren_depth += 1
                elif lexeme.text in {")", "]"}:
                    paren_depth = max(paren_depth - 1, 0)
                    # An if may take an else from its condition's ')' on, so a
                    # body on the header's line, or a braced one, keeps it open.
                    if (
                        lexeme.text == ")"
                        and view.ends_body_header(index)
                        and view.significant[view.pairs[index] - 1].text == "if"
                    ):
                        pending_ifs.append(line_extra)
            if line_tokens and line_tokens[0].kind is not LexemeKind.PREPROCESSOR:
                last_index = last_index_by_line[line.number]
                header_extra = line_extra if view.ends_body_header(last_index) else None
            if line_tokens:
                previous_token = line_tokens[-1]
                previous_first = line_tokens[0]

        had_final_newline = source.endswith("\n")
        result = "\n".join(rendered)
        if had_final_newline and not result.endswith("\n"):
            result += "\n"
        if not had_final_newline:
            result = result.rstrip("\n")
        return result

    @staticmethod
    def _apply_edits(source: str, edits: list[tuple[int, int, str]]) -> str:
        if not edits:
            return source
        edits.sort(key=lambda edit: (edit[0], edit[1]), reverse=True)
        last_start = len(source)
        result = source
        for start, end, replacement in edits:
            if end > last_start:
                continue
            result = result[:start] + replacement + result[end:]
            last_start = start
        return result
