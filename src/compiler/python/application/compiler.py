"""Public compiler application object."""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from ..frontend.packages import IncludeResolutionError
from ..frontend.sources import ResolvedSource, SourceFileReader, SourceText
from .pipeline import CompilationPipeline
from .results import (
    CompilerActionResult,
    CompilerDiagnostic,
    CompilerFailure,
    CompilerFailureKind,
    CompilerOptions,
    CompilerResult,
    FrontendResult,
)


class CachedCompilation(Protocol):
    """Value-only view of a verified complete emitted generation."""

    c_source: str
    c_units: tuple[str, ...]
    link_plan: str
    diagnostics: tuple[tuple[str, int, int, str, str | None], ...]
    split_source_spaces: bool


class CompilerInputIdentity(Protocol):
    """Read-time source authority rechecked before publishing compiler output."""

    def validate(self) -> None: ...


class CompilerOutputPublicationPort(Protocol):
    """Publish staged CLI outputs with the caller's final path safety check."""

    def retain_unchanged(
        self,
        outputs: Sequence[tuple[str, str, str]],
        *,
        validate: Callable[[Sequence[str]], None],
    ) -> bool:
        """Retain a complete owned generation of (destination, text, role) outputs."""
        ...

    def publish_staged(
        self,
        outputs: Sequence[tuple[str, str, str]],
        *,
        validate: Callable[[Sequence[str]], None],
    ) -> None: ...


class CompilerCachePort(Protocol):
    """Persistent emitted-artifact operations required by the application."""

    def load_artifacts(
        self,
        resolved_source: str,
        input_path: str | None = None,
        *,
        source_identity: str = "",
    ) -> CachedCompilation | None: ...

    def store_artifacts(
        self,
        resolved_source: str,
        c_output: str,
        input_path: str | None = None,
        *,
        c_units: tuple[str, ...] = (),
        link_plan: str,
        diagnostics: tuple[tuple[str, int, int, str, str | None], ...] = (),
        split_source_spaces: bool = False,
        source_identity: str = "",
    ) -> None: ...


class DisabledCompilerCache:
    """Explicit no-persistence cache used by an unconfigured library compiler."""

    @staticmethod
    def load_artifacts(
        resolved_source: str,
        input_path: str | None = None,
        *,
        source_identity: str = "",
    ) -> None:
        del resolved_source, input_path, source_identity
        return None

    @staticmethod
    def store_artifacts(
        resolved_source: str,
        c_output: str,
        input_path: str | None = None,
        *,
        c_units: tuple[str, ...] = (),
        link_plan: str,
        diagnostics: tuple[tuple[str, int, int, str, str | None], ...] = (),
        split_source_spaces: bool = False,
        source_identity: str = "",
    ) -> None:
        del resolved_source, c_output, input_path, c_units, link_plan, diagnostics, split_source_spaces, source_identity


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
    def _cache_inputs(source: ResolvedSource, options: CompilerOptions) -> tuple[str, str]:
        """Adapt a frontend result to the artifact cache's value-only contract."""

        import_mode = "strict" if source.strict_imports else "relaxed"
        return (
            f"import-mode={import_mode}\0{source.source}",
            json.dumps(
                {
                    "source": source.cache_identity(),
                    "debug": options.debug,
                    "dce": options.dce,
                    "use_ast_cache": options.use_ast_cache,
                    "map_stdlib_positions": options.map_stdlib_positions,
                    # Only debug emission observes the primary output path.
                    "generated_c_path": options.generated_c_path if options.debug else None,
                    "units_prefix": options.units_prefix,
                    "unit_lines": os.environ.get("BTRC_UNIT_LINES", "40000")
                    if options.units_prefix is not None
                    else None,
                    "cwd": os.getcwd() if options.debug or options.units_prefix is not None else None,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    @classmethod
    def read_source(cls, path: str) -> SourceText:
        """Read file-backed input with identity; compile() also accepts memory text."""
        return SourceFileReader().read_source(path)

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
        cache_inputs = (
            self._cache_inputs(resolved, options)
            if options.cacheable and (not resolved.native_plan.bindings or resolved.native_cache_identity is not None)
            else None
        )

        if cache_inputs is not None:
            cached = self.cache.load_artifacts(
                cache_inputs[0],
                source_path,
                source_identity=cache_inputs[1],
            )
            if cached is not None:
                native_plan = resolved.native_plan.with_cached_artifacts(
                    cached.link_plan, len(cached.c_units), options.units_prefix
                )
                if native_plan is not None:
                    return CompilerResult(
                        options=options,
                        source_bundle=resolved,
                        c_source=cached.c_source,
                        c_units=cached.c_units,
                        native_plan=native_plan,
                        diagnostics=tuple(CompilerDiagnostic(*record) for record in cached.diagnostics),
                        split_source_spaces=cached.split_source_spaces,
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
            with contextlib.suppress(OSError, UnicodeError, ValueError):
                self.cache.store_artifacts(
                    cache_inputs[0],
                    result.c_source,
                    input_path=source_path,
                    c_units=result.c_units,
                    link_plan=result.native_plan.canonical_json(),
                    diagnostics=tuple(
                        (diagnostic.message, diagnostic.line, diagnostic.col, diagnostic.severity, diagnostic.file)
                        for diagnostic in result.diagnostics
                    ),
                    split_source_spaces=result.split_source_spaces,
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
