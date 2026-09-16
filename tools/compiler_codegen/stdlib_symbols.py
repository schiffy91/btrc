"""Publish the root-stdlib symbol index both compilers load instead of parsing."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from . import GeneratedArtifact


class StdlibSymbolIndexGenerator:
    """Render ``src/stdlib/btrc.symbols`` from the root stdlib modules."""

    def __init__(self, repository_root: Path) -> None:
        self._repository_root = repository_root

    def artifacts(self) -> tuple[GeneratedArtifact, ...]:
        from src.compiler.python.frontend.sources import StdlibRepository
        from src.compiler.python.frontend.symbol_index import INDEX_FILE_NAME

        sources = StdlibRepository(directory=str(self._repository_root / "src" / "stdlib"))
        content = sources.render_symbol_index().encode("utf-8")
        return (GeneratedArtifact(PurePosixPath("src/stdlib") / INDEX_FILE_NAME, content),)
