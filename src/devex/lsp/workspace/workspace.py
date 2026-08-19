"""Workspace: unit caches, program composition, and seeded analysis.

Owns the per-file unit caches (a keystroke re-parses only the edited file),
composes the stdlib + imported + active declaration lists into one Program,
and runs semantic analysis seeded with a once-per-session stdlib base so
stdlib bodies never re-analyze.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass

from src.compiler.python.syntax.ast.generated import Program
from src.compiler.python.frontend.imports import ImportResolver
from src.compiler.python.frontend.packages import IncludeResolutionError, ResolvedPackages
from src.compiler.python.frontend.sources import (
    SourceDependencyGraph,
    SourceDirectiveScanner,
    SourceFileReader,
    SourceReadError,
    SourceResolutionPolicy,
    StdlibRepository,
)
from src.devex.lsp.workspace.cache import PackageResolutionCache, UnitCache, WorkspaceCache
from src.devex.lsp.workspace.units import FileUnit


@dataclass
class Composition:
    """A composed program for one active file."""

    active: FileUnit
    imported: list[FileUnit]
    stdlib: list[FileUnit]
    program: Program
    import_errors: list[tuple[int, str]]  # (active-file 1-based line, message)
    graph: SourceDependencyGraph

    def units_with_tokens(self) -> list[FileUnit]:
        return [self.active] + [u for u in self.imported if u.tokens]

    def snapshot_fingerprint(self, uri: str) -> tuple:
        """Return every composition input that can change LSP diagnostics."""

        return (
            uri,
            self.active.content_hash,
            tuple((unit.path, unit.content_hash) for unit in self.imported),
            tuple(unit.path for unit in self.stdlib),
            tuple(self.import_errors),
            self.graph.cache_records(),
        )


class Workspace:
    """Owns the unit caches and composes programs for analysis.

    ``overlay_provider`` lets the server supply unsaved editor buffers for
    imported files; otherwise units are read from disk.
    """

    # One full stdlib AnalyzedProgram per distinct user-shadowed-name set is
    # multi-MB; typing `class Strings {` mid-edit mints throwaway entries. A
    # session flips between at most a couple of stable shadow sets (none + one
    # per open file), so 4 covers real reuse while bounding memory.
    _STDLIB_BASE_CACHE_MAX = 4

    def __init__(
        self,
        *,
        package_cache: PackageResolutionCache | None = None,
        stdlib: StdlibRepository | None = None,
        unit_cache: UnitCache | None = None,
        workspace_cache: WorkspaceCache | None = None,
        source_reader: SourceFileReader | None = None,
        directive_scanner: SourceDirectiveScanner | None = None,
        resolution_policy: SourceResolutionPolicy | None = None,
    ):
        self._cache = workspace_cache or WorkspaceCache()
        self._package_cache = package_cache or PackageResolutionCache()
        if stdlib is not None:
            if resolution_policy is not None and stdlib.resolution_policy != resolution_policy:
                raise ValueError("Workspace and stdlib must share one source resolution policy")
            resolution_policy = stdlib.resolution_policy
        elif resolution_policy is None and source_reader is not None:
            resolution_policy = SourceResolutionPolicy(
                max_source_bytes=source_reader.max_bytes,
            )
        self._resolution_policy = resolution_policy or SourceResolutionPolicy()
        if source_reader is not None and source_reader.max_bytes != self._resolution_policy.max_source_bytes:
            raise ValueError("Workspace and source reader must share one source byte limit")
        self._source_reader = source_reader or SourceFileReader(
            self._resolution_policy.max_source_bytes,
        )
        self._directives = directive_scanner or SourceDirectiveScanner()
        self._stdlib = stdlib or StdlibRepository(
            source_reader=self._source_reader,
            directive_scanner=self._directives,
            resolution_policy=self._resolution_policy,
        )
        self._unit_cache = unit_cache or UnitCache.from_environment()
        self._imports = ImportResolver(
            self._stdlib,
            source_reader=self._source_reader,
            directive_scanner=self._directives,
            resolution_policy=self._resolution_policy,
        )
        self._stdlib_units: list[FileUnit] | None = None
        self._stdlib_lock = threading.Lock()  # one stdlib build/analysis at a time
        # included paths -> AnalyzedProgram, LRU-capped (see _STDLIB_BASE_CACHE_MAX)
        self._stdlib_base_cache: OrderedDict[frozenset, object] = OrderedDict()
        self.overlay_provider = None  # Callable[[str], str | None]

    def cached_units(self, root: str | None = None) -> list[FileUnit]:
        return self._cache.cached_units(root)

    def get_snapshot(self, path: str):
        return self._cache.get_snapshot(path)

    def store_snapshot(self, path: str, fingerprint: tuple, result) -> None:
        self._cache.store_snapshot(path, fingerprint, result)

    def close_document(self, path: str) -> None:
        self._cache.close_document(path)

    def parse_active(self, path: str, source: str) -> FileUnit:
        """Parse the active document's live buffer (cached by content hash)."""
        path = os.path.abspath(path)
        sig = ("active", self._live_source_digest(source))
        key = WorkspaceCache.path_identity(path)
        cached = self._cache.lookup_file(key)
        if cached and cached[0] == sig:
            return cached[1]
        unit = FileUnit.parse(
            path,
            source,
            stdlib=self._stdlib,
            directive_scanner=self._directives,
        )
        self._cache.store_file(key, sig, unit)
        return unit

    def get_file_unit(self, path: str) -> FileUnit | None:
        path = os.path.abspath(path)
        key = WorkspaceCache.path_identity(path)
        overlay = self.overlay_provider(path) if self.overlay_provider else None
        if overlay is not None:
            try:
                sig = ("overlay", self._live_source_digest(overlay))
            except ValueError:
                return None
            cached = self._cache.lookup_file(key)
            if cached and cached[0] == sig:
                return cached[1]
            unit = FileUnit.parse(
                path,
                overlay,
                stdlib=self._stdlib,
                directive_scanner=self._directives,
            )
            self._cache.store_file(key, sig, unit)
            return unit
        try:
            text = self._source_reader.read(path)
        except SourceReadError:
            return None
        sig = ("disk", hashlib.sha256(text.encode()).hexdigest())
        cached = self._cache.lookup_file(key)
        if cached and cached[0] == sig:
            return cached[1]
        unit = FileUnit.parse(
            path,
            text,
            stdlib=self._stdlib,
            directive_scanner=self._directives,
        )
        self._cache.store_file(key, sig, unit)
        return unit

    def stdlib_units(self) -> list[FileUnit]:
        # Fast path without the lock: assignment below is atomic and final.
        units = self._stdlib_units
        if units is not None:
            return units
        with self._stdlib_lock:
            if self._stdlib_units is None:  # warmup + first didOpen race: build once
                loaded = [
                    self._load_stdlib_unit(os.path.join(self._stdlib.directory(), filename))
                    for filename in self._stdlib.discover_files()
                ]
                # Single atomic assignment of the filtered list: a concurrent
                # reader never observes None placeholders.
                self._stdlib_units = [u for u in loaded if u is not None]
            return self._stdlib_units

    def _load_stdlib_unit(self, path: str) -> FileUnit | None:
        try:
            source = self._source_reader.read(path)
        except SourceReadError:
            return None
        cached = self._unit_cache.load(path, source)
        if cached is not None:
            return cached
        unit = FileUnit.parse(
            path,
            source,
            stdlib=self._stdlib,
            directive_scanner=self._directives,
        )
        if unit.error is None:
            self._unit_cache.store(source, unit)
        unit.source = ""
        unit.tokens = []
        return unit

    def compose(self, active: FileUnit) -> Composition:
        imported: list[FileUnit] = []
        import_errors: list[tuple[int, str]] = []
        included = {WorkspaceCache.path_identity(active.path)}
        graph = SourceDependencyGraph()
        graph.ensure_source(active.path)
        budget = self._resolution_policy.new_budget()
        budget.enter(active.source, active.path, 0)

        try:
            packages = self._package_cache.resolve_for(active.path)
        except IncludeResolutionError as error:
            packages = ResolvedPackages.empty()
            import_errors.append((1, str(error)))

        def visit(unit: FileUnit, attribute_line: int, depth: int = 0):
            for dependency in unit.dependencies:
                attr = dependency.line if unit is active else attribute_line
                try:
                    paths = self._imports.import_paths(
                        dependency.spec,
                        os.path.dirname(unit.path),
                        packages,
                    )
                except IncludeResolutionError as e:
                    import_errors.append((attr, str(e)))
                    continue
                for p in paths:
                    ap = os.path.abspath(p)
                    graph.add(unit.path, ap, dependency.kind)
                    identity = WorkspaceCache.path_identity(ap)
                    if identity in included or ap.endswith(".c"):
                        continue
                    included.add(identity)
                    u = self.get_file_unit(ap)
                    if u is None:
                        import_errors.append((attr, f"cannot read import '{dependency.spec}'"))
                        continue
                    try:
                        budget.enter(u.source, ap, depth + 1)
                    except IncludeResolutionError as error:
                        import_errors.append((attr, str(error)))
                        continue
                    if u.error:
                        import_errors.append((attr, f"imported file '{os.path.basename(ap)}': {u.error}"))
                    imported.append(u)
                    visit(u, attr, depth + 1)

        visit(active, 1)

        user_names = set(active.defined_names)
        for u in imported:
            user_names |= u.defined_names
        stdlib = [u for u in self.stdlib_units() if not (u.defined_names & user_names)]

        decls: list = []
        for u in stdlib:
            decls.extend(u.decls)
        for u in imported:
            decls.extend(u.decls)
        decls.extend(active.decls)

        return Composition(
            active=active,
            imported=imported,
            stdlib=stdlib,
            program=Program(declarations=decls),
            import_errors=import_errors,
            graph=graph,
        )

    def project_manifest(self, path: str) -> str | None:
        """Return the package-project boundary governing ``path``."""

        return self._package_cache.manifest_for(path)

    def stdlib_symbol_files(self) -> dict[str, frozenset[str]]:
        """Return canonical symbol ownership from this workspace's stdlib."""

        return self._stdlib.symbol_files()

    def stdlib_directory(self) -> str:
        """Return the root owned by this workspace's stdlib repository."""

        return self._stdlib.directory()

    def shares_project_manifest(
        self,
        path: str,
        active_manifest: str | None,
    ) -> bool:
        return self._package_cache.shares_manifest(path, active_manifest)

    def analyze(self, comp: Composition):
        """Semantic analysis over the composed program.

        The stdlib portion is analyzed once per exclusion set and its symbol
        tables are used to seed a fresh analyzer that only processes the
        user's declarations — the stdlib method bodies never re-analyze.
        """
        from src.compiler.python.analyzer.analyzer import SemanticAnalyzer

        base = self._stdlib_base(comp.stdlib)
        if base is None:
            return SemanticAnalyzer(record_occurrences=True).analyze(comp.program)

        # Record identifier resolutions for the user program only — the stdlib
        # base is analyzed separately (and cheaply) without recording.
        analyzer = SemanticAnalyzer(record_occurrences=True, seed=base)

        user_decls: list = []
        for u in comp.imported:
            user_decls.extend(u.decls)
        user_decls.extend(comp.active.decls)
        return analyzer.analyze(Program(declarations=user_decls))

    def _stdlib_base(self, stdlib: list[FileUnit]):
        """Analyze the (possibly user-filtered) stdlib once and cache the result.

        The cache is a small LRU: each entry is a full stdlib AnalyzedProgram,
        so unbounded growth (one entry per transient shadow set while typing)
        would leak multi-MB objects.
        """
        from src.compiler.python.analyzer.analyzer import SemanticAnalyzer

        key = frozenset(u.path for u in stdlib)
        # The whole build runs under the lock: the analyzer mutates the shared
        # stdlib decls in place, so two concurrent builds would corrupt them.
        with self._stdlib_lock:
            base = self._stdlib_base_cache.get(key)
            if base is not None:
                self._stdlib_base_cache.move_to_end(key)
                return base
            decls: list = []
            for u in stdlib:
                decls.extend(u.decls)
            try:
                base = SemanticAnalyzer().analyze(Program(declarations=decls))
            except Exception:
                return None
            self._stdlib_base_cache[key] = base
            while len(self._stdlib_base_cache) > self._STDLIB_BASE_CACHE_MAX:
                self._stdlib_base_cache.popitem(last=False)
            return base

    def _live_source_digest(self, source: str) -> str:
        """Hash one editor buffer after enforcing the compiler's source limit."""

        try:
            encoded = source.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("document contains invalid Unicode") from error
        max_bytes = self._source_reader.max_bytes
        if len(encoded) > max_bytes:
            raise ValueError(f"document exceeds the {max_bytes}-byte source limit")
        return hashlib.sha256(encoded).hexdigest()
