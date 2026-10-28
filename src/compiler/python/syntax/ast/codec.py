"""Owned allowlisted conversion between compiler ASTs and JSON values."""

from __future__ import annotations

import struct
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from types import MappingProxyType
from typing import Any

import src.compiler.python.syntax.ast.generated as generated_ast


class AstCanonicalRenderer:
    """Render Python AST values in the self-hosted compiler's canonical format."""

    _POSITIONS = frozenset({"line", "col", "name_line", "name_col", "source_file"})

    def __init__(self, *, positions: bool = True, callable_body: Callable[[Any], str] | None = None) -> None:
        self._positions = positions
        self._callable_body = callable_body

    @classmethod
    def position_free_renderer(cls) -> AstCanonicalRenderer:
        return cls(positions=False)

    @classmethod
    def interface_renderer(cls, callable_body: Callable[[Any], str]) -> AstCanonicalRenderer:
        return cls(positions=False, callable_body=callable_body)

    def render(self, value: Any) -> str:
        return self._render(value, 0)

    def _render(self, value: Any, depth: int, template: bool = False) -> str:
        padding = "  " * depth
        child_padding = "  " * (depth + 1)
        if value is None:
            return "nil"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if not self._positions:
                # All supported targets use IEEE binary64. Keep every bit,
                # including signed zero and values lost by display rounding.
                return "binary64:" + struct.pack(">d", value).hex()
            # A double past binary32's overflow midpoint prints as infinity.
            try:
                narrowed = struct.unpack("f", struct.pack("f", value))[0]
            except OverflowError:
                return "inf" if value > 0 else "-inf"
            return f"{narrowed:f}"
        if isinstance(value, str):
            return self._quoted(value)
        if isinstance(value, list):
            if not value:
                return "[]"
            children = "\n".join(child_padding + self._render(item, depth + 1, template) for item in value)
            return f"[\n{children}\n{padding}]"
        if is_dataclass(value) and not isinstance(value, type):
            if type(value).__module__ != generated_ast.__name__:
                raise TypeError(f"unsupported canonical AST value: {type(value).__name__}")
            template = template or bool(getattr(value, "generic_params", None))
            node_fields = [item for item in fields(value) if self._positions or item.name not in self._POSITIONS]
            if not node_fields:
                return f"({type(value).__name__})"
            body = "\n".join(
                child_padding + field.name + "=" + self._field(value, field.name, depth + 1, template)
                for field in node_fields
            )
            return f"({type(value).__name__}\n{body})"
        raise TypeError(f"unsupported canonical AST value: {type(value).__name__}")

    def _field(self, node: Any, name: str, depth: int, template: bool) -> str:
        value = None if name == "source_file" else getattr(node, name)
        if self._callable_body is not None and not template and value is not None:
            if (isinstance(node, (generated_ast.FunctionDecl, generated_ast.MethodDecl)) and name == "body") or (
                isinstance(node, generated_ast.PropertyDecl) and name in {"getter_body", "setter_body"}
            ):
                return f"(ElidedBody {self._callable_body(node)})"
        return self._render(value, depth, template)

    @staticmethod
    def _quoted(value: str) -> str:
        escaped = []
        replacements = {
            "\\": "\\\\",
            '"': '\\"',
            "\n": "\\n",
            "\r": "\\r",
            "\t": "\\t",
        }
        for character in value:
            escaped.append(replacements.get(character, character))
        return '"' + "".join(escaped) + '"'


class AstJsonCodec:
    """Own the immutable AST schema accepted by one persistent cache."""

    def __init__(self, node_types: Mapping[str, type] | None = None) -> None:
        allowed = (
            {
                value.__name__: value
                for value in vars(generated_ast).values()
                if isinstance(value, type) and value.__module__ == generated_ast.__name__ and is_dataclass(value)
            }
            if node_types is None
            else node_types
        )
        self._node_types = MappingProxyType(dict(allowed))

    def encode(self, value: Any) -> Any:
        """Convert an AST value into JSON-compatible primitives."""

        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, list):
            return [self.encode(item) for item in value]
        value_type = type(value)
        if self._node_types.get(value_type.__name__) is not value_type:
            raise TypeError(f"unsupported cached AST value: {value_type.__name__}")
        return {
            "fields": {
                field.name: self.encode(None if field.name == "source_file" else getattr(value, field.name))
                for field in fields(value)
            },
            "type": value_type.__name__,
        }

    def decode(self, value: Any) -> Any:
        """Reconstruct only known AST dataclasses from JSON values."""

        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, list):
            return [self.decode(item) for item in value]
        if not isinstance(value, dict) or set(value) != {"fields", "type"}:
            raise ValueError("invalid cached AST node")
        node_type = value["type"]
        value_type = self._node_types.get(node_type) if isinstance(node_type, str) else None
        field_values = value["fields"]
        if value_type is None or not isinstance(field_values, dict):
            raise ValueError("unknown cached AST node")
        expected_fields = {field.name for field in fields(value_type)}
        if set(field_values) != expected_fields:
            raise ValueError("cached AST fields do not match the current schema")
        return value_type(**{name: self.decode(item) for name, item in field_values.items()})
