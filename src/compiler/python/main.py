#!/usr/bin/env python3
"""btrc — a language that transpiles to C.

Usage: python main.py <input.btrc> [-o output.c] [--emit-ast] [--emit-tokens]
"""

import argparse
import os
import sys
import time

from . import frontend as _frontend
from . import pkg
from .disk_cache import get_cached
from .disk_cache import store as cache_store
from .frontend import (
    FrontendVisibilityError,
    IncludeResolutionError,
    _get_stdlib_dir,
    analyze_frontend_program,
    get_stdlib_source,
    lex_parse_frontend_source,
    resolve_frontend_source,
    uses_stdlib_ast_cache,
)
from .ir.emitter import CEmitter
from .ir.gen.generator import generate_ir
from .ir.optimizer import optimize
from .lexer import Lexer, LexerError
from .parser.core import ParseError
from .parser.parser import Parser

_STDLIB_AST_VERSION = _frontend._STDLIB_AST_VERSION
_cached_stdlib_decls = _frontend._cached_stdlib_decls
_discover_stdlib_files = _frontend._discover_stdlib_files
_find_stdlib_file = _frontend._find_stdlib_file
import_spec_paths = _frontend.import_spec_paths
resolve_includes = _frontend.resolve_includes
resolve_includes_traced = _frontend.resolve_includes_traced
Analyzer = _frontend.Analyzer


def _format_error(source: str, filename: str, message: str,
                  line: int, col: int) -> str:
    """Format an error with source context and caret."""
    lines = source.split('\n')
    if line < 1 or line > len(lines):
        return f"error: {message}\n --> {filename}:{line}:{col}"
    source_line = lines[line - 1]
    width = len(str(line))
    pad = " " * width
    caret_offset = max(col - 1, 0)
    caret = " " * caret_offset + "^"
    return (
        f"error: {message}\n"
        f" {pad}--> {filename}:{line}:{col}\n"
        f" {pad} |\n"
        f" {line} | {source_line}\n"
        f" {pad} | {caret}"
    )


class _DiagnosticPrinter:
    """Render diagnostics at native per-file positions.

    Parse/analysis positions live in a parse space (combined stdlib+user
    source, or separate spaces when the stdlib AST cache is used); the
    frontend's source-position map translates them back to the originating
    file, so the header and the quoted line both come from that file.
    """

    def __init__(self, frontend_source, input_path: str, input_source: str,
                 split_spaces: bool):
        self.frontend_source = frontend_source
        self.input_path = input_path
        self.split_spaces = split_spaces
        self._sources = {os.path.abspath(input_path): input_source}

    def _source_for(self, path: str) -> str:
        key = os.path.abspath(path)
        if key not in self._sources:
            try:
                with open(key) as f:
                    self._sources[key] = f.read()
            except OSError:
                self._sources[key] = ""
        return self._sources[key]

    def emit(self, message: str, line: int, col: int, *,
             severity: str = "error", diag_file: str | None = None) -> None:
        loc = self.frontend_source.map_diag_line(
            line, diag_file=diag_file, split_spaces=self.split_spaces)
        if loc is None:
            display, native_line, text = os.path.basename(self.input_path), line, ""
        else:
            path, native_line = loc
            text = self._source_for(path)
            display = (self.input_path
                       if os.path.abspath(path) == os.path.abspath(self.input_path)
                       else os.path.normpath(path))
        out = _format_error(text, display, message, native_line, col)
        if severity != "error":
            out = out.replace("error:", f"{severity}:", 1)
        print(out, file=sys.stderr)


def _syntax_error_exit(printer: _DiagnosticPrinter, e):
    """Print a lexer/parser error with source context, then exit(1)."""
    printer.emit(str(e).removesuffix(f" at {e.line}:{e.col}"), e.line, e.col)
    sys.exit(1)


def _print_profile(prof: dict, source_len: int) -> None:
    """Print a per-phase timing breakdown to stderr."""
    total = sum(prof.values()) or 1e-9
    print("--- btrc profile ---", file=sys.stderr)
    for label, secs in prof.items():
        pct = 100.0 * secs / total
        print(f"  {label:<18} {secs * 1000:8.2f} ms  {pct:5.1f}%", file=sys.stderr)
    print(f"  {'total':<18} {total * 1000:8.2f} ms  ({source_len} chars resolved)",
          file=sys.stderr)


def _dump_ir(module):
    """Print a canonical IR dump for debugging."""
    print(f"# IRModule: {len(module.enum_defs)} enums, "
          f"{len(module.struct_defs)} structs, "
          f"{len(module.function_defs)} functions, "
          f"{len(module.helper_decls)} helpers")
    for enum in module.enum_defs:
        vals = ", ".join(
            f"{v.name}={v.value}" if v.value else v.name
            for v in enum.values)
        print(f"enum {enum.name} {{ {vals} }}")
    for struct in module.struct_defs:
        fields = ", ".join(f"{f.c_type} {f.name}" for f in struct.fields)
        print(f"struct {struct.name} {{ {fields} }}")
    for func in module.function_defs:
        params = ", ".join(f"{p.c_type} {p.name}" for p in func.params)
        print(f"fn {func.name}({params}) -> {func.return_type}")


class _PrintStdlibDir(argparse.Action):
    """--stdlib-dir: print the bundled stdlib path and exit, like --version.

    Lets tooling locate the compiler's stdlib (e.g. to diff a vendored copy)
    without knowing where the package keeps it, the way `gcc -print-file-name`
    or `rustc --print sysroot` report their own data dirs.
    """

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, default=argparse.SUPPRESS, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        print(os.path.abspath(_get_stdlib_dir()))
        parser.exit()


def _build_stdlib_archive(out_dir: str) -> None:
    """Compile the entire stdlib into a linkable archive in ``out_dir``.

    Runs the normal front-end over every stdlib source, but deliberately skips
    dead-code elimination: an archive is a complete library, not a program, so
    nothing is "unreachable". Consumers prune what they don't use at link time
    (``-ffunction-sections`` / ``--gc-sections``).
    """
    from .stdlib_archive import build_archive

    stdlib_source = get_stdlib_source("")
    if not stdlib_source.strip():
        print("error: no stdlib sources found", file=sys.stderr)
        sys.exit(1)

    try:
        tokens = Lexer(stdlib_source, "<stdlib>").tokenize()
        program = Parser(tokens).parse()
    except (LexerError, ParseError) as e:
        msg = str(e).removesuffix(f" at {e.line}:{e.col}")
        print(_format_error(stdlib_source, "<stdlib>", msg, e.line, e.col),
              file=sys.stderr)
        sys.exit(1)

    analyzed = analyze_frontend_program(program)
    if analyzed.errors:
        for err in analyzed.errors:
            print(f"error: {err}", file=sys.stderr)
        sys.exit(1)

    ir_module = generate_ir(analyzed, debug=False, source_file="<stdlib>")
    build_archive(out_dir, ir_module)
    print(f"Built stdlib archive → {out_dir}")


def main():
    # Deeply nested expressions recurse through the full precedence chain;
    # lift the limit before parsing (the analyzer raises it too, post-parse).
    sys.setrecursionlimit(40000)
    argparser = argparse.ArgumentParser(description="btrc transpiler")
    argparser.add_argument("input", nargs="?", help="Input .btrc file")
    argparser.add_argument("--stdlib-dir", action=_PrintStdlibDir,
                           help="Print the bundled stdlib directory and exit")
    argparser.add_argument("--build-stdlib", metavar="DIR",
                           help="Compile the stdlib into a linkable archive "
                                "(btrc_stdlib.h/.c/.manifest) in DIR and exit")
    argparser.add_argument("--stdlib", metavar="DIR",
                           help="Reference a prebuilt stdlib archive in DIR: emit "
                                "program-only C that #includes btrc_stdlib.h and "
                                "links the archive, instead of inlining the stdlib")
    argparser.add_argument("-o", "--output", help="Output .c file (default: <input>.c)")
    argparser.add_argument("--emit-tokens", action="store_true", help="Print token stream")
    argparser.add_argument("--emit-ast", action="store_true", help="Print AST")
    argparser.add_argument("--no-stdlib", action="store_true",
                           help="Don't auto-include stdlib .btrc files; use explicit includes only")
    argparser.add_argument("--strict-imports", action="store_true",
                           help="Require every file to import the top-level symbols it references")
    argparser.add_argument("--debug", action="store_true",
                           help="Emit #line directives for source-level debugging")
    argparser.add_argument("--emit-ir", action="store_true",
                           help="Print IR representation (before optimization)")
    argparser.add_argument("--emit-optimized-ir", action="store_true",
                           help="Print IR representation (after optimization)")
    argparser.add_argument("--no-cache", action="store_true",
                           help="Disable on-disk compilation cache")
    argparser.add_argument("--profile", action="store_true",
                           help="Print a per-phase timing breakdown to stderr")
    argparser.add_argument("--fetch", action="store_true",
                           help="Re-resolve package dependencies and rewrite btrc.lock")

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

    # Resolve package dependencies (btrc.toml) governing this input, if any.
    try:
        pkg.configure_for(args.input, refresh=args.fetch)
    except IncludeResolutionError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    # Read input
    try:
        with open(args.input, "r") as f:
            source = f.read()
    except FileNotFoundError:
        print(f"Error: File '{args.input}' not found", file=sys.stderr)
        sys.exit(1)

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
    cache_source = f"strict-imports\0{source}" if args.strict_imports else source
    use_cache = not args.no_cache and args.stdlib is None and not any([
        args.emit_tokens, args.emit_ast, args.emit_ir,
        args.emit_optimized_ir, args.debug
    ])
    if use_cache:
        cached = get_cached(cache_source, input_path=args.input)
        if cached is not None:
            if args.output:
                out_path = args.output
            else:
                out_path = os.path.splitext(args.input)[0] + ".c"
            with open(out_path, "w") as f:
                f.write(cached)
            print(f"Transpiled {args.input} → {out_path} (cached)")
            return

    use_ast_cache = bool(frontend_source.stdlib_source) and not args.no_cache
    diag_printer = _DiagnosticPrinter(
        frontend_source, args.input, input_source,
        split_spaces=uses_stdlib_ast_cache(
            frontend_source,
            use_ast_cache=use_ast_cache,
            emit_tokens=args.emit_tokens,
            emit_ast=args.emit_ast,
            debug=args.debug,
            parse=not args.emit_tokens,
        ),
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
        print("error: expression or declaration nested too deeply to compile",
              file=sys.stderr)
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
        for err in analyzed.errors[len(error_diags):]:
            print(f"error: {err}", file=sys.stderr)
        sys.exit(1)

    # Display warnings (non-fatal)
    warning_diags = [d for d in analyzed.diags if d.severity == "warning"]
    for d in warning_diags:
        diag_printer.emit(d.message, d.line, d.col,
                          severity="warning", diag_file=d.file)
    for warn in analyzed.warnings[len(warning_diags):]:
        print(f"warning: {warn}", file=sys.stderr)

    # Code generation: AST → IR → optimize → C text
    _t = time.perf_counter()
    ir_module = generate_ir(analyzed, debug=args.debug, source_file=filename)
    prof["ir_gen"] = time.perf_counter() - _t

    if args.emit_ir:
        _dump_ir(ir_module)
        return

    _t = time.perf_counter()
    ir_module = optimize(ir_module)
    prof["optimize"] = time.perf_counter() - _t

    if args.emit_optimized_ir:
        _dump_ir(ir_module)
        return

    # --stdlib: drop everything the prebuilt archive already provides, leaving
    # program-only C that #includes btrc_stdlib.h and links the archive.
    if args.stdlib is not None:
        from .stdlib_archive import (
            ArchiveVersionError,
            load_manifest,
            partition_for_archive,
        )
        try:
            manifest = load_manifest(args.stdlib)
        except ArchiveVersionError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(1)
        partition_for_archive(ir_module, manifest)

    _t = time.perf_counter()
    c_source = CEmitter().emit(ir_module)
    prof["emit"] = time.perf_counter() - _t

    # Store in disk cache
    if use_cache:
        cache_store(cache_source, c_source, input_path=args.input)

    if args.profile:
        _print_profile(prof, len(source))

    # Output
    if args.output:
        out_path = args.output
    else:
        base = os.path.splitext(args.input)[0]
        out_path = base + ".c"

    with open(out_path, "w") as f:
        f.write(c_source)

    print(f"Transpiled {args.input} → {out_path}")


if __name__ == "__main__":  # pragma: no cover
    main()
