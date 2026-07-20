"""Conversions between compiler code-point columns and LSP UTF-16 offsets."""

from __future__ import annotations

from lsprotocol import types as lsp


def line_text(source: str, line: int) -> str:
    """Return one 0-based logical line without its CRLF terminator."""
    lines = source.split("\n")
    if not 0 <= line < len(lines):
        return ""
    return lines[line][:-1] if lines[line].endswith("\r") else lines[line]


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def codepoint_to_utf16(text: str, offset: int) -> int:
    offset = min(max(0, offset), len(text))
    return utf16_length(text[:offset])


def utf16_to_codepoint(text: str, offset: int) -> int:
    """Map a UTF-16 offset to a code-point boundary, clamping invalid input."""
    if offset <= 0:
        return 0
    units = 0
    for index, char in enumerate(text):
        width = 2 if ord(char) > 0xFFFF else 1
        if units + width > offset:
            return index
        units += width
        if units == offset:
            return index + 1
    return len(text)


def source_position(source: str, position: lsp.Position) -> lsp.Position:
    """Convert a client UTF-16 position to an internal code-point position."""
    line = min(max(0, position.line), max(0, source.count("\n")))
    character = utf16_to_codepoint(line_text(source, line), position.character)
    return lsp.Position(line=line, character=character)


def protocol_position(source: str, line: int, col: int) -> lsp.Position:
    """Convert a 1-based compiler position to a 0-based LSP UTF-16 position."""
    line0 = max(0, line - 1)
    character = codepoint_to_utf16(line_text(source, line0), max(0, col - 1))
    return lsp.Position(line=line0, character=character)


def protocol_range(source: str, line: int, col: int, length: int = 0) -> lsp.Range:
    """Return an LSP range for a single-line compiler span."""
    start = protocol_position(source, line, col)
    text = line_text(source, start.line)
    end_codepoint = max(0, col - 1) + max(0, length)
    end = lsp.Position(
        line=start.line,
        character=codepoint_to_utf16(text, end_codepoint),
    )
    return lsp.Range(start=start, end=end)
