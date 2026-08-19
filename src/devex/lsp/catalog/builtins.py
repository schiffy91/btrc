"""Validated builtin declarations used by language-server features."""

from __future__ import annotations

from src.devex.lsp.catalog.generated import (
    BUILTIN_FUNCTION_SIGNATURES,
    MEMBER_TABLES,
    STDLIB_STATIC_METHODS,
    BuiltinMemberSpec,
)


class BuiltinCatalog:
    """Own immutable indexes over the generated builtin declaration data."""

    def __init__(self) -> None:
        self._members = {name: tuple(members) for name, members in MEMBER_TABLES}
        self._static_methods = {name: tuple(methods) for name, methods in STDLIB_STATIC_METHODS}
        self._functions = {
            name: (return_type, tuple(parameters)) for name, (return_type, parameters) in BUILTIN_FUNCTION_SIGNATURES
        }

    @property
    def type_names(self) -> frozenset[str]:
        return frozenset(self._members)

    @property
    def static_class_names(self) -> tuple[str, ...]:
        return tuple(self._static_methods)

    @staticmethod
    def base_type_name(type_name: str) -> str:
        raw = type_name.strip()
        while raw.endswith(("?", "*")):
            raw = raw[:-1].strip()
        depth = 0
        for index, char in enumerate(raw):
            if char == "<":
                if depth == 0:
                    return raw[:index].strip()
                depth += 1
            elif char == ">":
                depth -= 1
        return raw

    def members(self, type_name: str) -> tuple[BuiltinMemberSpec, ...]:
        return self._members.get(self.base_type_name(type_name), ())

    def member(self, type_name: str, member_name: str) -> BuiltinMemberSpec | None:
        return next((member for member in self.members(type_name) if member.name == member_name), None)

    def hover_markdown(self, type_name: str, member_name: str) -> str | None:
        member = self.member(type_name, member_name)
        if member is None:
            return None
        if member.kind == "field":
            return f"```btrc\n{member.return_type} {member.name}\n```\n{member.doc}"
        parameters = ", ".join(f"{type_name} {name}" for type_name, name in member.params)
        return f"```btrc\n{member.return_type} {member.name}({parameters})\n```\n{member.doc}"

    def signature_parameters(self, type_name: str, method_name: str) -> tuple[tuple[str, str], ...] | None:
        member = self.member(type_name, method_name)
        return None if member is None or member.kind == "field" else member.params

    def static_methods(self, class_name: str) -> tuple[BuiltinMemberSpec, ...] | None:
        return self._static_methods.get(class_name)

    def static_signature(self, class_name: str, method_name: str) -> tuple[tuple[str, str], ...] | None:
        methods = self.static_methods(class_name)
        if methods is None:
            return None
        method = next((candidate for candidate in methods if candidate.name == method_name), None)
        return None if method is None else method.params

    def function_signature(self, name: str) -> tuple[str, tuple[tuple[str, str], ...]] | None:
        return self._functions.get(name)
