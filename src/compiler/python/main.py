#!/usr/bin/env python3
"""btrc — a language that transpiles to C.

Usage: python main.py <input.btrc> [-o output.c] [--emit-ast] [--emit-tokens]
"""

import sys
import os
import argparse
import re
from typing import Optional, Set

from .lexer import Lexer, LexerError
from .parser import Parser, ParseError
from .analyzer import Analyzer
from .ir import optimize, CEmitter
from .ir.gen import generate_ir


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


_BTRC_INCLUDE_RE = re.compile(r'^\s*#include\s+"([^"]+\.btrc)"\s*$')

# Stdlib collection files to auto-include (order matters: List before Map/Set)
_STDLIB_COLLECTION_FILES = ["list.btrc", "map.btrc", "set.btrc"]
_stdlib_cache: Optional[str] = None


def _get_stdlib_dir() -> str:
    """Get the absolute path to the stdlib directory."""
    # src/compiler/python/main.py → src/stdlib/
    module_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(module_dir, "..", "..", "stdlib")


def get_stdlib_source() -> str:
    """Read and cache the stdlib collection sources."""
    global _stdlib_cache
    if _stdlib_cache is not None:
        return _stdlib_cache
    stdlib_dir = _get_stdlib_dir()
    parts = []
    for fname in _STDLIB_COLLECTION_FILES:
        fpath = os.path.join(stdlib_dir, fname)
        if os.path.exists(fpath):
            with open(fpath, 'r') as f:
                parts.append(f.read())
    _stdlib_cache = "\n".join(parts)
    return _stdlib_cache


def resolve_includes(source: str, source_path: str, included: Optional[Set[str]] = None) -> str:
    """Recursively resolve #include "file.btrc" directives by textual inclusion."""
    if included is None:
        included = set()

    source_dir = os.path.dirname(os.path.abspath(source_path))
    abs_path = os.path.abspath(source_path)

    if abs_path in included:
        return ""  # Circular include guard
    included.add(abs_path)

    lines = source.split('\n')
    result = []
    for line in lines:
        m = _BTRC_INCLUDE_RE.match(line)
        if m:
            include_path = m.group(1)
            full_path = os.path.join(source_dir, include_path)
            if not os.path.exists(full_path):
                print(f"Error: Include file '{include_path}' not found "
                      f"(resolved to '{full_path}')", file=sys.stderr)
                sys.exit(1)
            with open(full_path, 'r') as f:
                included_source = f.read()
            resolved = resolve_includes(included_source, full_path, included)
            result.append(resolved)
        else:
            result.append(line)

    return '\n'.join(result)


def _dump_ir(module):
    """Print a canonical IR dump for debugging."""
    from .ir.nodes import IRModule
    print(f"# IRModule: {len(module.struct_defs)} structs, "
          f"{len(module.function_defs)} functions, "
          f"{len(module.helper_decls)} helpers")
    for struct in module.struct_defs:
        fields = ", ".join(f"{f.c_type} {f.name}" for f in struct.fields)
        print(f"struct {struct.name} {{ {fields} }}")
    for func in module.function_defs:
        params = ", ".join(f"{p.c_type} {p.name}" for p in func.params)
        print(f"fn {func.name}({params}) -> {func.return_type}")


def main():
    argparser = argparse.ArgumentParser(description="btrc transpiler")
    argparser.add_argument("input", help="Input .btrc file")
    argparser.add_argument("-o", "--output", help="Output .c file (default: <input>.c)")
    argparser.add_argument("--emit-tokens", action="store_true", help="Print token stream")
    argparser.add_argument("--emit-ast", action="store_true", help="Print AST")
    argparser.add_argument("--no-runtime", action="store_true",
                           help="Don't include runtime headers in output")
    argparser.add_argument("--debug", action="store_true",
                           help="Emit #line directives for source-level debugging")
    argparser.add_argument("--emit-ir", action="store_true",
                           help="Print IR representation (before optimization)")
    argparser.add_argument("--emit-optimized-ir", action="store_true",
                           help="Print IR representation (after optimization)")

    args = argparser.parse_args()

    # Read input
    try:
        with open(args.input, "r") as f:
            source = f.read()
    except FileNotFoundError:
        print(f"Error: File '{args.input}' not found", file=sys.stderr)
        sys.exit(1)

    # Resolve #include "file.btrc" directives
    source = resolve_includes(source, args.input)

    # Auto-include stdlib collection types (List, Map, Set)
    stdlib_source = get_stdlib_source()
    if stdlib_source:
        source = stdlib_source + "\n" + source

    filename = os.path.basename(args.input)

    # Lexing
    try:
        lexer = Lexer(source, filename)
        tokens = lexer.tokenize()
    except LexerError as e:
        # Extract the message without "at line:col" suffix
        raw_msg = str(e).rsplit(" at ", 1)[0] if " at " in str(e) else str(e)
        print(_format_error(source, filename, raw_msg, e.line, e.col),
              file=sys.stderr)
        sys.exit(1)

    if args.emit_tokens:
        for tok in tokens:
            print(tok)
        return

    # Parsing
    try:
        parser = Parser(tokens)
        program = parser.parse()
    except ParseError as e:
        raw_msg = str(e).rsplit(" at ", 1)[0] if " at " in str(e) else str(e)
        print(_format_error(source, filename, raw_msg, e.line, e.col),
              file=sys.stderr)
        sys.exit(1)

    if args.emit_ast:
        import pprint
        pprint.pprint(program)
        return

    # Analysis
    analyzer = Analyzer()
    analyzed = analyzer.analyze(program)

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

    # Code generation: AST → IR → optimize → C text
    ir_module = generate_ir(analyzed, debug=args.debug, source_file=filename)

    if args.emit_ir:
        _dump_ir(ir_module)
        return

    ir_module = optimize(ir_module)

    if args.emit_optimized_ir:
        _dump_ir(ir_module)
        return

    c_source = CEmitter().emit(ir_module)

    # Output
    if args.output:
        out_path = args.output
    else:
        base = os.path.splitext(args.input)[0]
        out_path = base + ".c"

    with open(out_path, "w") as f:
        f.write(c_source)

    print(f"Transpiled {args.input} → {out_path}")


if __name__ == "__main__":
    main()
