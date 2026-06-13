"""Workspace: unit caches, program composition, and seeded analysis.

Owns the per-file unit caches (a keystroke re-parses only the edited file),
composes the stdlib + imported + active declaration lists into one Program,
and runs semantic analysis seeded with a once-per-session stdlib base so
stdlib bodies never re-analyze.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from src.compiler.python.ast_nodes import Program
from src.compiler.python.cache_keys import resolve_cache_dir
from src.compiler.python.frontend import (
    IncludeResolutionError,
    _discover_stdlib_files,
    _get_stdlib_dir,
    import_spec_paths,
)
from src.devex.lsp.units import _UNIT_CACHE_VERSION, FileUnit, parse_unit


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

    def __init__(self):
        self._file_cache: dict[str, tuple[tuple, FileUnit]] = {}  # path -> (sig, unit)
        self._stdlib_units: list[FileUnit] | None = None
        self._stdlib_lock = threading.Lock()  # one stdlib build/analysis at a time
        # included paths -> AnalyzedProgram, LRU-capped (see _STDLIB_BASE_CACHE_MAX)
        self._stdlib_base_cache: OrderedDict[frozenset, object] = OrderedDict()
        self.snapshot_cache: dict[str, tuple] = {}  # path -> (fingerprint, AnalysisResult)
        self.overlay_provider = None  # Callable[[str], str | None]

    # -- file units ---------------------------------------------------------

    def parse_active(self, path: str, source: str) -> FileUnit:
        """Parse the active document's live buffer (cached by content hash)."""
        path = os.path.abspath(path)
        sig = ("active", hashlib.sha256(source.encode()).hexdigest())
        cached = self._file_cache.get(path)
        if cached and cached[0] == sig:
            return cached[1]
        unit = parse_unit(path, source)
        self._file_cache[path] = (sig, unit)
        return unit

    def get_file_unit(self, path: str) -> FileUnit | None:
        path = os.path.abspath(path)
        overlay = self.overlay_provider(path) if self.overlay_provider else None
        if overlay is not None:
            sig = ("overlay", hashlib.sha256(overlay.encode()).hexdigest())
            cached = self._file_cache.get(path)
            if cached and cached[0] == sig:
                return cached[1]
            unit = parse_unit(path, overlay)
            self._file_cache[path] = (sig, unit)
            return unit
        try:
            st = os.stat(path)
            sig = ("disk", st.st_mtime_ns, st.st_size)
            cached = self._file_cache.get(path)
            if cached and cached[0] == sig:
                return cached[1]
            with open(path) as f:
                text = f.read()
        except OSError:
            return None
        unit = parse_unit(path, text)
        self._file_cache[path] = (sig, unit)
        return unit

    # -- stdlib units ---------------------------------------------------------

    def stdlib_units(self) -> list[FileUnit]:
        # Fast path without the lock: assignment below is atomic and final.
        units = self._stdlib_units
        if units is not None:
            return units
        with self._stdlib_lock:
            if self._stdlib_units is None:  # warmup + first didOpen race: build once
                loaded = [
                    self._load_stdlib_unit(os.path.join(_get_stdlib_dir(), fname))
                    for fname in _discover_stdlib_files()
                ]
                # Single atomic assignment of the filtered list: a concurrent
                # reader never observes None placeholders.
                self._stdlib_units = [u for u in loaded if u is not None]
            return self._stdlib_units

    def _load_stdlib_unit(self, path: str) -> FileUnit | None:
        try:
            with open(path) as f:
                source = f.read()
        except OSError:
            return None
        key = hashlib.sha256(f"unitv{_UNIT_CACHE_VERSION}\n{source}".encode()).hexdigest()
        cache_path = os.path.join(_cache_dir(), f"lspunit-{key}.pkl")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    unit = pickle.load(f)
                for decl in unit.decls:
                    decl.source_file = unit.path
                return unit
            except Exception:
                pass  # corrupt/incompatible: reparse below
        unit = parse_unit(path, source)
        _prune_unit_cache(_cache_dir())
        slim = FileUnit(
            path=unit.path,
            source="",  # stdlib source not needed post-parse; keeps pickles small
            content_hash=unit.content_hash,
            tokens=[],  # stdlib tokens not used by features
            decls=unit.decls,
            name_positions=unit.name_positions,
            member_name_positions=unit.member_name_positions,
            import_specs=[],
            defined_names=unit.defined_names,
        )
        try:
            with open(cache_path, "wb") as f:
                pickle.dump(slim, f, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:
            pass
        return slim

    # -- composition ----------------------------------------------------------

    def compose(self, active: FileUnit) -> Composition:
        imported: list[FileUnit] = []
        import_errors: list[tuple[int, str]] = []
        included = {active.path}

        def visit(unit: FileUnit, attribute_line: int):
            for line, spec in unit.import_specs:
                attr = line if unit is active else attribute_line
                try:
                    paths = import_spec_paths(spec, os.path.dirname(unit.path))
                except IncludeResolutionError as e:
                    import_errors.append((attr, str(e)))
                    continue
                for p in paths:
                    ap = os.path.abspath(p)
                    if ap in included or ap.endswith(".c"):
                        continue
                    included.add(ap)
                    u = self.get_file_unit(ap)
                    if u is None:
                        import_errors.append((attr, f"cannot read import '{spec}'"))
                        continue
                    if u.error:
                        import_errors.append(
                            (attr, f"imported file '{os.path.basename(ap)}': {u.error}")
                        )
                    imported.append(u)
                    visit(u, attr)

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

    # -- analysis -------------------------------------------------------------

    def analyze(self, comp: Composition):
        """Semantic analysis over the composed program.

        The stdlib portion is analyzed once per exclusion set and its symbol
        tables are used to seed a fresh analyzer that only processes the
        user's declarations — the stdlib method bodies never re-analyze.
        """
        from src.compiler.python.analyzer.analyzer import Analyzer

        base = self._stdlib_base(comp.stdlib)
        if base is None:
            return Analyzer().analyze(comp.program)

        analyzer = Analyzer()
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


_UNIT_CACHE_MAX_AGE = 30 * 24 * 3600  # seconds; orphaned pickles outlive a version flip
_pruned_dirs: set[str] = set()


def _prune_unit_cache(cache_dir: str) -> None:
    """Best-effort, once per process per dir: drop unit pickles older than 30 days."""
    if cache_dir in _pruned_dirs:
        return
    _pruned_dirs.add(cache_dir)
    cutoff = time.time() - _UNIT_CACHE_MAX_AGE
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return
    for name in names:
        if not (name.startswith("lspunit-") and name.endswith(".pkl")):
            continue
        path = os.path.join(cache_dir, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass  # raced/permission: stale entries are harmless
