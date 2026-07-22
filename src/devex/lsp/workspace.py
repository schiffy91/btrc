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
from contextlib import suppress
from dataclasses import dataclass

from src.compiler.python import pkg
from src.compiler.python.ast_nodes import Program
from src.compiler.python.cache_keys import resolve_cache_dir
from src.compiler.python.frontend.resolver import SourceResolver
from src.compiler.python.frontend.stdlib import StdlibRepository
from src.compiler.python.frontend_limits import ResolutionBudget
from src.compiler.python.pkg import IncludeResolutionError
from src.compiler.python.source_io import MAX_SOURCE_BYTES, SourceReadError, read_source
from src.devex.lsp.package_resolution import PackageResolver
from src.devex.lsp.unit_cache import (
    cache_path,
    load_unit,
    prune_unit_cache,
    store_unit,
)
from src.devex.lsp.units import _UNIT_CACHE_VERSION, FileUnit, parse_unit
from src.devex.lsp.workspace_cache import WorkspaceCacheMixin, path_identity


@dataclass
class Composition:
    """A composed program for one active file."""

    active: FileUnit
    imported: list[FileUnit]
    stdlib: list[FileUnit]
    program: Program
    import_errors: list[tuple[int, str]]  # (active-file 1-based line, message)

    def units_with_tokens(self) -> list[FileUnit]:
        return [self.active] + [u for u in self.imported if u.tokens]


class Workspace(WorkspaceCacheMixin):
    """Owns the unit caches and composes programs for analysis.

    ``overlay_provider`` lets the server supply unsaved editor buffers for
    imported files; otherwise units are read from disk.
    """

    # One full stdlib AnalyzedProgram per distinct user-shadowed-name set is
    # multi-MB; typing `class Strings {` mid-edit mints throwaway entries. A
    # session flips between at most a couple of stable shadow sets (none + one
    # per open file), so 4 covers real reuse while bounding memory.
    _STDLIB_BASE_CACHE_MAX = 4

    def __init__(self):
        self._init_caches()
        self._package_resolver = PackageResolver()
        self._stdlib = StdlibRepository()
        self._source_resolver = SourceResolver(self._stdlib)
        self._stdlib_units: list[FileUnit] | None = None
        self._stdlib_lock = threading.Lock()  # one stdlib build/analysis at a time
        # included paths -> AnalyzedProgram, LRU-capped (see _STDLIB_BASE_CACHE_MAX)
        self._stdlib_base_cache: OrderedDict[frozenset, object] = OrderedDict()
        self.overlay_provider = None  # Callable[[str], str | None]

    def parse_active(self, path: str, source: str) -> FileUnit:
        """Parse the active document's live buffer (cached by content hash)."""
        path = os.path.abspath(path)
        sig = ("active", _live_source_digest(source))
        key = path_identity(path)
        cached = self._cached_file(key)
        if cached and cached[0] == sig:
            return cached[1]
        unit = parse_unit(path, source)
        self._store_file(key, sig, unit)
        return unit

    def get_file_unit(self, path: str) -> FileUnit | None:
        path = os.path.abspath(path)
        key = path_identity(path)
        overlay = self.overlay_provider(path) if self.overlay_provider else None
        if overlay is not None:
            try:
                sig = ("overlay", _live_source_digest(overlay))
            except ValueError:
                return None
            cached = self._cached_file(key)
            if cached and cached[0] == sig:
                return cached[1]
            unit = parse_unit(path, overlay)
            self._store_file(key, sig, unit)
            return unit
        try:
            text = read_source(path)
        except SourceReadError:
            return None
        sig = ("disk", hashlib.sha256(text.encode()).hexdigest())
        cached = self._cached_file(key)
        if cached and cached[0] == sig:
            return cached[1]
        unit = parse_unit(path, text)
        self._store_file(key, sig, unit)
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
            source = read_source(path)
        except SourceReadError:
            return None
        content_hash = hashlib.sha256(source.encode()).hexdigest()
        cache_dir = None
        with suppress(OSError):
            cache_dir = _cache_dir()
        cached_path = None
        if cache_dir is not None:
            prune_unit_cache(cache_dir)
            cached_path = cache_path(cache_dir, _UNIT_CACHE_VERSION, source)
            cached = load_unit(cached_path, path, content_hash)
            if cached is not None:
                return cached
        unit = parse_unit(path, source)
        if unit.error is None and cached_path is not None:
            with suppress(OSError, TypeError, ValueError):
                store_unit(cached_path, unit)
        unit.source = ""
        unit.tokens = []
        unit.import_specs = []
        return unit

    def compose(self, active: FileUnit) -> Composition:
        imported: list[FileUnit] = []
        import_errors: list[tuple[int, str]] = []
        included = {path_identity(active.path)}
        budget = ResolutionBudget()
        budget.enter(active.source, active.path, 0)

        def visit(unit: FileUnit, attribute_line: int, depth: int = 0):
            for line, spec in unit.import_specs:
                attr = line if unit is active else attribute_line
                try:
                    paths = self._source_resolver.import_paths(spec, os.path.dirname(unit.path))
                except IncludeResolutionError as e:
                    import_errors.append((attr, str(e)))
                    continue
                for p in paths:
                    ap = os.path.abspath(p)
                    identity = path_identity(ap)
                    if identity in included or ap.endswith(".c"):
                        continue
                    included.add(identity)
                    u = self.get_file_unit(ap)
                    if u is None:
                        import_errors.append((attr, f"cannot read import '{spec}'"))
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

        try:
            packages = self._package_resolver.packages_for(active.path)
        except IncludeResolutionError as error:
            packages = {}
            import_errors.append((1, str(error)))
        # Package state is document-root-local. ContextVar scoping prevents one
        # workspace/project from affecting another concurrent LSP analysis and
        # restores any embedding host's prior context after composition.
        with pkg.package_context(packages):
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
        )

    def analyze(self, comp: Composition):
        """Semantic analysis over the composed program.

        The stdlib portion is analyzed once per exclusion set and its symbol
        tables are used to seed a fresh analyzer that only processes the
        user's declarations — the stdlib method bodies never re-analyze.
        """
        from src.compiler.python.analyzer.analyzer import Analyzer

        base = self._stdlib_base(comp.stdlib)
        if base is None:
            analyzer = Analyzer()
            analyzer.record_occurrences = True
            return analyzer.analyze(comp.program)

        analyzer = Analyzer()
        # Record identifier resolutions for the user program only — the stdlib
        # base is analyzed separately (and cheaply) without recording.
        analyzer.record_occurrences = True
        analyzer.class_table = dict(base.class_table)
        analyzer.function_table = dict(base.function_table)
        analyzer.enum_table = dict(base.enum_table)
        analyzer.interface_table = dict(base.interface_table)
        analyzer.rich_enum_table = dict(base.rich_enum_table)
        analyzer.generic_instances = {k: list(v) for k, v in base.generic_instances.items()}

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
        from src.compiler.python.analyzer.analyzer import Analyzer

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
                base = Analyzer().analyze(Program(declarations=decls))
            except Exception:
                return None
            self._stdlib_base_cache[key] = base
            while len(self._stdlib_base_cache) > self._STDLIB_BASE_CACHE_MAX:
                self._stdlib_base_cache.popitem(last=False)
            return base


def _cache_dir() -> str:
    """Shared btrc cache dir ($BTRC_CACHE_DIR > project root > user cache);
    never the bare cwd, so the server doesn't litter its launch directory."""
    return resolve_cache_dir()


def _live_source_digest(source: str) -> str:
    """Hash one editor buffer after enforcing the compiler's source limit."""
    try:
        encoded = source.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("document contains invalid Unicode") from error
    if len(encoded) > MAX_SOURCE_BYTES:
        raise ValueError(f"document exceeds the {MAX_SOURCE_BYTES}-byte source limit")
    return hashlib.sha256(encoded).hexdigest()
