"""Source and dependency resolution for one compiler invocation."""

from __future__ import annotations

import os
import time

from ..frontend_limits import check_combined_source_size
from ..pkg import PackageResolver
from .dependencies import ResolvedSource
from .imports import ImportResolver
from .stdlib import StdlibRepository


class SourceResolver:
    """Own package setup, import/include resolution, and stdlib composition."""

    def __init__(
        self,
        stdlib: StdlibRepository | None = None,
        *,
        imports: ImportResolver | None = None,
        package_resolver: PackageResolver | None = None,
    ) -> None:
        if imports is not None and stdlib is not None and imports.stdlib is not stdlib:
            raise ValueError("SourceResolver imports and stdlib must share one repository")
        self.stdlib = imports.stdlib if imports is not None else (stdlib or StdlibRepository())
        self.imports = imports or ImportResolver(self.stdlib)
        self.package_resolver = package_resolver or PackageResolver()

    @staticmethod
    def _timed(profile: dict[str, float] | None, label: str, start: float) -> None:
        if profile is not None:
            profile[label] = time.perf_counter() - start

    def resolve(
        self,
        source: str,
        source_path: str,
        *,
        include_stdlib: bool = True,
        strict_imports: bool = True,
        map_stdlib_positions: bool = False,
        refresh_packages: bool = False,
        profile: dict[str, float] | None = None,
    ) -> ResolvedSource:
        """Resolve one root file into text, provenance, and dependency graph."""

        packages = self.package_resolver.resolve_for(
            source_path,
            refresh=refresh_packages,
        )
        start = time.perf_counter()
        user_source, provenance, source_positions, graph = self.imports.resolve_mapped(
            source,
            source_path,
            packages,
            exit_on_error=False,
        )
        self._timed(profile, "resolve_includes", start)

        stdlib_source = ""
        stdlib_positions: tuple[tuple[str, int], ...] = ()
        if include_stdlib and not strict_imports:
            start = time.perf_counter()
            if map_stdlib_positions:
                stdlib = self.stdlib.source_mapped(user_source)
                stdlib_source = stdlib.source
                stdlib_positions = stdlib.source_positions
            else:
                stdlib_source = self.stdlib.source(user_source)
            self._timed(profile, "stdlib_include", start)

        check_combined_source_size(stdlib_source, "\n" if stdlib_source else "", user_source)
        full_source = f"{stdlib_source}\n{user_source}" if stdlib_source else user_source
        return ResolvedSource(
            user_source=user_source,
            source=full_source,
            stdlib_source=stdlib_source,
            provenance=tuple(provenance),
            source_positions=stdlib_positions + tuple(source_positions),
            graph=graph,
            strict_imports=strict_imports,
            root_source_path=os.path.realpath(source_path),
        )

    def resolve_includes(
        self,
        source: str,
        source_path: str,
        included: set[str] | None = None,
        *,
        exit_on_error: bool = True,
    ) -> str:
        packages = self.package_resolver.resolve_for(source_path)
        return self.imports.resolve(
            source,
            source_path,
            packages,
            included,
            exit_on_error=exit_on_error,
        )

    def resolve_includes_traced(
        self,
        source: str,
        source_path: str,
        *,
        exit_on_error: bool = True,
    ):
        packages = self.package_resolver.resolve_for(source_path)
        return self.imports.resolve_with_graph(
            source,
            source_path,
            packages,
            exit_on_error=exit_on_error,
        )
