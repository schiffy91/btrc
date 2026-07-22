"""Compiler front-end orchestration from source bundle through analysis."""

from __future__ import annotations

import os
import time

from .analyzer.analyzer import Analyzer
from .analyzer.core import AnalyzedProgram
from .ast_nodes import Program
from .frontend_imports import (
    IncludeResolutionError,
    _resolve_includes_mapped,
    import_spec_paths,
    resolve_includes,
    resolve_includes_traced,
)
from .frontend_limits import check_combined_source_size
from .frontend_models import (
    FrontendParseResult,
    FrontendResult,
    FrontendSource,
    FrontendVisibilityError,
)
from .frontend_stdlib import (
    _STDLIB_AST_VERSION,
    _cached_stdlib_decls,
    _defined_stdlib_names,
    _discover_stdlib_files,
    _find_stdlib_file,
    _get_stdlib_dir,
    get_stdlib_source,
    get_stdlib_source_mapped,
)
from .import_visibility import ImportVisibilityChecker
from .lexer import Lexer
from .parser.parser import Parser
from .source_provenance import compiler_stdlib_source, stamp_nested_declaration_sources

__all__ = [
    "_STDLIB_AST_VERSION",
    "Analyzer",
    "FrontendParseResult",
    "FrontendResult",
    "FrontendSource",
    "FrontendVisibilityError",
    "IncludeResolutionError",
    "_cached_stdlib_decls",
    "_defined_stdlib_names",
    "_discover_stdlib_files",
    "_find_stdlib_file",
    "_get_stdlib_dir",
    "analyze_frontend_program",
    "compile_frontend",
    "get_stdlib_source",
    "get_stdlib_source_mapped",
    "import_spec_paths",
    "lex_parse_frontend_source",
    "resolve_frontend_source",
    "resolve_includes",
    "resolve_includes_traced",
    "uses_stdlib_ast_cache",
]


def _timed(profile: dict[str, float] | None, label: str, start: float) -> None:
    if profile is not None:
        profile[label] = time.perf_counter() - start


def resolve_frontend_source(
    source: str,
    source_path: str,
    *,
    include_stdlib: bool = True,
    strict_imports: bool = True,
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

    check_combined_source_size(stdlib_source, "\n" if stdlib_source else "", user_source)
    full_source = (stdlib_source + "\n" + user_source) if stdlib_source else user_source
    return FrontendSource(
        user_source=user_source,
        source=full_source,
        stdlib_source=stdlib_source,
        provenance=provenance,
        source_positions=stdlib_positions + source_positions,
        graph=graph,
        strict_imports=strict_imports,
        root_source_path=os.path.realpath(source_path),
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
        parse
        and bool(frontend_source.stdlib_source)
        and use_ast_cache
        and not emit_tokens
        and not emit_ast
        and not debug
        and not frontend_source.strict_imports
    )


def _stamp_decl_files(decls, frontend_source: FrontendSource, space: str) -> None:
    """Record native-file provenance on top-level decls (feeds ``Diag.file``)."""
    stdlib_line_count = frontend_source.stdlib_source.count("\n") + 1 if frontend_source.stdlib_source else 0
    for decl in decls:
        pos = frontend_source.map_line(getattr(decl, "line", 0), space)
        compiler_stdlib = space == "stdlib" or (
            space == "combined" and stdlib_line_count and getattr(decl, "line", 0) <= stdlib_line_count
        )
        if pos is not None and _compiler_resolved_stdlib_import(
            frontend_source,
            pos[0],
        ):
            compiler_stdlib = True
        if pos is not None:
            decl.source_file = compiler_stdlib_source(pos[0]) if compiler_stdlib else pos[0]
        elif compiler_stdlib:
            # Provenance matters even without detailed stdlib diagnostic mapping.
            decl.source_file = compiler_stdlib_source()
        stamp_nested_declaration_sources(decl)


def _compiler_resolved_stdlib_import(
    frontend_source: FrontendSource,
    path: str,
) -> bool:
    """Authenticate canonical stdlib files reached through the import graph."""
    canonical = os.path.realpath(path)
    if canonical == frontend_source.root_source_path:
        return False
    stdlib_root = os.path.realpath(_get_stdlib_dir())
    try:
        if os.path.commonpath((canonical, stdlib_root)) != stdlib_root:
            return False
    except (OSError, ValueError):
        return False
    return frontend_source.graph.has_target(canonical)


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
        errors = ImportVisibilityChecker(
            program,
            frontend_source.provenance,
            frontend_source.graph,
        ).check()
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
    strict_imports: bool = True,
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
        source_bundle=frontend_source,
        user_program=parsed.user_program,
        provenance=frontend_source.provenance,
        source_positions=frontend_source.source_positions,
        graph=frontend_source.graph,
    )
