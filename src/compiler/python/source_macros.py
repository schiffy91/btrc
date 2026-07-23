"""Owned syntax and active-namespace model for source C macros."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

_HSPACE = r"[ \t\f\v\r]"
_DIRECTIVE = re.compile(rf"^{_HSPACE}*#{_HSPACE}*(define|undef)\b(.*)$", re.DOTALL)
_NAME = re.compile(rf"^{_HSPACE}+([A-Za-z_][A-Za-z0-9_]*)(.*)$", re.DOTALL)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LINE_SPLICE = re.compile(r"(?:\\|\?\?/)\r?\n")
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
        directive_match = _DIRECTIVE.fullmatch(text)
        if directive_match is None:
            return None
        operation, payload = directive_match.groups()
        name_match = _NAME.fullmatch(payload)
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
            elif not _IDENTIFIER.fullmatch(parameter) or parameter in parameter_order:
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
                if member_access and identifier not in self.parameters and identifier not in members:
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
        match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", text)
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
        return callee, tuple(self._split_call_arguments(text[index + 1 : close]))

    @classmethod
    def unwrapped_identifier(cls, text: str) -> str | None:
        """Return one identifier through redundant grouping parentheses."""
        value = cls.unwrap_identifier_groups(text, require_identifier=False)
        return value if _IDENTIFIER.fullmatch(value) else None

    @classmethod
    def unwrap_identifier_groups(cls, text: str, *, require_identifier: bool = True) -> str:
        text = text.strip()
        while text.startswith("("):
            close = cls._matching_parenthesis(text, 0)
            if close is None or text[close + 1 :].strip():
                break
            text = text[1:close].strip()
        if require_identifier and not _IDENTIFIER.fullmatch(text):
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


class SourceMacroNamespace:
    """Immutable declared-name and final-active-definition namespace."""

    def __init__(
        self,
        declared_names=(),
        definitions: Mapping[str, SourceSymbolDirective] | None = None,
    ) -> None:
        self._declared_names = frozenset(declared_names)
        self._definitions = MappingProxyType(dict(definitions or {}))

    @classmethod
    def empty(cls) -> SourceMacroNamespace:
        return cls()

    @property
    def declared_names(self) -> frozenset[str]:
        return self._declared_names

    @property
    def definitions(self) -> Mapping[str, SourceSymbolDirective]:
        return self._definitions

    def declared(self, name: str) -> bool:
        return name in self._declared_names

    def active(self, name: str) -> SourceSymbolDirective | None:
        return self._definitions.get(name)

    def expands_to_any(self, name: str, identifiers: frozenset[str]) -> bool:
        """Whether an active macro transitively references a target identifier."""
        pending = [name]
        visiting: set[str] = set()
        while pending:
            current = pending.pop()
            if current in visiting:
                continue
            visiting.add(current)
            directive = self.active(current)
            if directive is None:
                continue
            for identifier in directive.replacement_identifiers():
                if identifier in identifiers:
                    return True
                if identifier not in visiting and self.active(identifier) is not None:
                    pending.append(identifier)
        return False


__all__ = ["SourceMacroNamespace", "SourceSymbolDirective"]
