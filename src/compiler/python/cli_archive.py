"""Build the reusable C archive form of the btrc standard library."""

import sys

from .cli_diagnostics import format_error
from .frontend import analyze_frontend_program, get_stdlib_source
from .ir.gen.errors import CodegenError
from .ir.gen.generator import generate_ir
from .lexer import Lexer, LexerError
from .parser.core import ParseError
from .parser.parser import Parser


def build_stdlib_archive(out_dir: str) -> None:
    """Compile the entire stdlib into a linkable archive in ``out_dir``."""
    from .stdlib_archive import build_archive

    stdlib_source = get_stdlib_source("")
    if not stdlib_source.strip():
        print("error: no stdlib sources found", file=sys.stderr)
        raise SystemExit(1)

    try:
        tokens = Lexer(stdlib_source, "<stdlib>").tokenize()
        program = Parser(tokens).parse()
    except (LexerError, ParseError) as error:
        message = str(error).removesuffix(f" at {error.line}:{error.col}")
        print(
            format_error(
                stdlib_source,
                "<stdlib>",
                message,
                error.line,
                error.col,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from error

    analyzed = analyze_frontend_program(program)
    if analyzed.errors:
        for error in analyzed.errors:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)

    try:
        ir_module = generate_ir(analyzed, debug=False, source_file="<stdlib>")
        build_archive(out_dir, ir_module, stdlib_source)
    except CodegenError as error:
        from .cli_diagnostics import codegen_error_exit

        codegen_error_exit(error)
    print(f"Built stdlib archive → {out_dir}")


def partition_against_stdlib(module, program, stdlib_dir: str) -> None:
    """Validate and apply a prebuilt stdlib archive to one program module."""
    from .stdlib_archive import (
        ArchiveVersionError,
        load_manifest,
        partition_for_archive,
        reject_user_overrides,
    )

    try:
        manifest = load_manifest(stdlib_dir, get_stdlib_source(""))
        reject_user_overrides(program, manifest)
    except ArchiveVersionError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    partition_for_archive(module, manifest)
