"""Compiler front-end orchestration.

This module owns the source-to-analyzed-AST pipeline:

    include/import resolution -> stdlib composition -> lexing -> parsing
    -> strict import visibility -> semantic analysis

The CLI owns process concerns such as argument parsing, disk output, C emission,
and user-facing formatting. Tooling such as the LSP should enter through this
module instead of rebuilding a partial compiler pipeline.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import re
import sys
import time
from dataclasses import dataclass, field
from functools import cached_property

from . import pkg
from .analyzer.analyzer import Analyzer
from .analyzer.core import AnalyzedProgram
from .ast_nodes import Program
from .import_visibility import check_visibility
from .lexer import Lexer
from .parser.parser import Parser
from .tokens import Token

# Bump when the lexer/parser/AST changes so cached stdlib ASTs are invalidated.
_STDLIB_AST_VERSION = "2"

_BTRC_INCLUDE_RE = re.compile(r'^\s*#include\s+[<"]([^>"]+\.btrc)[>"]\s*$')
_BTRC_IMPORT_RE = re.compile(r'^\s*import\s+(.+?)\s*;?\s*$')

# Regex to extract class/interface names from btrc source (for skip-if-redefined)
_CLASS_NAME_RE = re.compile(
    r'^\s*(?:abstract\s+)?class\s+(\w+)(?:\s*<[^>\n]+>)?\s*'
    r'(?:extends\s+\w+(?:\s*<[^>\n]+>)?\s*)?'
    r'(?:implements\s+\w+(?:\s*,\s*\w+)*\s*)?\{',
    re.MULTILINE,
)
_INTERFACE_NAME_RE = re.compile(
    r'^\s*interface\s+(\w+)(?:\s*<[^>\n]+>)?\s*'
    r'(?:extends\s+\w+(?:\s*<[^>\n]+>)?\s*)?\{',
    re.MULTILINE,
)


@dataclass
class FrontendSource:
    """Resolved source bundle passed from include/stdlib resolution into parsing."""

    user_source: str
    source: str
    stdlib_source: str = ""
    provenance: list[str] = field(default_factory=list)
    source_positions: list[tuple[str, int]] = field(default_factory=list)
    graph: dict[str, set[str]] = field(default_factory=dict)
    strict_imports: bool = False

    @cached_property
    def _user_position_offset(self) -> int:
        """Index in ``source_positions`` where user-source line entries begin."""
        return len(self.source_positions) - (self.user_source.count("\n") + 1)

    def map_line(self, line: int, space: str = "combined") -> tuple[str, int] | None:
        """Translate a 1-based parse-space line to ``(source_file, native_line)``.

        ``space`` is "combined" (stdlib + user concatenation), "user" (resolved
        user source), or "stdlib" (composed stdlib source). Returns None when
        unmappable (out of range, or stdlib positions were not requested).
        """
        offset = self._user_position_offset
        if space == "combined":
            stdlib_lines = self.stdlib_source.count("\n") + 1 if self.stdlib_source else 0
            if line > stdlib_lines:
                space, line = "user", line - stdlib_lines
            else:
                space = "stdlib"
        if space == "stdlib":
            idx, lo, hi = line - 1, 0, offset
        else:
            idx, lo, hi = offset + line - 1, offset, len(self.source_positions)
        if line >= 1 and lo <= idx < hi:
            return self.source_positions[idx]
        return None

    def map_diag_line(self, line: int, *, diag_file: str | None = None,
                      split_spaces: bool = False) -> tuple[str, int] | None:
        """Resolve a diagnostic position to ``(source_file, native_line)``.

        ``split_spaces`` means stdlib and user code were parsed separately
        (stdlib AST cache), so each position is native to whichever space
        produced it; ``diag_file`` (decl ``source_file`` provenance) selects
        the stdlib space when it names a stdlib-composed file.
        """
        if not split_spaces:
            return self.map_line(line, "combined")
        offset = self._user_position_offset
        if diag_file is not None and any(
            f == diag_file for f, _ in self.source_positions[:offset]
        ):
            return self.map_line(line, "stdlib")
        return self.map_line(line, "user")


@dataclass
class StdlibSource:
    source: str
    source_positions: list[tuple[str, int]]


@dataclass
class FrontendParseResult:
    """Lexer/parser output. ``program`` is absent for token-only requests."""

    tokens: list[Token]
    program: Program | None = None
    user_program: Program | None = None


@dataclass
class FrontendResult:
    """Successful front-end compilation result."""

    source: str
    user_source: str
    stdlib_source: str
    tokens: list[Token]
    program: Program
    analyzed: AnalyzedProgram
    user_program: Program | None = None
    provenance: list[str] = field(default_factory=list)
    source_positions: list[tuple[str, int]] = field(default_factory=list)
    graph: dict[str, set[str]] = field(default_factory=dict)


class FrontendVisibilityError(Exception):
    """Strict-import visibility failures."""

    def __init__(self, errors: list[tuple[str, int, int]]):
        self.errors = errors
        super().__init__("strict import visibility failed")


class IncludeResolutionError(Exception):
    """Include/import resolution failed before lexing."""


def _timed(profile: dict[str, float] | None, label: str, start: float) -> None:
    if profile is not None:
        profile[label] = time.perf_counter() - start


def _cached_stdlib_decls(stdlib_source: str) -> list:
    """Parse the stdlib once and cache its AST declarations on disk.

    The stdlib is large and identical across programs, so re-lexing/re-parsing
    it every compile dominates build time. This caches the parsed declarations
    keyed by the exact stdlib source (which already reflects any user overrides),
    so subsequent builds skip straight to the user's code. Each CLI invocation
    is a fresh process, so the unpickled AST is never shared/mutated across runs.
    """
    key = hashlib.sha256(
        f"astv{_STDLIB_AST_VERSION}\n{stdlib_source}".encode()
    ).hexdigest()
    cache_dir = os.path.join(os.getcwd(), ".btrc-cache")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"stdlib-{key}.ast")
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass  # corrupt/incompatible cache: reparse below
    tokens = Lexer(stdlib_source, "<stdlib>").tokenize()
    decls = Parser(tokens).parse().declarations
    try:
        with open(path, "wb") as f:
            pickle.dump(decls, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass
    return decls


def _defined_stdlib_names(source: str) -> set[str]:
    return set(_CLASS_NAME_RE.findall(source)) | set(_INTERFACE_NAME_RE.findall(source))


def _get_stdlib_dir() -> str:
    """Get the absolute path to the stdlib directory."""
    # src/compiler/python/frontend.py -> src/stdlib/
    module_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(module_dir, "..", "..", "stdlib")


def _discover_stdlib_files() -> list[str]:
    """Scan src/stdlib/ and return .btrc filenames in include order.

    vector.btrc comes first (Map/Set/List/Array may depend on Vector), then
    list.btrc (depends on ListNode + Vector), then strings.btrc because
    higher-level stdlib modules use Strings.copy(). Process/fs come before
    app-level modules that construct shell and filesystem helpers.
    """
    stdlib_dir = _get_stdlib_dir()
    if not os.path.isdir(stdlib_dir):
        return []
    files = sorted(f for f in os.listdir(stdlib_dir) if f.endswith(".btrc"))
    priority = [
        "vector.btrc",
        "list.btrc",
        "strings.btrc",
        "platform.btrc",
        "process.btrc",
        "fs.btrc",
        "daemon.btrc",
        "ui.btrc",
    ]
    ordered = [f for f in priority if f in files]
    ordered += [f for f in files if f not in priority]
    return ordered


def get_stdlib_source(user_source: str = "") -> str:
    """Read stdlib sources, skipping classes/interfaces already defined by user."""
    return get_stdlib_source_mapped(user_source).source


def _stdlib_file_source(content: str, path: str) -> tuple[list[str], list[tuple[str, int]]]:
    lines = []
    source_positions = []
    for line_number, line in enumerate(content.split("\n"), start=1):
        if _BTRC_IMPORT_RE.match(line):
            continue
        lines.append(line)
        source_positions.append((path, line_number))
    return lines, source_positions


def get_stdlib_source_mapped(user_source: str = "") -> StdlibSource:
    """Read stdlib sources, skipping classes/interfaces already defined by user."""
    stdlib_dir = _get_stdlib_dir()
    user_names = _defined_stdlib_names(user_source)

    lines = []
    source_positions = []
    for fname in _discover_stdlib_files():
        fpath = os.path.join(stdlib_dir, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath) as f:
            content = f.read()
        file_names = _defined_stdlib_names(content)
        if file_names & user_names:
            continue
        file_lines, file_positions = _stdlib_file_source(content, fpath)
        lines.extend(file_lines)
        source_positions.extend(file_positions)
    return StdlibSource(source="\n".join(lines), source_positions=source_positions)


def _strip_btrc_imports(source: str) -> str:
    """Drop btrc import lines from auto-stdlib concatenation."""
    return "\n".join(
        line for line in source.split("\n")
        if not _BTRC_IMPORT_RE.match(line)
    )


def _find_stdlib_file(include_path: str) -> str | None:
    """Find a stdlib file by root-relative path or basename in subdirectories."""
    stdlib_dir = _get_stdlib_dir()
    stdlib_path = os.path.join(stdlib_dir, include_path)
    if os.path.exists(stdlib_path):
        return stdlib_path

    fname = os.path.basename(include_path)
    for entry in os.listdir(stdlib_dir):
        sub = os.path.join(stdlib_dir, entry)
        if os.path.isdir(sub):
            candidate = os.path.join(sub, fname)
            if os.path.exists(candidate):
                return candidate
    return None


def _resolve_include_path(include_path: str, source_dir: str) -> str:
    full_path = os.path.join(source_dir, include_path)
    if os.path.exists(full_path):
        return full_path

    stdlib_path = _find_stdlib_file(include_path)
    if stdlib_path is not None:
        return stdlib_path

    raise IncludeResolutionError(
        f"include file '{include_path}' not found\n"
        f"  searched: {source_dir}\n"
        f"  searched: {_get_stdlib_dir()}"
    )


def _strip_import_quotes(spec: str) -> str:
    spec = spec.strip()
    if spec.endswith(";"):
        spec = spec[:-1].strip()
    if len(spec) >= 2 and spec[0] in ('"', "'") and spec[-1] == spec[0]:
        return spec[1:-1]
    return spec


def _expand_brace_import(spec: str) -> list[str]:
    start = spec.find("{")
    end = spec.find("}", start + 1)
    if start < 0 or end < 0:
        return [spec]
    prefix = spec[:start]
    suffix = spec[end + 1:]
    result = []
    for item in spec[start + 1:end].split(","):
        name = item.strip()
        if name:
            result.append(prefix + name + suffix)
    return result


def _stdlib_import_paths(spec: str) -> list[str]:
    stdlib_dir = _get_stdlib_dir()
    if spec in ("std.*", "std.**"):
        return [os.path.join(stdlib_dir, fname) for fname in _discover_stdlib_files()]
    if not spec.startswith("std."):
        return []

    name = spec.removeprefix("std.")
    if not name.endswith(".btrc"):
        name = f"{name}.btrc"
    path = _find_stdlib_file(name)
    if path is None:
        raise IncludeResolutionError(
            f"stdlib import '{spec}' not found\n"
            f"  searched: {stdlib_dir}"
        )
    return [path]


def _relative_import_paths(spec: str, source_dir: str) -> list[str]:
    recursive = spec.endswith("/**")
    direct_glob = spec.endswith("/*")
    if recursive or direct_glob:
        base = spec[:-3] if recursive else spec[:-2]
        root = base if os.path.isabs(base) else os.path.join(source_dir, base)
        if not os.path.isdir(root):
            raise IncludeResolutionError(
                f"import directory '{spec}' not found\n"
                f"  searched: {root}"
            )
        matches: list[str] = []
        if recursive:
            for current, _dirs, files in os.walk(root):
                for fname in files:
                    if fname.endswith((".btrc", ".c")):
                        matches.append(os.path.join(current, fname))
        else:
            for fname in os.listdir(root):
                path = os.path.join(root, fname)
                if os.path.isfile(path) and fname.endswith((".btrc", ".c")):
                    matches.append(path)
        return sorted(matches)

    if os.path.isdir(spec if os.path.isabs(spec) else os.path.join(source_dir, spec)):
        root = spec if os.path.isabs(spec) else os.path.join(source_dir, spec)
        return sorted(
            os.path.join(root, fname)
            for fname in os.listdir(root)
            if fname.endswith((".btrc", ".c")) and os.path.isfile(os.path.join(root, fname))
        )

    path = spec if os.path.isabs(spec) else os.path.join(source_dir, spec)
    if os.path.exists(path):
        return [path]
    return [_resolve_include_path(spec, source_dir)]


def _import_paths(spec: str, source_dir: str) -> list[str]:
    paths: list[str] = []
    for expanded in _expand_brace_import(_strip_import_quotes(spec)):
        paths.extend(
            _stdlib_import_paths(expanded)
            or pkg.package_import_paths(expanded)
            or _relative_import_paths(expanded, source_dir)
        )
    return paths


def _resolve_traced(source: str, source_path: str, included: set[str],
                    graph: dict[str, set[str]]) -> list[tuple[str, str, int]]:
    """Recursively resolve includes/imports, preserving line provenance."""
    abs_path = os.path.abspath(source_path)
    source_dir = os.path.dirname(abs_path)
    graph.setdefault(abs_path, set())
    if abs_path in included:
        return []  # circular/repeat include guard; caller still recorded the edge
    included.add(abs_path)

    out: list[tuple[str, str, int]] = []
    for line_number, line in enumerate(source.split("\n"), start=1):
        m = _BTRC_INCLUDE_RE.match(line)
        if m:
            full_path = os.path.abspath(_resolve_include_path(m.group(1), source_dir))
            graph[abs_path].add(full_path)
            with open(full_path) as f:
                out.extend(_resolve_traced(f.read(), full_path, included, graph))
            continue

        m = _BTRC_IMPORT_RE.match(line)
        if m:
            for full_path in _import_paths(m.group(1), source_dir):
                abs_full = os.path.abspath(full_path)
                graph[abs_path].add(abs_full)
                if full_path.endswith(".c"):
                    out.append((f'#include "{abs_full}"', abs_path, line_number))
                    continue
                with open(full_path) as f:
                    out.extend(_resolve_traced(f.read(), full_path, included, graph))
            continue

        out.append((line, abs_path, line_number))

    return out


def _resolve_includes_mapped(
    source: str,
    source_path: str,
    included: set[str] | None = None,
    *,
    exit_on_error: bool = True,
) -> tuple[str, list[str], list[tuple[str, int]], dict[str, set[str]]]:
    """Resolve imports with both file and original-line mapping."""
    graph: dict[str, set[str]] = {}
    try:
        traced = _resolve_traced(
            source,
            source_path,
            set() if included is None else included,
            graph,
        )
    except IncludeResolutionError as e:
        if not exit_on_error:
            raise
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    resolved = "\n".join(text for text, _, _ in traced)
    provenance = [src for _, src, _ in traced]
    source_positions = [(src, line) for _, src, line in traced]
    return resolved, provenance, source_positions, graph


def resolve_includes(
    source: str,
    source_path: str,
    included: set[str] | None = None,
    *,
    exit_on_error: bool = True,
) -> str:
    """Recursively resolve btrc includes/imports by textual inclusion.

    Supported import forms:
      import std.{cli, fs, process}
      import std.*
      import ./file.btrc
      import ./directory/*
      import ./directory/**
    """
    try:
        resolved, _, _, _ = _resolve_includes_mapped(
            source,
            source_path,
            included,
            exit_on_error=False,
        )
    except IncludeResolutionError as e:
        if not exit_on_error:
            raise
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    return resolved


def resolve_includes_traced(
    source: str,
    source_path: str,
    *,
    exit_on_error: bool = True,
):
    """Like resolve_includes, but include provenance and the import graph."""
    resolved, provenance, _, graph = _resolve_includes_mapped(
        source,
        source_path,
        exit_on_error=exit_on_error,
    )
    return resolved, provenance, graph


def resolve_frontend_source(
    source: str,
    source_path: str,
    *,
    include_stdlib: bool = True,
    strict_imports: bool = False,
    map_stdlib_positions: bool = False,
    profile: dict[str, float] | None = None,
) -> FrontendSource:
    """Resolve includes/imports and compose the stdlib according to CLI rules."""
    start = time.perf_counter()
    user_source, provenance, source_positions, graph = _resolve_includes_mapped(
        source,
        source_path,
        exit_on_error=False,
    )
    _timed(profile, "resolve_includes", start)

    stdlib_source = ""
    stdlib_positions: list[tuple[str, int]] = []
    if include_stdlib and not strict_imports:
        start = time.perf_counter()
        if map_stdlib_positions:
            stdlib = get_stdlib_source_mapped(user_source)
            stdlib_source = stdlib.source
            stdlib_positions = stdlib.source_positions
        else:
            stdlib_source = get_stdlib_source(user_source)
        _timed(profile, "stdlib_include", start)

    full_source = (stdlib_source + "\n" + user_source) if stdlib_source else user_source
    return FrontendSource(
        user_source=user_source,
        source=full_source,
        stdlib_source=stdlib_source,
        provenance=provenance,
        source_positions=stdlib_positions + source_positions,
        graph=graph,
        strict_imports=strict_imports,
    )


def uses_stdlib_ast_cache(
    frontend_source: FrontendSource,
    *,
    use_ast_cache: bool = True,
    emit_tokens: bool = False,
    emit_ast: bool = False,
    debug: bool = False,
    parse: bool = True,
) -> bool:
    """True when stdlib and user code are parsed separately (cached stdlib AST),
    i.e. parse positions are native to each part rather than combined-source."""
    return (
        parse and bool(frontend_source.stdlib_source) and use_ast_cache
        and not emit_tokens and not emit_ast and not debug
        and not frontend_source.strict_imports
    )


def _stamp_decl_files(decls, frontend_source: FrontendSource, space: str) -> None:
    """Record native-file provenance on top-level decls (feeds ``Diag.file``)."""
    for decl in decls:
        pos = frontend_source.map_line(getattr(decl, "line", 0), space)
        if pos is not None:
            decl.source_file = pos[0]


def lex_parse_frontend_source(
    frontend_source: FrontendSource,
    filename: str,
    *,
    use_ast_cache: bool = True,
    emit_tokens: bool = False,
    emit_ast: bool = False,
    debug: bool = False,
    parse: bool = True,
    profile: dict[str, float] | None = None,
) -> FrontendParseResult:
    """Lex and parse a resolved source bundle.

    The stdlib AST cache is a parse optimization only. Token-only/debug/AST dump
    modes lex the exact full source to preserve CLI behavior and line mapping.
    """
    use_cached_stdlib_ast = uses_stdlib_ast_cache(
        frontend_source,
        use_ast_cache=use_ast_cache,
        emit_tokens=emit_tokens,
        emit_ast=emit_ast,
        debug=debug,
        parse=parse,
    )

    if use_cached_stdlib_ast:
        start = time.perf_counter()
        tokens = Lexer(frontend_source.user_source, filename).tokenize()
        _timed(profile, "lex", start)

        start = time.perf_counter()
        user_program = Parser(tokens).parse()
        stdlib_decls = _cached_stdlib_decls(frontend_source.stdlib_source)
        _stamp_decl_files(user_program.declarations, frontend_source, "user")
        _stamp_decl_files(stdlib_decls, frontend_source, "stdlib")
        program = Program(declarations=stdlib_decls + user_program.declarations)
        _timed(profile, "parse", start)
    else:
        start = time.perf_counter()
        tokens = Lexer(frontend_source.source, filename).tokenize()
        _timed(profile, "lex", start)
        if not parse:
            return FrontendParseResult(tokens=tokens)

        start = time.perf_counter()
        program = Parser(tokens).parse()
        user_program = program if not frontend_source.stdlib_source else None
        _stamp_decl_files(program.declarations, frontend_source, "combined")
        _timed(profile, "parse", start)

    if frontend_source.strict_imports:
        errors = check_visibility(
            program, frontend_source.provenance, frontend_source.graph
        )
        if errors:
            raise FrontendVisibilityError(errors)

    return FrontendParseResult(tokens=tokens, program=program, user_program=user_program)


def analyze_frontend_program(
    program: Program,
    *,
    profile: dict[str, float] | None = None,
) -> AnalyzedProgram:
    """Run semantic analysis for a parsed program."""
    start = time.perf_counter()
    analyzed = Analyzer().analyze(program)
    _timed(profile, "analyze", start)
    return analyzed


def compile_frontend(
    source: str,
    source_path: str,
    *,
    filename: str | None = None,
    include_stdlib: bool = True,
    strict_imports: bool = False,
    use_ast_cache: bool = True,
    map_stdlib_positions: bool = False,
    debug: bool = False,
    profile: dict[str, float] | None = None,
) -> FrontendResult:
    """Compile source through semantic analysis without generating C."""
    filename = filename or os.path.basename(source_path)
    frontend_source = resolve_frontend_source(
        source,
        source_path,
        include_stdlib=include_stdlib,
        strict_imports=strict_imports,
        map_stdlib_positions=map_stdlib_positions,
        profile=profile,
    )
    parsed = lex_parse_frontend_source(
        frontend_source,
        filename,
        use_ast_cache=use_ast_cache,
        debug=debug,
        profile=profile,
    )
    if parsed.program is None:
        raise AssertionError("front-end parse result unexpectedly omitted program")
    analyzed = analyze_frontend_program(parsed.program, profile=profile)
    return FrontendResult(
        source=frontend_source.source,
        user_source=frontend_source.user_source,
        stdlib_source=frontend_source.stdlib_source,
        tokens=parsed.tokens,
        program=parsed.program,
        analyzed=analyzed,
        user_program=parsed.user_program,
        provenance=frontend_source.provenance,
        source_positions=frontend_source.source_positions,
        graph=frontend_source.graph,
    )
