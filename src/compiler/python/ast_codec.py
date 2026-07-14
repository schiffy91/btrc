"""Allowlisted conversion between compiler AST dataclasses and JSON values."""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from . import ast_nodes

_AST_TYPES = {
    value.__name__: value
    for value in vars(ast_nodes).values()
    if isinstance(value, type) and value.__module__ == ast_nodes.__name__ and is_dataclass(value)
}


def encode_ast(value):
    """Convert an AST value into JSON-compatible primitives."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [encode_ast(item) for item in value]
    cls = type(value)
    if _AST_TYPES.get(cls.__name__) is not cls:
        raise TypeError(f"unsupported cached AST value: {cls.__name__}")
    return {
        "fields": {
            field.name: encode_ast(None if field.name == "source_file" else getattr(value, field.name))
            for field in fields(value)
        },
        "type": cls.__name__,
    }


def decode_ast(value):
    """Reconstruct only known AST dataclasses from JSON-compatible values."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [decode_ast(item) for item in value]
    if not isinstance(value, dict) or set(value) != {"fields", "type"}:
        raise ValueError("invalid cached AST node")
    node_type = value["type"]
    cls = _AST_TYPES.get(node_type) if isinstance(node_type, str) else None
    field_values = value["fields"]
    if cls is None or not isinstance(field_values, dict):
        raise ValueError("unknown cached AST node")
    expected_fields = {field.name for field in fields(cls)}
    if set(field_values) != expected_fields:
        raise ValueError("cached AST fields do not match the current schema")
    return cls(**{name: decode_ast(item) for name, item in field_values.items()})
