"""Frontend composition for source resolution, lexing, and parsing."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from src.compiler.python.syntax.ast.generated import Program

from ..lexer.lexer import Lexer
from ..parser.parser import Parser
from ..syntax.tokens import Token
from .imports import FrontendVisibilityError, ImportResolver, ImportVisibilityChecker
from .packages import PackageUniverse
from .sources import (
    CompilerStdlibSource,
    ResolvedSource,
    SourceResolver,
    StdlibRepository,
)


@dataclass(frozen=True)
class FrontendParseResult:
    """Typed lexer/parser output owned by the frontend stage."""

    tokens: tuple[Token, ...]
    program: Program | None = None
    user_program: Program | None = None


class FrontendStage:
    """Compose resolution, lexing, parsing, provenance, and visibility."""

    def __init__(
        self,
        stdlib: StdlibRepository | None = None,
        *,
        resolver: SourceResolver | None = None,
        imports: ImportResolver | None = None,
        package_universe: PackageUniverse | None = None,
    ) -> None:
        if resolver is not None:
            if stdlib is not None and resolver.stdlib is not stdlib:
                raise ValueError("FrontendStage resolver and stdlib must share one repository")
            if imports is not None and resolver.imports is not imports:
                raise ValueError("FrontendStage resolver and imports must share one owner")
            self.resolver = resolver
            self.stdlib = resolver.stdlib
        else:
            self.stdlib = stdlib or (imports.stdlib if imports is not None else StdlibRepository())
            imports = imports or ImportResolver(self.stdlib)
            self.resolver = SourceResolver(
                self.stdlib,
                imports=imports,
                package_universe=package_universe,
            )

    def resolve(
        self,
        source: str,
        source_path: str,
        *,
        include_stdlib: bool = True,
        strict_imports: bool = True,
        map_stdlib_positions: bool = False,
        refresh_packages: bool = False,
        profile: dict[str, float] | None = None,
    ) -> ResolvedSource:
        return self.resolver.resolve(
            source,
            source_path,
            include_stdlib=include_stdlib,
            strict_imports=strict_imports,
            map_stdlib_positions=map_stdlib_positions,
            refresh_packages=refresh_packages,
            profile=profile,
        )

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
                space == "combined" and stdlib_line_count and getattr(declaration, "line", 0) <= stdlib_line_count
            )
            if position is not None and self._compiler_resolved_stdlib_import(source, position[0]):
                compiler_stdlib = True
            if position is not None:
                declaration.source_file = CompilerStdlibSource(position[0]) if compiler_stdlib else position[0]
            elif compiler_stdlib:
                declaration.source_file = CompilerStdlibSource()
            CompilerStdlibSource.stamp_nested(declaration)

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
            tokens = Lexer(source.user_source, filename).tokenize()
            self._timed(profile, "lex", start)

            start = time.perf_counter()
            user_program = Parser(tokens).parse()
            stdlib_declarations = self.stdlib.cached_declarations(source.stdlib_source)
            self._stamp_declaration_files(user_program.declarations, source, "user")
            self._stamp_declaration_files(stdlib_declarations, source, "stdlib")
            program = Program(declarations=stdlib_declarations + user_program.declarations)
            self._timed(profile, "parse", start)
        else:
            start = time.perf_counter()
            tokens = Lexer(source.source, filename).tokenize()
            self._timed(profile, "lex", start)
            if not parse:
                return FrontendParseResult(tokens=tuple(tokens))

            start = time.perf_counter()
            program = Parser(tokens).parse()
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
