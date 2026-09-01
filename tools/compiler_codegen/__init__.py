"""Deterministic compiler source-generation owners."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


class GeneratedSourceError(RuntimeError):
    """A generated artifact is invalid or differs from its checked-in form."""


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    """One repository-relative generated file."""

    path: PurePosixPath
    content: bytes
    mode: int = 0o644

    def __post_init__(self) -> None:
        if self.path.is_absolute() or ".." in self.path.parts:
            raise GeneratedSourceError(f"generated path must be repository-relative: {self.path}")
        if b"\r" in self.content:
            raise GeneratedSourceError(f"generated source must use LF line endings: {self.path}")
        if self.mode != 0o644:
            raise GeneratedSourceError(f"generated source mode must be 0644: {self.path}")


def format_generated_btrc(source: str, path: PurePosixPath) -> bytes:
    """Return one generated BTRC source in the repository's canonical style."""

    if path.suffix != ".btrc":
        raise GeneratedSourceError(f"generated BTRC path must end in .btrc: {path}")

    from src.devex.formatter import BtrcFormatter, FormatError

    try:
        formatted = BtrcFormatter().format(source, path.as_posix())
    except FormatError as error:
        raise GeneratedSourceError(
            f"generated BTRC source is invalid at {path}:{error.line}:{error.column}: {error}"
        ) from error
    return formatted.encode("utf-8")
