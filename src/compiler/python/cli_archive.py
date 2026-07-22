"""Build the reusable C archive form of the btrc standard library."""

import sys

from .analyzer.analyzer import Analyzer
from .artifacts.publication.publisher import ArtifactPublisher
from .artifacts.publication.storage import ArtifactStorage
from .artifacts.stdlib.publisher import StdlibArchivePublisher
from .cli_diagnostics import format_error
from .frontend.stdlib import StdlibRepository
from .ir.gen.errors import CodegenError
from .ir.gen.generator import generate_ir
from .lexer import Lexer, LexerError
from .parser.core import ParseError
from .parser.parser import Parser
from .source_provenance import (
    compiler_stdlib_source,
    stamp_nested_declaration_sources,
)


def _stamp_stdlib_declarations(program) -> None:
    """Authenticate top-level and nested declarations in archive builds."""
    for declaration in program.declarations:
        declaration.source_file = compiler_stdlib_source()
        stamp_nested_declaration_sources(declaration)


def build_stdlib_archive(out_dir: str) -> None:
    """Compile the entire stdlib into a linkable archive in ``out_dir``."""
    from .stdlib_archive import build_archive

    stdlib_source = StdlibRepository().source("")
    if not stdlib_source.strip():
        print("error: no stdlib sources found", file=sys.stderr)
        raise SystemExit(1)

    try:
        tokens = Lexer(stdlib_source, "<stdlib>").tokenize()
        program = Parser(tokens).parse()
        _stamp_stdlib_declarations(program)
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

    analyzed = Analyzer().analyze(program)
    if analyzed.errors:
        for error in analyzed.errors:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)

    try:
        ir_module = generate_ir(analyzed, debug=False, source_file="<stdlib>")
        storage = ArtifactStorage()
        publication = ArtifactPublisher(storage)
        build_archive(
            out_dir,
            ir_module,
            stdlib_source,
            StdlibArchivePublisher(publication),
        )
    except CodegenError as error:
        from .cli_diagnostics import codegen_error_exit

        codegen_error_exit(error)
    print(f"Built stdlib archive → {out_dir}")
