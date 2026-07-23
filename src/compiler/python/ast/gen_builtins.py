#!/usr/bin/env python3
"""Generate ``src/devex/lsp/builtins.py`` from stdlib declarations.

Usage: python src/compiler/python/ast/gen_builtins.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, ROOT)

from src.compiler.python.ast.gen_builtins_render import (
    fmt_params,
    generate_collection_members,
    generate_intrinsic_members,
    generate_static_methods,
    render_builtins,
)
from src.compiler.python.ast.gen_builtins_scan import (
    classify_stdlib,
    extract_members,
    type_repr,
)
from src.compiler.python.ast.gen_builtins_scan import (
    parse_file as _parse_file,
)
from src.compiler.python.ast.gen_builtins_spec import (
    INTRINSIC_COLLECTION_MEMBERS,
    INTRINSIC_FUNCTIONS,
    INTRINSIC_STRING_MEMBERS,
)
from src.compiler.python.cli.file_io import CompilerFileIO

__all__ = [
    "INTRINSIC_COLLECTION_MEMBERS",
    "INTRINSIC_FUNCTIONS",
    "INTRINSIC_STRING_MEMBERS",
    "extract_members",
    "fmt_params",
    "generate_collection_members",
    "generate_intrinsic_members",
    "generate_static_methods",
    "main",
    "parse_file",
    "render_current_builtins",
    "type_repr",
]

STDLIB_DIR = os.path.join(ROOT, "src", "stdlib")
OUTPUT = os.path.join(ROOT, "src", "devex", "lsp", "builtins.py")


def parse_file(filename):
    """Parse one file from the configured stdlib directory."""
    return _parse_file(filename, STDLIB_DIR)


def render_current_builtins() -> str:
    """Render the builtins module represented by the current stdlib."""
    collection_data, static_data = classify_stdlib(STDLIB_DIR)
    return render_builtins(collection_data, static_data)


def main():
    collection_data, static_data = classify_stdlib(STDLIB_DIR)
    content = render_builtins(collection_data, static_data)
    CompilerFileIO().write_output(OUTPUT, content)
    print(f"Generated {OUTPUT}")

    print(f"  STRING_MEMBERS: {len(INTRINSIC_STRING_MEMBERS)} members (intrinsic)")
    for type_name, (fields, methods) in collection_data.items():
        print(f"  {type_name.upper()}_MEMBERS: {len(fields)} fields + {len(methods)} methods (from stdlib)")
    for class_name, methods in static_data.items():
        print(f"  STDLIB_STATIC_METHODS[{class_name}]: {len(methods)} methods (from stdlib)")
    print(f"  BUILTIN_FUNCTION_SIGNATURES: {len(INTRINSIC_FUNCTIONS)} functions (intrinsic)")


if __name__ == "__main__":
    main()
