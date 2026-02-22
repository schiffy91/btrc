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
from .codegen import CodeGen


_BTRC_INCLUDE_RE = re.compile(r'^\s*#include\s+"([^"]+\.btrc)"\s*$')


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

    filename = os.path.basename(args.input)

    # Lexing
    try:
        lexer = Lexer(source, filename)
        tokens = lexer.tokenize()
    except LexerError as e:
        print(f"Lexer error: {e}", file=sys.stderr)
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
        print(f"Parse error: {e}", file=sys.stderr)
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
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # Code generation
    codegen = CodeGen(analyzed, debug=args.debug, source_file=filename)
    c_source = codegen.generate()

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
