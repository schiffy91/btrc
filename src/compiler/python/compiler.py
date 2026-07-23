"""Public compiler application object."""

from __future__ import annotations

import contextlib
import os

from .artifacts.cache.compiler_cache import CompilationCache, ToolchainFingerprint
from .pipeline.models import CompilerOptions, CompilerResult, FrontendResult
from .pipeline.pipeline import CompilerPipeline


class Compiler:
    """Own one configured pipeline and its application-level artifact cache."""

    def __init__(
        self,
        pipeline: CompilerPipeline | None = None,
        cache: CompilationCache | None = None,
    ) -> None:
        fingerprint = ToolchainFingerprint()
        self.pipeline = pipeline or CompilerPipeline(fingerprint=fingerprint)
        self.cache = cache or CompilationCache(fingerprint=fingerprint)

    def compile(
        self,
        source: str,
        source_path: str,
        options: CompilerOptions | None = None,
    ) -> CompilerResult:
        """Compile source through the requested terminal pipeline stage."""

        options = options or CompilerOptions()
        profile: dict[str, float] | None = {} if options.profile else None
        resolved = self.pipeline.resolve(source, source_path, options, profile)

        if options.cacheable:
            cached = self.cache.load(resolved, source_path)
            if cached is not None:
                return CompilerResult(
                    options=options,
                    source_bundle=resolved,
                    c_source=cached,
                    cache_hit=True,
                    profile=CompilerResult.profile_snapshot(profile),
                )

        result = self.pipeline.compile_resolved(
            resolved,
            os.path.basename(source_path),
            options,
            profile,
        )
        if options.cacheable and result.successful and result.c_source is not None:
            with contextlib.suppress(OSError, UnicodeError):
                self.cache.store(resolved, source_path, result.c_source)
        return result

    def compile_frontend(
        self,
        source: str,
        source_path: str,
        options: CompilerOptions | None = None,
        *,
        filename: str | None = None,
        profile: dict[str, float] | None = None,
    ) -> FrontendResult:
        """Compile through semantic analysis for tools that consume typed AST."""

        return self.pipeline.compile_frontend(
            source,
            source_path,
            options or CompilerOptions(),
            filename=filename,
            profile=profile,
        )
