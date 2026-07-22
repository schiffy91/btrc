"""Lexing/parsing owner for resolved compiler source bundles."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from ..ast_nodes import Program
from ..lexer import Lexer
from ..parser.parser import Parser
from ..pipeline.models import FrontendParseResult
from ..source_provenance import compiler_stdlib_source, stamp_nested_declaration_sources
from .dependencies import ResolvedSource
from .stdlib import StdlibRepository
from .visibility import FrontendVisibilityError, ImportVisibilityChecker


class FrontendParser:
    """Own parse-mode selection, AST provenance, and import visibility."""

    def __init__(
        self,
        stdlib: StdlibRepository | None = None,
        *,
        lexer_factory: Callable[[str, str], Lexer] = Lexer,
        parser_factory: Callable[[list], Parser] = Parser,
    ) -> None:
        self.stdlib = stdlib or StdlibRepository()
        self._lexer_factory = lexer_factory
        self._parser_factory = parser_factory

    @staticmethod
    def _timed(profile: dict[str, float] | None, label: str, start: float) -> None:
        if profile is not None:
            profile[label] = time.perf_counter() - start

    @staticmethod
    def uses_stdlib_ast_cache(
        source: ResolvedSource,
        *,
        use_ast_cache: bool = True,
        emit_tokens: bool = False,
        emit_ast: bool = False,
        debug: bool = False,
        parse: bool = True,
    ) -> bool:
        """Whether stdlib and user source use separate parse coordinate spaces."""

        return (
            parse
            and bool(source.stdlib_source)
            and use_ast_cache
            and not emit_tokens
            and not emit_ast
            and not debug
            and not source.strict_imports
        )

    def _compiler_resolved_stdlib_import(self, source: ResolvedSource, path: str) -> bool:
        canonical = os.path.realpath(path)
        if canonical == source.root_source_path:
            return False
        stdlib_root = os.path.realpath(self.stdlib.directory())
        try:
            if os.path.commonpath((canonical, stdlib_root)) != stdlib_root:
                return False
        except (OSError, ValueError):
            return False
        return source.graph.has_target(canonical)

    def _stamp_declaration_files(self, declarations, source: ResolvedSource, space: str) -> None:
        stdlib_line_count = source.stdlib_source.count("\n") + 1 if source.stdlib_source else 0
        for declaration in declarations:
            position = source.map_line(getattr(declaration, "line", 0), space)
            compiler_stdlib = space == "stdlib" or (
                space == "combined"
                and stdlib_line_count
                and getattr(declaration, "line", 0) <= stdlib_line_count
            )
            if position is not None and self._compiler_resolved_stdlib_import(source, position[0]):
                compiler_stdlib = True
            if position is not None:
                declaration.source_file = compiler_stdlib_source(position[0]) if compiler_stdlib else position[0]
            elif compiler_stdlib:
                declaration.source_file = compiler_stdlib_source()
            stamp_nested_declaration_sources(declaration)

    def parse(
        self,
        source: ResolvedSource,
        filename: str,
        *,
        use_ast_cache: bool = True,
        emit_tokens: bool = False,
        emit_ast: bool = False,
        debug: bool = False,
        parse: bool = True,
        profile: dict[str, float] | None = None,
    ) -> FrontendParseResult:
        """Lex and optionally parse a resolved source bundle."""

        use_cached_stdlib_ast = self.uses_stdlib_ast_cache(
            source,
            use_ast_cache=use_ast_cache,
            emit_tokens=emit_tokens,
            emit_ast=emit_ast,
            debug=debug,
            parse=parse,
        )

        if use_cached_stdlib_ast:
            start = time.perf_counter()
            tokens = self._lexer_factory(source.user_source, filename).tokenize()
            self._timed(profile, "lex", start)

            start = time.perf_counter()
            user_program = self._parser_factory(tokens).parse()
            stdlib_declarations = self.stdlib.cached_declarations(source.stdlib_source)
            self._stamp_declaration_files(user_program.declarations, source, "user")
            self._stamp_declaration_files(stdlib_declarations, source, "stdlib")
            program = Program(declarations=stdlib_declarations + user_program.declarations)
            self._timed(profile, "parse", start)
        else:
            start = time.perf_counter()
            tokens = self._lexer_factory(source.source, filename).tokenize()
            self._timed(profile, "lex", start)
            if not parse:
                return FrontendParseResult(tokens=tuple(tokens))

            start = time.perf_counter()
            program = self._parser_factory(tokens).parse()
            user_program = program if not source.stdlib_source else None
            self._stamp_declaration_files(program.declarations, source, "combined")
            self._timed(profile, "parse", start)

        if source.strict_imports:
            errors = ImportVisibilityChecker(
                program,
                source.provenance,
                source.graph,
                external_symbol_files=self.stdlib.symbol_files(),
            ).check()
            if errors:
                raise FrontendVisibilityError(errors)

        return FrontendParseResult(
            tokens=tuple(tokens),
            program=program,
            user_program=user_program,
        )
