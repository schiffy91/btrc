"""Owned filesystem resolution for btrc import and include directives."""

from __future__ import annotations

import os
import sys

from ..ast_nodes import (
    PackagePath,
    QuotedPath,
    RelativePath,
    StdGlob,
    StdModules,
)
from ..frontend_c_imports import c_include_directive
from ..frontend_limits import ResolutionBudget
from ..frontend_path_scan import scan_import_directory
from ..import_scan import scan_directives
from ..pkg import IncludeResolutionError, ResolvedPackages
from ..source_io import SourceReadError, read_source
from .dependencies import SourceDependencyGraph
from .stdlib import StdlibRepository


class ImportResolver:
    """Resolve one source graph against packages and a stdlib repository."""

    def __init__(self, stdlib: StdlibRepository | None = None) -> None:
        self.stdlib = stdlib or StdlibRepository()

    def import_paths(
        self,
        spec,
        source_dir: str,
        packages: ResolvedPackages,
    ) -> list[str]:
        """Resolve a parsed import specification to filesystem paths."""
        if isinstance(spec, StdGlob):
            return [os.path.join(self.stdlib.directory(), filename) for filename in self.stdlib.discover_files()]
        if isinstance(spec, StdModules):
            return [self._stdlib_module_path(name) for name in spec.names]
        if isinstance(spec, PackagePath):
            dotted = ".".join(spec.segments)
            return list(packages.paths_for_import(dotted)) or self._relative_paths(
                dotted,
                source_dir,
            )
        if isinstance(spec, (RelativePath, QuotedPath)):
            return list(packages.paths_for_import(spec.path)) or self._relative_paths(
                spec.path,
                source_dir,
            )
        raise IncludeResolutionError(f"unsupported import spec: {spec!r}")

    def resolve_mapped(
        self,
        source: str,
        source_path: str,
        packages: ResolvedPackages,
        included: set[str] | None = None,
        *,
        exit_on_error: bool = True,
    ) -> tuple[str, list[str], list[tuple[str, int]], SourceDependencyGraph]:
        """Resolve a source graph with file and original-line provenance."""
        graph = SourceDependencyGraph()
        try:
            traced = self._resolve_traced(
                source,
                source_path,
                packages,
                set() if included is None else included,
                graph,
                ResolutionBudget(),
                0,
            )
        except IncludeResolutionError as error:
            if not exit_on_error:
                raise
            print(f"error: {error}", file=sys.stderr)
            raise SystemExit(1) from error

        resolved = "\n".join(text for text, _, _ in traced)
        provenance = [path for _, path, _ in traced]
        source_positions = [(path, line) for _, path, line in traced]
        return resolved, provenance, source_positions, graph

    def resolve(
        self,
        source: str,
        source_path: str,
        packages: ResolvedPackages,
        included: set[str] | None = None,
        *,
        exit_on_error: bool = True,
    ) -> str:
        """Resolve a source graph to its textually composed source."""
        resolved, _, _, _ = self.resolve_mapped(
            source,
            source_path,
            packages,
            included,
            exit_on_error=exit_on_error,
        )
        return resolved

    def resolve_with_graph(
        self,
        source: str,
        source_path: str,
        packages: ResolvedPackages,
        *,
        exit_on_error: bool = True,
    ) -> tuple[str, list[str], SourceDependencyGraph]:
        """Resolve source with file provenance and its dependency graph."""
        resolved, provenance, _, graph = self.resolve_mapped(
            source,
            source_path,
            packages,
            exit_on_error=exit_on_error,
        )
        return resolved, provenance, graph

    def _resolve_include_path(self, include_path: str, source_dir: str) -> str:
        local = os.path.join(source_dir, include_path)
        if os.path.exists(local):
            return local
        stdlib_path = self.stdlib.find_file(include_path)
        if stdlib_path is not None:
            return stdlib_path
        raise IncludeResolutionError(
            f"include file '{include_path}' not found\n  searched: {source_dir}\n  searched: {self.stdlib.directory()}"
        )

    def _stdlib_module_path(self, name: str) -> str:
        filename = name if name.endswith(".btrc") else f"{name}.btrc"
        path = self.stdlib.find_file(filename)
        if path is None:
            raise IncludeResolutionError(f"stdlib import 'std.{name}' not found\n  searched: {self.stdlib.directory()}")
        return path

    def _relative_paths(self, spec: str, source_dir: str) -> list[str]:
        recursive = spec.endswith("/**")
        direct_glob = spec.endswith("/*")
        if recursive or direct_glob:
            base = spec[:-3] if recursive else spec[:-2]
            root = base if os.path.isabs(base) else os.path.join(source_dir, base)
            if not os.path.isdir(root):
                raise IncludeResolutionError(f"import directory '{spec}' not found\n  searched: {root}")
            return scan_import_directory(root, recursive=recursive)

        candidate = spec if os.path.isabs(spec) else os.path.join(source_dir, spec)
        if os.path.isdir(candidate):
            return scan_import_directory(candidate, recursive=False)
        if os.path.exists(candidate):
            return [candidate]
        return [self._resolve_include_path(spec, source_dir)]

    @staticmethod
    def _read_source(path: str) -> str:
        try:
            return read_source(path)
        except SourceReadError as error:
            raise IncludeResolutionError(str(error)) from error

    def _inline_paths(
        self,
        paths: list[str],
        packages: ResolvedPackages,
        source_path: str,
        line_number: int,
        included: set[str],
        graph: SourceDependencyGraph,
        output: list[tuple[str, str, int]],
        budget: ResolutionBudget,
        depth: int,
    ) -> None:
        for path in paths:
            absolute = os.path.abspath(path)
            graph.add_import(source_path, absolute)
            if path.endswith(".c"):
                identity = os.path.normcase(os.path.realpath(absolute))
                if identity in included:
                    continue
                budget.enter("", absolute, depth)
                included.add(identity)
                output.append((c_include_directive(absolute), source_path, line_number))
                continue
            output.extend(
                self._resolve_traced(
                    self._read_source(path),
                    path,
                    packages,
                    included,
                    graph,
                    budget,
                    depth,
                )
            )

    def _resolve_traced(
        self,
        source: str,
        source_path: str,
        packages: ResolvedPackages,
        included: set[str],
        graph: SourceDependencyGraph,
        budget: ResolutionBudget,
        depth: int,
    ) -> list[tuple[str, str, int]]:
        absolute = os.path.abspath(source_path)
        identity = os.path.normcase(os.path.realpath(absolute))
        source_dir = os.path.dirname(absolute)
        graph.ensure_source(absolute)
        if identity in included:
            return []
        budget.enter(source, absolute, depth)
        included.add(identity)

        directives = scan_directives(source)
        by_start = {directive.start: directive for directive in directives}
        covered = {line for directive in directives for line in range(directive.start, directive.end + 1)}
        output: list[tuple[str, str, int]] = []
        for line_number, line in enumerate(source.split("\n"), start=1):
            directive = by_start.get(line_number)
            if directive is not None:
                if directive.kind == "btrc_include":
                    target = os.path.abspath(
                        self._resolve_include_path(
                            directive.payload,
                            source_dir,
                        )
                    )
                    graph.add_include(absolute, target)
                    output.extend(
                        self._resolve_traced(
                            self._read_source(target),
                            target,
                            packages,
                            included,
                            graph,
                            budget,
                            depth + 1,
                        )
                    )
                else:
                    self._inline_paths(
                        self.import_paths(
                            directive.payload,
                            source_dir,
                            packages,
                        ),
                        packages,
                        absolute,
                        line_number,
                        included,
                        graph,
                        output,
                        budget,
                        depth + 1,
                    )
                continue
            if line_number not in covered:
                output.append((line, absolute, line_number))
        return output


__all__ = ["ImportResolver"]
