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

    def _statement_start(self, end_index: int) -> int:
        balances = {")": 0, "]": 0}
        matching_close = {"(": ")", "[": "]"}
        cursor = end_index - 1
        while cursor >= 0:
            lexeme = self.significant[cursor]
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

    @staticmethod
    def _statement_has_protected_layout(lexemes: tuple[Lexeme, ...]) -> bool:
        return any(
            lexeme.kind in {LexemeKind.LINE_COMMENT, LexemeKind.BLOCK_COMMENT, LexemeKind.PREPROCESSOR}
            or (lexeme.kind is LexemeKind.STRING and lexeme.line != lexeme.end_line)
            for lexeme in lexemes
        )

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
                category = "stdlib" if following is not None and following.text == "std" else "external"
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
            if any(lexeme.kind is LexemeKind.LINE_COMMENT for lexeme in lexemes):
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
            if BtrcFormatter._needs_space(
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
            protected = view.lexemes_between(start, end)
            if any(
                lexeme.kind in {LexemeKind.LINE_COMMENT, LexemeKind.BLOCK_COMMENT, LexemeKind.PREPROCESSOR}
                for lexeme in protected
            ):
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
                category = "stdlib" if following is not None and following.text == "std" else "external"
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

        brace_depth = 0
        paren_depth = 0
        previous_token: Lexeme | None = None
        rendered: list[str] = []
        for line in view.lines:
            text = line.text
            line_tokens = tokens_by_line.get(line.number, [])
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
                    level = brace_depth - (1 if first == "}" else 0)
                    if (
                        (paren_depth > 0 and first not in {")", "]"})
                        or self._line_starts_with_continuation(first_token, previous_token)
                        or (previous_token is not None and previous_token.text in self._TRAILING_CONTINUATION_TOKENS)
                    ):
                        level += 1
                rendered.append(self.style.indentation(max(level, 0)) + text.lstrip(" \t").rstrip(" \t"))

            for lexeme in line_tokens:
                if lexeme.kind is not LexemeKind.SYMBOL:
                    continue
                if lexeme.text == "{":
                    brace_depth += 1
                elif lexeme.text == "}":
                    brace_depth = max(brace_depth - 1, 0)
                elif lexeme.text in {"(", "["}:
                    paren_depth += 1
                elif lexeme.text in {")", "]"}:
                    paren_depth = max(paren_depth - 1, 0)
            if line_tokens:
                previous_token = line_tokens[-1]

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
