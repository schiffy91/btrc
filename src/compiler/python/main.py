#!/usr/bin/env python3
"""btrc — a language that transpiles to C.

Usage: python main.py <input.btrc> [-o output.c] [--emit-ast] [--emit-tokens]
"""

import contextlib
import os
import sys
import time

from . import cli_archive, cli_diagnostics, cli_io, cli_options, pkg
from . import frontend as _frontend
from .disk_cache import get_cached
from .disk_cache import store as cache_store
from .frontend import (
    FrontendVisibilityError,
    IncludeResolutionError,
    analyze_frontend_program,
    get_stdlib_source,
    lex_parse_frontend_source,
    resolve_frontend_source,
    uses_stdlib_ast_cache,
)
from .ir.emitter import CEmitter
from .ir.gen.errors import CodegenError
from .ir.gen.generator import generate_ir
from .ir.optimizer import optimize
from .lexer import LexerError
from .parser.core import ParseError
from .source_provenance import make_ir_source_maps

_STDLIB_AST_VERSION = _frontend._STDLIB_AST_VERSION
_cached_stdlib_decls = _frontend._cached_stdlib_decls
_discover_stdlib_files = _frontend._discover_stdlib_files
_find_stdlib_file = _frontend._find_stdlib_file
import_spec_paths = _frontend.import_spec_paths
resolve_includes = _frontend.resolve_includes
resolve_includes_traced = _frontend.resolve_includes_traced
Analyzer = _frontend.Analyzer
_build_stdlib_archive = cli_archive.build_stdlib_archive
_partition_against_stdlib = cli_archive.partition_against_stdlib
_codegen_error_exit = cli_diagnostics.codegen_error_exit
_DiagnosticPrinter = cli_diagnostics.DiagnosticPrinter
_dump_ir = cli_diagnostics.dump_ir
_format_error = cli_diagnostics.format_error
_print_profile = cli_diagnostics.print_profile
_syntax_error_exit = cli_diagnostics.syntax_error_exit
_PrintStdlibDir = cli_options.PrintStdlibDir
build_argument_parser = cli_options.build_argument_parser
__all__ = ("_PrintStdlibDir", "_format_error", "get_stdlib_source", "main")


def main():
    # Status lines and analyzer diagnostics contain non-ASCII (e.g. the "→"
    # arrow). On Windows the default console encoding is cp1252, which can't
    # encode them and aborts the process mid-transpile. Force UTF-8 on the
    # standard streams so output is portable; a no-op where it's already UTF-8.
    for _stream in (sys.stdout, sys.stderr):
        _reconfig = getattr(_stream, "reconfigure", None)
        if _reconfig is not None:
            with contextlib.suppress(ValueError, OSError):
                _reconfig(encoding="utf-8")
    # Deeply nested expressions recurse through the full precedence chain;
    # lift the limit before parsing (the analyzer raises it too, post-parse).
    sys.setrecursionlimit(40000)
    argparser = build_argument_parser()
    args = argparser.parse_args()
    prof: dict[str, float] = {}

    # --build-stdlib: compile the whole stdlib into a linkable archive and exit.
    # No input program; deliberately skips dead-code elimination so the archive
    # is a complete library (binaries prune unused code at link time).
    if args.build_stdlib is not None:
        _build_stdlib_archive(args.build_stdlib)
        return

    if not args.input:
        argparser.error("the following arguments are required: input")

    emit_only = any([args.emit_tokens, args.emit_ast, args.emit_ir, args.emit_optimized_ir])
    out_path = None if emit_only else cli_io.output_path(args.input, args.output)

    # Resolve package dependencies (btrc.toml) governing this input, if any.
    try:
        pkg.configure_for(args.input, refresh=args.fetch)
    except IncludeResolutionError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    source = cli_io.read_input(args.input)

    try:
        frontend_source = resolve_frontend_source(
            source,
            args.input,
            include_stdlib=not args.no_stdlib,
            strict_imports=args.strict_imports,
            map_stdlib_positions=True,
            profile=prof,
        )
    except IncludeResolutionError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    input_source = source
    source = frontend_source.source

    filename = os.path.basename(args.input)

    # Check disk cache (only for default compilation, not debug/emit modes).
    # --stdlib produces different output for the same source (program-only,
    # partitioned against the archive), so it must not share the default cache.
    import_mode = "strict" if args.strict_imports else "relaxed"
    cache_source = f"import-mode={import_mode}\0{source}"
    cache_source_identity = frontend_source.cache_identity()
    use_cache = (
        not args.no_cache
        and args.stdlib is None
        and not args.freestanding
        and not args.no_dce
        and not any([args.emit_tokens, args.emit_ast, args.emit_ir, args.emit_optimized_ir, args.debug, args.profile])
    )
    if use_cache:
        cached = get_cached(
            cache_source,
            input_path=args.input,
            source_identity=cache_source_identity,
        )
        if cached is not None:
            assert out_path is not None
            cli_io.write_output(out_path, cached)
            print(f"Transpiled {args.input} → {out_path} (cached)")
            return

    # --debug forces combined parsing (no split stdlib AST cache) so every node's
    # line is in one coordinate space that frontend_source.map_line can translate
    # back to (file, native_line) for #line directives.
    use_ast_cache = bool(frontend_source.stdlib_source) and not args.no_cache and not args.debug
    split_source_spaces = uses_stdlib_ast_cache(
        frontend_source,
        use_ast_cache=use_ast_cache,
        emit_tokens=args.emit_tokens,
        emit_ast=args.emit_ast,
        debug=args.debug,
        parse=not args.emit_tokens,
    )
    diag_printer = _DiagnosticPrinter(
        frontend_source,
        args.input,
        input_source,
        split_spaces=split_source_spaces,
    )
    try:
        parsed = lex_parse_frontend_source(
            frontend_source,
            filename,
            use_ast_cache=use_ast_cache,
            emit_tokens=args.emit_tokens,
            emit_ast=args.emit_ast,
            debug=args.debug,
            parse=not args.emit_tokens,
            profile=prof,
        )
    except (LexerError, ParseError) as e:
        _syntax_error_exit(diag_printer, e)
    except RecursionError:
        print("error: expression or declaration nested too deeply to compile", file=sys.stderr)
        sys.exit(1)
    except FrontendVisibilityError as e:
        for msg, line, col in e.errors:
            diag_printer.emit(msg, line, col)
        sys.exit(1)

    if args.emit_tokens:
        for tok in parsed.tokens:
            print(tok)
        return

    program = parsed.program
    if program is None:
        raise AssertionError("front-end parse result unexpectedly omitted program")

    if args.emit_ast:
        import pprint

        pprint.pprint(program)
        return

    analyzed = analyze_frontend_program(program, profile=prof)

    # Analyzer diagnostics are structured (message, line, col, file); positions
    # are mapped to native per-file locations. Entries appended to the plain
    # errors/warnings lists without a matching Diag print unformatted.
    error_diags = [d for d in analyzed.diags if d.severity == "error"]
    if analyzed.errors or error_diags:
        for d in error_diags:
            diag_printer.emit(d.message, d.line, d.col, diag_file=d.file)
        for err in analyzed.errors[len(error_diags) :]:
            print(f"error: {err}", file=sys.stderr)
        sys.exit(1)

    # Display warnings (non-fatal)
    warning_diags = [d for d in analyzed.diags if d.severity == "warning"]
    for d in warning_diags:
        diag_printer.emit(d.message, d.line, d.col, severity="warning", diag_file=d.file)
    for warn in analyzed.warnings[len(warning_diags) :]:
        print(f"warning: {warn}", file=sys.stderr)

    # Code generation: AST → IR → optimize → C text
    _t = time.perf_counter()

    line_map, declaration_line_map = make_ir_source_maps(
        frontend_source,
        split_spaces=split_source_spaces,
    )

    try:
        ir_module = generate_ir(
            analyzed,
            debug=args.debug,
            source_file=filename,
            freestanding=args.freestanding,
            line_map=line_map,
            declaration_line_map=declaration_line_map,
        )
    except CodegenError as error:
        _codegen_error_exit(error)
    prof["ir_gen"] = time.perf_counter() - _t

    if args.emit_ir:
        _dump_ir(ir_module)
        return

    # Archive-consumer compiles (--stdlib) let the archive be the optimization
    # boundary: partition_for_archive drops what the archive provides by matching
    # the manifest's verbatim sections, so DCE here (which rewrites those
    # sections) must not run. --no-dce disables elimination for any compile.
    _t = time.perf_counter()
    run_dce = not args.no_dce and args.stdlib is None
    try:
        ir_module = optimize(ir_module, dce=run_dce)
    except CodegenError as error:
        _codegen_error_exit(error)
    prof["optimize"] = time.perf_counter() - _t

    if args.emit_optimized_ir:
        _dump_ir(ir_module)
        return

    # --stdlib: drop everything the prebuilt archive already provides, leaving
    # program-only C that #includes btrc_stdlib.h and links the archive.
    if args.stdlib is not None:
        _partition_against_stdlib(ir_module, program, args.stdlib)

    # Determine the output path up front so debug builds can stamp #line resets
    # with the real generated .c path (synthesized code maps there, not to btrc).
    assert out_path is not None
    if args.debug:
        ir_module.debug_cfile = os.path.abspath(out_path)

    _t = time.perf_counter()
    c_source = CEmitter().emit(ir_module)
    prof["emit"] = time.perf_counter() - _t

    # Store in disk cache
    if use_cache:
        with contextlib.suppress(OSError, UnicodeError):
            cache_store(
                cache_source,
                c_source,
                input_path=args.input,
                source_identity=cache_source_identity,
            )

    if args.profile:
        _print_profile(prof, len(source))

    cli_io.write_output(out_path, c_source)

    # Freestanding output references "btrc_rt.h"; drop a reference copy next to
    # it so the result compiles unchanged on a hosted toolchain and documents
    # the full retarget surface for kernel/embedded use. Never clobber an
    # existing (possibly user-customized) header.
    if args.freestanding:
        rt_path = os.path.join(os.path.dirname(out_path) or ".", "btrc_rt.h")
        from .freestanding import RUNTIME_HEADER

        if cli_io.write_output_if_missing(rt_path, RUNTIME_HEADER):
            print(f"Wrote freestanding runtime seam → {rt_path}")

    print(f"Transpiled {args.input} → {out_path}")


if __name__ == "__main__":  # pragma: no cover
    main()
