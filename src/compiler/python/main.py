#!/usr/bin/env python3
"""btrc — a language that transpiles to C.

Usage: python main.py <input.btrc> [-o output.c] [--emit-ast] [--emit-tokens]
"""

import argparse
import hashlib
import os
import pickle
import re
import sys
import time

from . import pkg
from .analyzer.analyzer import Analyzer
from .ast_nodes import Program
from .disk_cache import get_cached
from .disk_cache import store as cache_store
from .import_visibility import check_visibility
from .ir.emitter import CEmitter
from .ir.gen.generator import generate_ir
from .ir.optimizer import optimize
from .lexer import Lexer, LexerError
from .parser.core import ParseError
from .parser.parser import Parser

# Bump when the lexer/parser/AST changes so cached stdlib ASTs are invalidated.
_STDLIB_AST_VERSION = "1"


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
            pass  # corrupt/incompatible cache — reparse below
    tokens = Lexer(stdlib_source, "<stdlib>").tokenize()
    decls = Parser(tokens).parse().declarations
    try:
        with open(path, "wb") as f:
            pickle.dump(decls, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass
    return decls


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


def _syntax_error_exit(source: str, filename: str, e):
    """Print a lexer/parser error with source context, then exit(1)."""
    raw_msg = str(e).rsplit(" at ", 1)[0] if " at " in str(e) else str(e)
    print(_format_error(source, filename, raw_msg, e.line, e.col), file=sys.stderr)
    sys.exit(1)


_BTRC_INCLUDE_RE = re.compile(r'^\s*#include\s+[<"]([^>"]+\.btrc)[>"]\s*$')
_BTRC_IMPORT_RE = re.compile(r'^\s*import\s+(.+?)\s*;?\s*$')

# Regex to extract class names from btrc source (for skip-if-redefined)
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


def _defined_stdlib_names(source: str) -> set[str]:
    return set(_CLASS_NAME_RE.findall(source)) | set(_INTERFACE_NAME_RE.findall(source))


def _get_stdlib_dir() -> str:
    """Get the absolute path to the stdlib directory."""
    # src/compiler/python/main.py → src/stdlib/
    module_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(module_dir, "..", "..", "stdlib")


def _discover_stdlib_files() -> list[str]:
    """Scan src/stdlib/ and return .btrc filenames in include order.

    vector.btrc comes first (Map/Set/List/Array may depend on Vector),
    then list.btrc (depends on ListNode + Vector), then strings.btrc
    because higher-level stdlib modules use Strings.copy(). Process/fs come
    before app-level modules that construct shell and filesystem helpers.
    """
    stdlib_dir = _get_stdlib_dir()
    if not os.path.isdir(stdlib_dir):
        return []
    files = sorted(f for f in os.listdir(stdlib_dir) if f.endswith(".btrc"))
    # Foundation modules first, then the rest alphabetically.
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
    """Read stdlib sources, skipping classes already defined by the user.

    Args:
        user_source: The user's btrc source (after include resolution).
            If a stdlib file defines a class that the user source already
            defines, that stdlib file is skipped entirely.
    """
    stdlib_dir = _get_stdlib_dir()
    user_names = _defined_stdlib_names(user_source)

    parts = []
    for fname in _discover_stdlib_files():
        fpath = os.path.join(stdlib_dir, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath, 'r') as f:
            content = f.read()
        # Skip if any class in this file is already defined by user
        file_names = _defined_stdlib_names(content)
        if file_names & user_names:
            continue
        parts.append(_strip_btrc_imports(content))
    return "\n".join(parts)


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

    print(f"error: include file '{include_path}' not found\n"
          f"  searched: {source_dir}\n"
          f"  searched: {_get_stdlib_dir()}",
          file=sys.stderr)
    sys.exit(1)


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
        print(f"error: stdlib import '{spec}' not found\n"
              f"  searched: {stdlib_dir}",
              file=sys.stderr)
        sys.exit(1)
    return [path]


def _relative_import_paths(spec: str, source_dir: str) -> list[str]:
    recursive = spec.endswith("/**")
    direct_glob = spec.endswith("/*")
    if recursive or direct_glob:
        base = spec[:-3] if recursive else spec[:-2]
        root = base if os.path.isabs(base) else os.path.join(source_dir, base)
        if not os.path.isdir(root):
            print(f"error: import directory '{spec}' not found\n"
                  f"  searched: {root}",
                  file=sys.stderr)
            sys.exit(1)
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
                    graph: dict[str, set[str]]) -> list[tuple[str, str]]:
    """Recursively resolve includes/imports, tracking per-line provenance and the
    include graph.

    Returns a list of ``(line_text, abs_source_file)`` for every line of the
    resolved output, in order. Populates ``graph``: ``abs_file -> set of abs files
    it directly imports``. The ``included`` set guards circular includes (a file's
    lines appear once); every import *edge* is still recorded in the graph.
    """
    abs_path = os.path.abspath(source_path)
    source_dir = os.path.dirname(abs_path)
    graph.setdefault(abs_path, set())
    if abs_path in included:
        return []  # Circular / repeat include guard (edge already recorded by caller)
    included.add(abs_path)

    out: list[tuple[str, str]] = []
    for line in source.split('\n'):
        m = _BTRC_INCLUDE_RE.match(line)
        if m:
            full_path = os.path.abspath(_resolve_include_path(m.group(1), source_dir))
            graph[abs_path].add(full_path)
            with open(full_path, 'r') as f:
                out.extend(_resolve_traced(f.read(), full_path, included, graph))
            continue

        m = _BTRC_IMPORT_RE.match(line)
        if m:
            for full_path in _import_paths(m.group(1), source_dir):
                abs_full = os.path.abspath(full_path)
                graph[abs_path].add(abs_full)
                if full_path.endswith(".c"):
                    out.append((f'#include "{abs_full}"', abs_path))
                    continue
                with open(full_path, 'r') as f:
                    out.extend(_resolve_traced(f.read(), full_path, included, graph))
            continue

        out.append((line, abs_path))

    return out


def resolve_includes(source: str, source_path: str, included: set[str] | None = None) -> str:
    """Recursively resolve btrc includes/imports by textual inclusion.

    Supported import forms:
      import std.{cli, fs, process}
      import std.*
      import ./file.btrc
      import ./directory/*
      import ./directory/**
    """
    traced = _resolve_traced(source, source_path,
                             set() if included is None else included, {})
    return '\n'.join(text for text, _ in traced)


def resolve_includes_traced(source: str, source_path: str):
    """Like resolve_includes, but also return per-line provenance and the include
    graph, for import-visibility enforcement.

    Returns ``(resolved_source, provenance, graph)`` where ``provenance[i]`` is the
    absolute source file that produced line ``i + 1`` of ``resolved_source``, and
    ``graph`` maps each abs file to the set of abs files it directly imports.
    """
    graph: dict[str, set[str]] = {}
    traced = _resolve_traced(source, source_path, set(), graph)
    resolved = '\n'.join(text for text, _ in traced)
    provenance = [src for _, src in traced]
    return resolved, provenance, graph


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
    except LexerError as e:
        _syntax_error_exit(stdlib_source, "<stdlib>", e)
    except ParseError as e:
        _syntax_error_exit(stdlib_source, "<stdlib>", e)

    analyzed = Analyzer().analyze(program)
    if analyzed.errors:
        for err in analyzed.errors:
            print(f"error: {err}", file=sys.stderr)
        sys.exit(1)

    ir_module = generate_ir(analyzed, debug=False, source_file="<stdlib>")
    build_archive(out_dir, ir_module)
    print(f"Built stdlib archive → {out_dir}")


def main():
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
    argparser.add_argument("--no-runtime", action="store_true",
                           help="Don't include runtime headers in output")
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
    pkg.configure_for(args.input, refresh=args.fetch)

    # Read input
    try:
        with open(args.input, "r") as f:
            source = f.read()
    except FileNotFoundError:
        print(f"Error: File '{args.input}' not found", file=sys.stderr)
        sys.exit(1)

    # Resolve #include/import directives
    _t = time.perf_counter()
    if args.strict_imports:
        user_source, provenance, graph = resolve_includes_traced(source, args.input)
    else:
        user_source = resolve_includes(source, args.input)
        provenance, graph = [], {}
    prof["resolve_includes"] = time.perf_counter() - _t

    # Auto-include stdlib types (skipping classes the user redefines). Kept
    # separate from user_source so the (large, identical) stdlib can be parsed
    # from cache; `source` is the concatenation used for the disk-cache key and
    # the non-cached fallback path.
    stdlib_source = ""
    if not args.no_stdlib and not args.strict_imports:
        _t = time.perf_counter()
        stdlib_source = get_stdlib_source(user_source)
        prof["stdlib_include"] = time.perf_counter() - _t
    source = (stdlib_source + "\n" + user_source) if stdlib_source else user_source

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
        cached = get_cached(cache_source)
        if cached is not None:
            if args.output:
                out_path = args.output
            else:
                out_path = os.path.splitext(args.input)[0] + ".c"
            with open(out_path, "w") as f:
                f.write(cached)
            print(f"Transpiled {args.input} → {out_path} (cached)")
            return

    # Precompiled-stdlib fast path: parse only the user source and merge a
    # cached parse of the stdlib. Disabled for token/AST dumps and --debug
    # (which need exact source positions over the concatenated text).
    use_ast_cache = (
        bool(stdlib_source) and not args.no_cache
        and not args.emit_tokens and not args.emit_ast and not args.debug
        and not args.strict_imports
    )

    if use_ast_cache:
        _t = time.perf_counter()
        try:
            tokens = Lexer(user_source, filename).tokenize()
        except LexerError as e:
            _syntax_error_exit(user_source, filename, e)
        prof["lex"] = time.perf_counter() - _t

        _t = time.perf_counter()
        try:
            user_program = Parser(tokens).parse()
            stdlib_decls = _cached_stdlib_decls(stdlib_source)
        except ParseError as e:
            _syntax_error_exit(user_source, filename, e)
        program = Program(declarations=stdlib_decls + user_program.declarations)
        prof["parse"] = time.perf_counter() - _t
    else:
        # Lexing
        _t = time.perf_counter()
        try:
            lexer = Lexer(source, filename)
            tokens = lexer.tokenize()
        except LexerError as e:
            _syntax_error_exit(source, filename, e)
        prof["lex"] = time.perf_counter() - _t

        if args.emit_tokens:
            for tok in tokens:
                print(tok)
            return

        # Parsing
        _t = time.perf_counter()
        try:
            parser = Parser(tokens)
            program = parser.parse()
        except ParseError as e:
            _syntax_error_exit(source, filename, e)
        prof["parse"] = time.perf_counter() - _t

    if args.strict_imports:
        errors = check_visibility(program, provenance, graph)
        if errors:
            for msg, line, col in errors:
                print(_format_error(source, filename, msg, line, col), file=sys.stderr)
            sys.exit(1)

    if args.emit_ast:
        import pprint
        pprint.pprint(program)
        return

    # Analysis
    _t = time.perf_counter()
    analyzer = Analyzer()
    analyzed = analyzer.analyze(program)
    prof["analyze"] = time.perf_counter() - _t

    if analyzed.errors:
        for err in analyzed.errors:
            # Analyzer errors are formatted as "message at line:col"
            parts = err.rsplit(" at ", 1)
            if len(parts) == 2:
                msg_text = parts[0]
                loc = parts[1].split(":")
                if len(loc) == 2:
                    try:
                        line_no, col_no = int(loc[0]), int(loc[1])
                        print(_format_error(source, filename, msg_text,
                                            line_no, col_no), file=sys.stderr)
                        continue
                    except ValueError:
                        pass
            print(f"error: {err}", file=sys.stderr)
        sys.exit(1)

    # Display warnings (non-fatal)
    for warn in analyzed.warnings:
        parts = warn.rsplit(" at ", 1)
        if len(parts) == 2:
            loc = parts[1].split(":")
            if len(loc) == 2:
                try:
                    line_no, col_no = int(loc[0]), int(loc[1])
                    print(_format_error(source, filename, parts[0],
                                        line_no, col_no).replace("error:", "warning:"),
                          file=sys.stderr)
                    continue
                except ValueError:
                    pass
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
        from .stdlib_archive import load_manifest, partition_for_archive
        partition_for_archive(ir_module, load_manifest(args.stdlib))

    _t = time.perf_counter()
    c_source = CEmitter().emit(ir_module)
    prof["emit"] = time.perf_counter() - _t

    # Store in disk cache
    if use_cache:
        cache_store(cache_source, c_source)

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
