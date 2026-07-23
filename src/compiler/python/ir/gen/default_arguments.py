"""Scoped state and semantic resolution for synthesized default arguments."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeVar

from ...ast_nodes import TypeExpr
from ...type_identity import TypeIdentity

_Result = TypeVar("_Result")
_LineMap = Callable[[int], tuple[str, int] | None]


@dataclass(frozen=True)
class _DeclarationScope:
    function_name: str
    source_file: str
    line_map: _LineMap | None


@dataclass(frozen=True)
class _DefaultArgumentState:
    substitutions: Mapping[str, TypeExpr] | None = None
    declaration: _DeclarationScope | None = None


_EMPTY_STATE = _DefaultArgumentState()


class DefaultArgumentLoweringContext:
    """Own default-only substitutions and declaration provenance for one IR run.

    The instance-owned context variable preserves nested and asynchronous
    lowering scopes without sharing mutable state between ``IRLowerer``
    instances.
    """

    def __init__(self, type_identity: TypeIdentity | None = None) -> None:
        self._type_identity = type_identity if type_identity is not None else TypeIdentity()
        self._state = ContextVar(
            f"btrc_default_arguments_{id(self)}",
            default=_EMPTY_STATE,
        )

    @contextmanager
    def scope(
        self,
        param,
        is_default: bool = True,
        *,
        function_name: str | None = None,
        source_file: str = "",
        line_map: _LineMap | None = None,
    ) -> Iterator[None]:
        """Activate one nested argument/declaration lowering scope."""

        current = self._state.get()
        substitutions = current.substitutions
        default_type_map = getattr(param, "default_type_map", None) if is_default and param is not None else None
        if default_type_map:
            substitutions = MappingProxyType(dict(default_type_map))

        declaration = current.declaration
        if function_name is not None:
            declaration = _DeclarationScope(
                function_name=function_name,
                source_file=source_file,
                line_map=line_map,
            )

        token = self._state.set(
            _DefaultArgumentState(
                substitutions=substitutions,
                declaration=declaration,
            )
        )
        try:
            yield
        finally:
            self._state.reset(token)

    def evaluate(
        self,
        param,
        is_default: bool,
        operation: Callable[[], _Result],
    ) -> _Result:
        """Run an operation under the parameter's default substitutions."""

        with self.scope(param, is_default):
            return operation()

    def lower_argument(
        self,
        param,
        node,
        lower: Callable[[object], _Result],
        *,
        is_default: bool = False,
    ) -> _Result:
        """Lower one explicit or synthesized argument in its semantic scope."""

        return self.evaluate(
            param,
            is_default,
            lambda: lower(node),
        )

    def argument_type(
        self,
        param,
        node,
        type_of: Callable[[object], TypeExpr | None],
        *,
        is_default: bool = False,
    ) -> TypeExpr | None:
        """Resolve an argument's analyzed type under default substitutions."""

        return self.evaluate(
            param,
            is_default,
            lambda: self.resolve_type(type_of(node)),
        )

    def resolve_type(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        """Apply the active default parameter's concrete type substitutions."""

        substitutions = self._state.get().substitutions
        if not substitutions or type_expr is None:
            return type_expr
        return self._type_identity.substitute(type_expr, substitutions)

    def predefined_identifier(self, node) -> str | None:
        """Freeze a predefined identifier at its declaration site."""

        declaration = self._state.get().declaration
        if declaration is None:
            return None

        source_file = declaration.source_file
        source_line = node.line or 0
        if declaration.line_map is not None:
            mapped = declaration.line_map(source_line)
            if mapped is not None:
                mapped_file, source_line = mapped
                source_file = source_file or mapped_file

        if node.name == "__func__":
            return json.dumps(declaration.function_name)
        if node.name == "__LINE__":
            return str(source_line)
        if node.name == "__FILE__" and source_file:
            return json.dumps(source_file)
        return None


__all__ = ["DefaultArgumentLoweringContext"]
