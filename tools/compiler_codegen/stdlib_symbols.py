"""Publish the root-stdlib symbol index both compilers load instead of parsing."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from . import GeneratedArtifact
from .hosted_abi import TargetManifest, TargetUnion


class StdlibSymbolIndexGenerator:
    """Render ``src/stdlib/btrc.symbols`` from the root stdlib modules.

    The index does not depend on the target: a symbol's owners are the union,
    over every spec target, of the root modules that declare it.
    """

    def __init__(self, repository_root: Path, targets: TargetManifest | None = None) -> None:
        self._repository_root = repository_root
        self._union = TargetUnion(targets if targets is not None else TargetManifest.load_repository(repository_root))

    def artifacts(self) -> tuple[GeneratedArtifact, ...]:
        from src.compiler.python.frontend.sources import ConditionalEnvironment, StdlibRepository
        from src.compiler.python.frontend.symbol_index import StdlibSymbolIndex

        sources = StdlibRepository(directory=str(self._repository_root / "src" / "stdlib"))
        per_target = {
            environment.label: sources.parsed_symbol_owners(environment=environment)
            for environment in ConditionalEnvironment.every_target()
        }
        merged = self._union.owners(per_target)
        content = StdlibSymbolIndex.render(sources.symbol_index_digest(), merged).encode("utf-8")
        return (GeneratedArtifact(PurePosixPath("src/stdlib") / StdlibSymbolIndex.INDEX_FILE_NAME, content),)
