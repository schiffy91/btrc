"""Parsing helpers for source directives that mutate the C macro namespace."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HSPACE = r"[ \t\f\v\r]"
_DIRECTIVE = re.compile(rf"^{_HSPACE}*#{_HSPACE}*(define|undef)\b(.*)$", re.DOTALL)
_NAME = re.compile(rf"^{_HSPACE}+([A-Za-z_][A-Za-z0-9_]*)(.*)$", re.DOTALL)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LINE_SPLICE = re.compile(r"(?:\\|\?\?/)\r?\n")
_TOKEN_PASTE_SPELLINGS = ("##", "%:%:", "??=??=")


@dataclass(frozen=True)
class SourceSymbolDirective:
    operation: str
    name: str
    parameters: frozenset[str] = frozenset()
    replacement: str = ""
    parameter_order: tuple[str, ...] = ()
    function_like: bool = False


def source_symbol_directive(text: str) -> SourceSymbolDirective | None:
    """Parse the symbol-bearing portion of a single-line define/undef."""
    text = _normalize_preprocessing(text)
    directive_match = _DIRECTIVE.fullmatch(text)
    if directive_match is None:
        return None
    operation, payload = directive_match.groups()
    name_match = _NAME.fullmatch(payload)
    if name_match is None:
        return None
    name, suffix = name_match.groups()
    if operation == "undef":
        return SourceSymbolDirective(operation, name)
    if not suffix.startswith("("):
        return SourceSymbolDirective(operation, name, replacement=suffix.lstrip())
    close = suffix.find(")")
    if close < 0:
        return SourceSymbolDirective(operation, name, replacement=suffix)
    parameter_text = suffix[1:close].strip()
    parameters = () if not parameter_text else tuple(item.strip() for item in parameter_text.split(","))
    parameter_order = tuple(parameter for parameter in parameters if _IDENTIFIER.fullmatch(parameter))
    return SourceSymbolDirective(
        operation,
        name,
        parameters=frozenset(parameter_order),
        replacement=suffix[close + 1 :].lstrip(),
        parameter_order=parameter_order,
        function_like=True,
    )


def _normalize_preprocessing(text: str) -> str:
    """Apply translation phases that affect directive token boundaries."""
    text = _LINE_SPLICE.sub("", text)
    normalized: list[str] = []
    index = 0
    while index < len(text):
        if text[index] in {'"', "'"}:
            end = _skip_quoted(text, index, text[index])
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


def source_macro_name(text: str) -> str | None:
    directive = source_symbol_directive(text)
    if directive is None or directive.operation != "define":
        return None
    return directive.name


def source_undef_name(text: str) -> str | None:
    directive = source_symbol_directive(text)
    if directive is None or directive.operation != "undef":
        return None
    return directive.name


def source_macro_replacement_identifiers(
    directive: SourceSymbolDirective,
) -> tuple[str, ...]:
    """Return code identifiers, excluding parameters and literal/comment text."""
    if directive.operation != "define":
        return ()
    identifiers: list[str] = []
    text = directive.replacement
    index = 0
    while index < len(text):
        value = text[index]
        if value in {'"', "'"}:
            index = _skip_quoted(text, index, value)
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
            if identifier not in directive.parameters and identifier not in identifiers:
                identifiers.append(identifier)
            index = end
            continue
        index += 1
    return tuple(identifiers)


def source_macro_replacement_member_identifiers(
    directive: SourceSymbolDirective,
) -> tuple[str, ...]:
    """Return replacement identifiers used after ``.`` or ``->``."""
    if directive.operation != "define":
        return ()
    members: list[str] = []
    text = directive.replacement
    index = 0
    while index < len(text):
        value = text[index]
        if value in {'"', "'"}:
            index = _skip_quoted(text, index, value)
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
            if member_access and identifier not in directive.parameters and identifier not in members:
                members.append(identifier)
            index = end
            continue
        index += 1
    return tuple(members)


def source_macro_uses_token_paste(directive: SourceSymbolDirective) -> bool:
    """Whether executable replacement text contains a C token-paste operator."""
    if directive.operation != "define":
        return False
    text = directive.replacement
    index = 0
    while index < len(text):
        value = text[index]
        if value in {'"', "'"}:
            index = _skip_quoted(text, index, value)
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


def source_macro_single_call(
    directive: SourceSymbolDirective,
) -> tuple[str, tuple[str, ...]] | None:
    """Return an exact single-call replacement without interpreting C.

    This intentionally recognizes only ``callee(arg, ...)`` with optional
    redundant outer parentheses.  Semantic consumers can model that narrow
    shape without pretending arbitrary preprocessor text is a typed AST.
    """
    if not directive.function_like:
        return None
    text = directive.replacement.split("//", 1)[0].strip()
    text = _strip_outer_parentheses(text)
    match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", text)
    if match is None:
        return None
    callee = match.group(1)
    index = match.end()
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] != "(":
        return None
    close = _matching_parenthesis(text, index)
    if close is None or text[close + 1 :].strip():
        return None
    return callee, tuple(_split_call_arguments(text[index + 1 : close]))


def source_macro_unwrapped_identifier(text: str) -> str | None:
    """Return one identifier through redundant grouping parentheses."""
    text = _strip_outer_parentheses(text.strip())
    return text if _IDENTIFIER.fullmatch(text) else None


def _strip_outer_parentheses(text: str) -> str:
    while text.startswith("("):
        close = _matching_parenthesis(text, 0)
        if close is None or text[close + 1 :].strip():
            break
        text = text[1:close].strip()
    return text


def _matching_parenthesis(text: str, start: int) -> int | None:
    depth = 0
    index = start
    while index < len(text):
        value = text[index]
        if value in {'"', "'"}:
            index = _skip_quoted(text, index, value)
            continue
        if value == "(":
            depth += 1
        elif value == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _split_call_arguments(text: str) -> list[str]:
    if not text.strip():
        return []
    arguments: list[str] = []
    start = 0
    depth = 0
    index = 0
    while index < len(text):
        value = text[index]
        if value in {'"', "'"}:
            index = _skip_quoted(text, index, value)
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


__all__ = [
    "SourceSymbolDirective",
    "source_macro_name",
    "source_macro_replacement_identifiers",
    "source_macro_replacement_member_identifiers",
    "source_macro_single_call",
    "source_macro_unwrapped_identifier",
    "source_macro_uses_token_paste",
    "source_symbol_directive",
    "source_undef_name",
]
