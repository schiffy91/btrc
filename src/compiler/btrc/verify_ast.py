#!/usr/bin/env python3
"""Reference canonical-AST dumper for self-hosting verification.

Uses the Python compiler as a LIBRARY (imports its lexer + parser) — it does NOT
modify the compiler. Parses one .btrc file and prints a stable canonical AST
S-expression that the self-hosted btrc parser reproduces byte-for-byte.

Run from the repo root:  python3 src/compiler/btrc/verify_ast.py <file.btrc>

Format (one field per line, 2-space indent by depth):
    (NodeKind
      field=<value>
      ...)
<value> ::= nested node `(...)` | list `[ ... ]` (`[]` when empty) | `nil`
          | `true`/`false` | decimal int | "double-quoted string" (\\ \n \r \t).
"""
import dataclasses
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from src.compiler.python.lexer import Lexer  # noqa: E402
from src.compiler.python.parser.parser import Parser  # noqa: E402


def _q(s: str) -> str:
    out = ['"']
    for ch in s:
        out.append({"\\": "\\\\", '"': '\\"', "\n": "\\n",
                    "\r": "\\r", "\t": "\\t"}.get(ch, ch))
    out.append('"')
    return "".join(out)


def _dump(node, depth: int) -> str:
    pad = "  " * depth
    cpad = "  " * (depth + 1)
    if node is None:
        return "nil"
    if isinstance(node, bool):
        return "true" if node else "false"
    if isinstance(node, int):
        return str(node)
    if isinstance(node, str):
        return _q(node)
    if isinstance(node, list):
        if not node:
            return "[]"
        return "[\n" + "\n".join(cpad + _dump(x, depth + 1) for x in node) + "\n" + pad + "]"
    if dataclasses.is_dataclass(node):
        fields = dataclasses.fields(node)
        if not fields:
            return "(" + type(node).__name__ + ")"
        body = "\n".join(cpad + f.name + "=" + _dump(getattr(node, f.name), depth + 1)
                         for f in fields)
        return "(" + type(node).__name__ + "\n" + body + ")"
    return _q(str(node))


def main():
    if len(sys.argv) < 2:
        print("usage: verify_ast.py <file.btrc>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        src = f.read()
    program = Parser(Lexer(src, os.path.basename(sys.argv[1])).tokenize()).parse()
    print(_dump(program, 0))


if __name__ == "__main__":
    main()
