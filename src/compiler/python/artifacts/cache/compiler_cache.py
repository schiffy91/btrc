"""Compiled-C cache collaborator used by the compiler application object."""

from __future__ import annotations

from ... import disk_cache
from ...frontend.dependencies import ResolvedSource


class CompilationCache:
    """Own cache framing and persistence for complete compiler results."""

    @staticmethod
    def cache_source(source: ResolvedSource) -> str:
        import_mode = "strict" if source.strict_imports else "relaxed"
        return f"import-mode={import_mode}\0{source.source}"

    def load(self, source: ResolvedSource, input_path: str) -> str | None:
        return disk_cache.get_cached(
            self.cache_source(source),
            input_path=input_path,
            source_identity=source.cache_identity(),
        )

    def store(self, source: ResolvedSource, input_path: str, c_source: str) -> None:
        disk_cache.store(
            self.cache_source(source),
            c_source,
            input_path=input_path,
            source_identity=source.cache_identity(),
        )
