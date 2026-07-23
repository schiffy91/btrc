"""Owned allowlisted conversion between compiler ASTs and JSON values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from types import MappingProxyType

from . import ast_nodes


class AstJsonCodec:
    """Own the immutable AST schema accepted by one persistent cache."""

    def __init__(self, node_types: Mapping[str, type] | None = None) -> None:
        allowed = (
            {
                value.__name__: value
                for value in vars(ast_nodes).values()
                if isinstance(value, type) and value.__module__ == ast_nodes.__name__ and is_dataclass(value)
            }
            if node_types is None
            else node_types
        )
        self._node_types = MappingProxyType(dict(allowed))

    def encode(self, value):
        """Convert an AST value into JSON-compatible primitives."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, list):
            return [self.encode(item) for item in value]
        cls = type(value)
        if self._node_types.get(cls.__name__) is not cls:
            raise TypeError(f"unsupported cached AST value: {cls.__name__}")
        return {
            "fields": {
                field.name: self.encode(None if field.name == "source_file" else getattr(value, field.name))
                for field in fields(value)
            },
            "type": cls.__name__,
        }

    def decode(self, value):
        """Reconstruct only known AST dataclasses from JSON values."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, list):
            return [self.decode(item) for item in value]
        if not isinstance(value, dict) or set(value) != {"fields", "type"}:
            raise ValueError("invalid cached AST node")
        node_type = value["type"]
        cls = self._node_types.get(node_type) if isinstance(node_type, str) else None
        field_values = value["fields"]
        if cls is None or not isinstance(field_values, dict):
            raise ValueError("unknown cached AST node")
        expected_fields = {field.name for field in fields(cls)}
        if set(field_values) != expected_fields:
            raise ValueError("cached AST fields do not match the current schema")
        return cls(**{name: self.decode(item) for name, item in field_values.items()})


__all__ = ["AstJsonCodec"]
