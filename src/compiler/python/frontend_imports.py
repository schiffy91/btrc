"""Filesystem resolution for btrc include and import directives."""

from __future__ import annotations

import os
import sys

from . import pkg
from .frontend.dependencies import SourceDependencyGraph
from .frontend_c_imports import c_include_directive as _c_include_directive
from .frontend_limits import ResolutionBudget
from .frontend_path_scan import scan_import_directory
from .frontend_stdlib import (
    _discover_stdlib_files,
    _find_stdlib_file,
    _get_stdlib_dir,
)
from .import_scan import scan_directives
from .pkg import IncludeResolutionError
from .source_io import SourceReadError, read_source


def _resolve_include_path(include_path: str, source_dir: str) -> str:
    full_path = os.path.join(source_dir, include_path)
    if os.path.exists(full_path):
        return full_path

    stdlib_path = _find_stdlib_file(include_path)
    if stdlib_path is not None:
        return stdlib_path

    raise IncludeResolutionError(
        f"include file '{include_path}' not found\n  searched: {source_dir}\n  searched: {_get_stdlib_dir()}"
    )


def _stdlib_glob_paths() -> list[str]:
    stdlib_dir = _get_stdlib_dir()
    return [os.path.join(stdlib_dir, fname) for fname in _discover_stdlib_files()]


def _stdlib_module_path(name: str) -> str:
    """Resolve a single ``std.<name>`` module to its stdlib file path."""
    stdlib_dir = _get_stdlib_dir()
    fname = name if name.endswith(".btrc") else f"{name}.btrc"
    path = _find_stdlib_file(fname)
    if path is None:
        raise IncludeResolutionError(f"stdlib import 'std.{name}' not found\n  searched: {stdlib_dir}")
    return path


def _relative_import_paths(spec: str, source_dir: str) -> list[str]:
    recursive = spec.endswith("/**")
    direct_glob = spec.endswith("/*")
    if recursive or direct_glob:
        base = spec[:-3] if recursive else spec[:-2]
        root = base if os.path.isabs(base) else os.path.join(source_dir, base)
        if not os.path.isdir(root):
            raise IncludeResolutionError(f"import directory '{spec}' not found\n  searched: {root}")
        return scan_import_directory(root, recursive=recursive)

    if os.path.isdir(spec if os.path.isabs(spec) else os.path.join(source_dir, spec)):
        root = spec if os.path.isabs(spec) else os.path.join(source_dir, spec)
        return scan_import_directory(root, recursive=False)

    path = spec if os.path.isabs(spec) else os.path.join(source_dir, spec)
    if os.path.exists(path):
        return [path]
    return [_resolve_include_path(spec, source_dir)]


def import_spec_paths(spec, source_dir: str) -> list[str]:
    """Resolve a parsed ``import_spec`` AST node to filesystem path(s).

    All path RESOLUTION still lives in the helpers below (stdlib/package/
    relative); only the *parsing* of the spec moved into the parser, so brace
    expansion and quote stripping are already done by the time we get here.
    """
    from .ast_nodes import (
        PackagePath,
        QuotedPath,
        RelativePath,
        StdGlob,
        StdModules,
    )

    if isinstance(spec, StdGlob):
        return _stdlib_glob_paths()
    if isinstance(spec, StdModules):
        return [_stdlib_module_path(name) for name in spec.names]
    if isinstance(spec, PackagePath):
        dotted = ".".join(spec.segments)
        return pkg.package_import_paths(dotted) or _relative_import_paths(dotted, source_dir)
    if isinstance(spec, (RelativePath, QuotedPath)):
        path = spec.path
        return pkg.package_import_paths(path) or _relative_import_paths(path, source_dir)
    raise IncludeResolutionError(f"unsupported import spec: {spec!r}")


def _read_import_source(path: str) -> str:
    try:
        return read_source(path)
    except SourceReadError as error:
        raise IncludeResolutionError(str(error)) from error


def _inline_paths(
    paths: list[str],
    abs_path: str,
    line_number: int,
    included: set[str],
    graph: SourceDependencyGraph,
    out: list[tuple[str, str, int]],
    budget: ResolutionBudget,
    depth: int,
) -> None:
    """Splice resolved import/include targets into ``out`` (recursing)."""
    for full_path in paths:
        abs_full = os.path.abspath(full_path)
        graph.add_import(abs_path, abs_full)
        if full_path.endswith(".c"):
            identity = os.path.normcase(os.path.realpath(abs_full))
            if identity in included:
                continue
            budget.enter("", abs_full, depth)
            included.add(identity)
            out.append((_c_include_directive(abs_full), abs_path, line_number))
            continue
        out.extend(
            _resolve_traced(
                _read_import_source(full_path),
                full_path,
                included,
                graph,
                budget,
                depth,
            )
        )


def _resolve_traced(
    source: str,
    source_path: str,
    included: set[str],
    graph: SourceDependencyGraph,
    budget: ResolutionBudget,
    depth: int,
) -> list[tuple[str, str, int]]:
    """Recursively resolve includes/imports, preserving line provenance.

    Directives are located by the lexer/parser (``scan_directives``), not by a
    raw line regex, so imports inside comments or strings are never resolved.
    Each directive's line range is replaced by the imported declarations; every
    other line is emitted verbatim with its native provenance.
    """
    abs_path = os.path.abspath(source_path)
    identity = os.path.normcase(os.path.realpath(abs_path))
    source_dir = os.path.dirname(abs_path)
    graph.ensure_source(abs_path)
    if identity in included:
        return []  # circular/repeat include guard; caller still recorded the edge
    budget.enter(source, abs_path, depth)
    included.add(identity)

    directives = scan_directives(source)
    by_start = {d.start: d for d in directives}
    covered = {ln for d in directives for ln in range(d.start, d.end + 1)}

    out: list[tuple[str, str, int]] = []
    for line_number, line in enumerate(source.split("\n"), start=1):
        directive = by_start.get(line_number)
        if directive is not None:
            if directive.kind == "btrc_include":
                full = os.path.abspath(_resolve_include_path(directive.payload, source_dir))
                graph.add_include(abs_path, full)
                out.extend(
                    _resolve_traced(
                        _read_import_source(full),
                        full,
                        included,
                        graph,
                        budget,
                        depth + 1,
                    )
                )
            else:  # import
                paths = import_spec_paths(directive.payload, source_dir)
                _inline_paths(
                    paths,
                    abs_path,
                    line_number,
                    included,
                    graph,
                    out,
                    budget,
                    depth + 1,
                )
            continue
        if line_number in covered:
            continue  # continuation line of a multi-line directive
        out.append((line, abs_path, line_number))

    return out


def _resolve_includes_mapped(
    source: str,
    source_path: str,
    included: set[str] | None = None,
    *,
    exit_on_error: bool = True,
) -> tuple[str, list[str], list[tuple[str, int]], SourceDependencyGraph]:
    """Resolve imports with both file and original-line mapping."""
    graph = SourceDependencyGraph()
    try:
        traced = _resolve_traced(
            source,
            source_path,
            set() if included is None else included,
            graph,
            ResolutionBudget(),
            0,
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
