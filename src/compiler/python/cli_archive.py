"""Command-line owner for building the reusable standard-library archive."""

from __future__ import annotations

import sys
from collections.abc import Callable

from .analyzer.semantic_analyzer import SemanticAnalyzer
from .artifacts.publication.publisher import ArtifactPublisher
from .artifacts.publication.storage import ArtifactStorage
from .artifacts.stdlib.publisher import StdlibArchivePublisher
from .cli_diagnostics import format_error
from .frontend.stdlib import StdlibRepository
from .ir.gen.errors import CodegenError
from .ir.gen.lowerer import IRLowerer
from .lexer import Lexer, LexerError
from .parser.core import ParseError
from .parser.parser import Parser
from .source_provenance import (
    compiler_stdlib_source,
    stamp_nested_declaration_sources,
)


class StdlibArchiveBuilder:
    """Own the parse, analysis, lowering, and publication build workflow."""

    def __init__(
        self,
        stdlib: StdlibRepository | None = None,
        publisher: StdlibArchivePublisher | None = None,
        *,
        analyzer_factory: Callable[[], SemanticAnalyzer] = SemanticAnalyzer,
        lowerer_factory: Callable[..., IRLowerer] = IRLowerer,
    ) -> None:
        self._stdlib = stdlib or StdlibRepository()
        self._publisher = publisher or StdlibArchivePublisher(ArtifactPublisher(ArtifactStorage()))
        self._analyzer_factory = analyzer_factory
        self._lowerer_factory = lowerer_factory

    def build(self, out_dir: str) -> None:
        """Compile the entire stdlib into a linkable archive in ``out_dir``."""

        from .stdlib_archive import build_archive

        stdlib_source = self._stdlib.source("")
        if not stdlib_source.strip():
            print("error: no stdlib sources found", file=sys.stderr)
            raise SystemExit(1)

        program = self._parse(stdlib_source)
        analyzed = self._analyzer_factory().analyze(program)
        if analyzed.errors:
            for error in analyzed.errors:
                print(f"error: {error}", file=sys.stderr)
            raise SystemExit(1)

        try:
            ir_module = self._lowerer_factory(
                analyzed,
                debug=False,
                source_file="<stdlib>",
            ).lower()
            build_archive(
                out_dir,
                ir_module,
                stdlib_source,
                self._publisher,
            )
        except CodegenError as error:
            from .cli_diagnostics import codegen_error_exit

            codegen_error_exit(error)
        print(f"Built stdlib archive → {out_dir}")

    def _parse(self, stdlib_source: str):
        try:
            tokens = Lexer(stdlib_source, "<stdlib>").tokenize()
            program = Parser(tokens).parse()
            self._stamp_declarations(program)
            return program
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

    def _stamp_declarations(self, program) -> None:
        """Authenticate top-level and nested declarations in archive builds."""

        for declaration in program.declarations:
            declaration.source_file = compiler_stdlib_source()
            stamp_nested_declaration_sources(declaration)


__all__ = ["StdlibArchiveBuilder"]
