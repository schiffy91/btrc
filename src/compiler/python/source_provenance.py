"""Unforgeable provenance markers for compiler-composed source."""

from __future__ import annotations

import os


class CompilerStdlibSource(str):
    """A displayable path whose value was assigned by the front end."""


def compiler_stdlib_source(path: str = "<stdlib>") -> CompilerStdlibSource:
    """Mark a declaration as originating in compiler-resolved stdlib text."""
    return CompilerStdlibSource(path)


def is_compiler_stdlib_source(value: object) -> bool:
    """Return whether *value* carries front-end-authenticated provenance."""
    return isinstance(value, CompilerStdlibSource)


def stamp_nested_declaration_sources(declaration) -> None:
    """Propagate an authenticated top-level marker to nested declarations."""
    for attribute in ("members", "methods", "variants"):
        for nested in getattr(declaration, attribute, ()) or ():
            nested.source_file = declaration.source_file


def make_ir_source_maps(frontend_source, *, split_spaces: bool):
    """Build debug and declaration-aware source mappers for IR generation."""

    def normalized(mapped):
        if mapped is None:
            return None
        source_file, native_line = mapped
        if os.path.exists(source_file):
            source_file = os.path.abspath(source_file)
        return source_file, native_line

    def combined_line_map(combined_line: int):
        return normalized(frontend_source.map_line(combined_line, "combined"))

    def declaration_line_map(source_file: str | None, source_line: int):
        return normalized(
            frontend_source.map_declaration_line(
                source_line,
                source_file,
                split_spaces=split_spaces,
            )
        )

    return combined_line_map, declaration_line_map


__all__ = [
    "CompilerStdlibSource",
    "compiler_stdlib_source",
    "is_compiler_stdlib_source",
    "make_ir_source_maps",
    "stamp_nested_declaration_sources",
]
