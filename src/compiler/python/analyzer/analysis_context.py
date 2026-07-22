"""Mutable diagnostics and source provenance for one semantic analysis."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from ..ast_nodes import ImportDecl, Program
from .core_models import Diag


class AnalysisContext:
    """Own diagnostics and the source location active during analysis."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.diagnostics: list[Diag] = []
        self.current_source_file: str | None = None

    def declarations(self, program: Program) -> Iterator[object]:
        """Yield semantic declarations while tracking their source file."""
        for declaration in program.declarations:
            if isinstance(declaration, ImportDecl):
                continue
            with self.source(getattr(declaration, "source_file", None)):
                yield declaration

    @contextmanager
    def source(self, source_file: str | None) -> Iterator[None]:
        """Activate source provenance and restore any enclosing provenance."""
        previous = self.current_source_file
        self.current_source_file = source_file
        try:
            yield
        finally:
            self.current_source_file = previous

    def error(self, message: str, line: int = 0, col: int = 0) -> None:
        self.errors.append(f"{message} at {line}:{col}")
        self.diagnostics.append(
            Diag(message, line, col, "error", self.current_source_file),
        )

    def warning(self, message: str, line: int = 0, col: int = 0) -> None:
        self.warnings.append(f"{message} at {line}:{col}")
        self.diagnostics.append(
            Diag(message, line, col, "warning", self.current_source_file),
        )


__all__ = ["AnalysisContext"]
