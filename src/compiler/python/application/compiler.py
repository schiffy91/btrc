"""Public compiler application object."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Protocol

from ..frontend.packages import IncludeResolutionError
from ..frontend.sources import ResolvedSource
from .pipeline import CompilationPipeline
from .results import (
    CompilerActionResult,
    CompilerFailure,
    CompilerFailureKind,
    CompilerOptions,
    CompilerResult,
    FrontendResult,
)


class CompilerCachePort(Protocol):
    """Persistent C-output operations required by the compiler application."""

    def load_text(
        self,
        resolved_source: str,
        input_path: str | None = None,
        *,
        source_identity: str = "",
    ) -> str | None: ...

    def store_text(
        self,
        resolved_source: str,
        c_output: str,
        input_path: str | None = None,
        *,
        source_identity: str = "",
    ) -> None: ...


class DisabledCompilerCache:
    """Explicit no-persistence cache used by an unconfigured library compiler."""

    @staticmethod
    def load_text(
        resolved_source: str,
        input_path: str | None = None,
        *,
        source_identity: str = "",
    ) -> None:
        del resolved_source, input_path, source_identity
        return None

    @staticmethod
    def store_text(
        resolved_source: str,
        c_output: str,
        input_path: str | None = None,
        *,
        source_identity: str = "",
    ) -> None:
        del resolved_source, c_output, input_path, source_identity


class SelfhostBundlePublication(Protocol):
    """Published bundle paths returned by a self-host artifact owner."""

    bundle: Path
    archive: Path
    checksum: Path


class SelfhostBundlePort(Protocol):
    """Self-host publication operation required by the compiler application."""

    def build(
        self,
        *,
        binary: Path,
        target: str,
        output_dir: Path,
        source_root: Path,
        version: str | None = None,
        epoch: int = 0,
    ) -> SelfhostBundlePublication: ...


class DisabledSelfhostBundlePublisher:
    """Explicit unavailable bundle port used by an unconfigured library compiler."""

    @staticmethod
    def build(
        *,
        binary: Path,
        target: str,
        output_dir: Path,
        source_root: Path,
        version: str | None = None,
        epoch: int = 0,
    ) -> SelfhostBundlePublication:
        del binary, target, output_dir, source_root, version, epoch
        raise ValueError("self-host bundle publication is not configured")


class Compiler:
    """Own one configured pipeline and its application-level artifact cache."""

    def __init__(
        self,
        pipeline: CompilationPipeline | None = None,
        cache: CompilerCachePort | None = None,
        bundle_builder: SelfhostBundlePort | None = None,
    ) -> None:
        self.pipeline = pipeline if pipeline is not None else CompilationPipeline()
        self.cache = cache if cache is not None else DisabledCompilerCache()
        self._bundle_builder = bundle_builder if bundle_builder is not None else DisabledSelfhostBundlePublisher()

    @property
    def stdlib_directory(self) -> str:
        return os.path.abspath(self.pipeline.frontend.stdlib.directory())

    @property
    def freestanding_header(self) -> str:
        return self.pipeline.freestanding_runtime.header

    @property
    def stdlib_archive_available(self) -> bool:
        """Whether this compiler has a configured persistent archive owner."""

        return self.pipeline.stdlib_archive.repository.available

    @staticmethod
    def _cache_inputs(source: ResolvedSource) -> tuple[str, str]:
        """Adapt a frontend result to the artifact cache's value-only contract."""

        import_mode = "strict" if source.strict_imports else "relaxed"
        return (
            f"import-mode={import_mode}\0{source.source}",
            source.cache_identity(),
        )

    def compile(
        self,
        source: str,
        source_path: str,
        options: CompilerOptions | None = None,
    ) -> CompilerResult:
        """Compile source through the requested terminal pipeline stage."""

        options = options or CompilerOptions()
        profile: dict[str, float] | None = {} if options.profile else None
        try:
            resolved = self.pipeline.resolve(source, source_path, options, profile)
        except IncludeResolutionError as error:
            return CompilerResult(
                options=options,
                source_bundle=None,
                failure=CompilerFailure(CompilerFailureKind.PACKAGE, str(error)),
                profile=CompilerResult.profile_snapshot(profile),
            )
        cache_inputs = self._cache_inputs(resolved) if options.cacheable else None

        if cache_inputs is not None:
            cached = self.cache.load_text(
                cache_inputs[0],
                source_path,
                source_identity=cache_inputs[1],
            )
            if cached is not None:
                return CompilerResult(
                    options=options,
                    source_bundle=resolved,
                    c_source=cached,
                    native_plan=resolved.native_plan,
                    cache_hit=True,
                    profile=CompilerResult.profile_snapshot(profile),
                )

        result = self.pipeline.compile_resolved(
            resolved,
            os.path.basename(source_path),
            options,
            profile,
        )
        if cache_inputs is not None and result.successful and result.c_source is not None:
            with contextlib.suppress(OSError, UnicodeError):
                self.cache.store_text(
                    cache_inputs[0],
                    result.c_source,
                    input_path=source_path,
                    source_identity=cache_inputs[1],
                )
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

    def build_stdlib_archive(self, output_directory: str) -> CompilerActionResult:
        """Build the canonical stdlib through the configured application pipeline."""

        return self.pipeline.build_stdlib_archive(output_directory)

    def build_selfhost_bundle(
        self,
        *,
        binary: Path,
        target: str,
        output_directory: Path,
        source_root: Path,
        version: str | None = None,
        epoch: int = 0,
    ) -> CompilerActionResult:
        """Publish a self-host distribution through the artifact owner."""

        try:
            bundle = self._bundle_builder.build(
                binary=binary,
                target=target,
                output_dir=output_directory,
                source_root=source_root,
                version=version,
                epoch=epoch,
            )
        except (OSError, ValueError) as error:
            return CompilerActionResult(
                failure=CompilerFailure(CompilerFailureKind.ARCHIVE, str(error)),
            )
        return CompilerActionResult.completed(
            "self-host bundle published",
            bundle=str(bundle.bundle),
            archive=str(bundle.archive),
            checksum=str(bundle.checksum),
        )
