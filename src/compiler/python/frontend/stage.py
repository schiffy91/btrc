"""Frontend composition for source resolution, lexing, and parsing."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from src.compiler.python.syntax.ast.generated import PreprocessorDirective, Program

from ..lexer.lexer import Lexer
from ..parser.parser import Parser
from ..syntax.tokens import SourceSymbolDirective, Token
from .imports import FrontendVisibilityError, ImportResolver, ImportVisibilityChecker
from .native_imports import NativeHeaderSource
from .packages import PackageUniverse
from .sources import (
    CompilerStdlibSource,
    ConditionalTest,
    PreprocessorConditionalError,
    ResolvedSource,
    SourceDependencyGraph,
    SourceDependencyKind,
    SourceResolver,
    StdlibRepository,
)

_QUOTED_INCLUDE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*("[^"\n]+")')


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
        use_cache: bool = True,
        target: str | None = None,
        profile: dict[str, float] | None = None,
    ) -> ResolvedSource:
        return self.resolver.resolve(
            source,
            source_path,
            include_stdlib=include_stdlib,
            strict_imports=strict_imports,
            map_stdlib_positions=map_stdlib_positions,
            refresh_packages=refresh_packages,
            use_cache=use_cache,
            target=target,
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

        if source.native_declarations:
            program.declarations = list(source.native_declarations) + program.declarations

        self.verify_tests(program, source)

        if source.strict_imports:
            errors = ImportVisibilityChecker(
                program,
                source.provenance,
                source.graph,
                external_symbol_files=self.stdlib.symbol_files(),
            ).check()
            if errors:
                raise FrontendVisibilityError(errors)

        program.declarations = [
            declaration
            for declaration in program.declarations
            if not (
                isinstance(getattr(declaration, "source_file", None), NativeHeaderSource)
                and declaration.source_file.coalesced
            )
        ]

        return FrontendParseResult(
            tokens=tuple(tokens),
            program=program,
            user_program=user_program,
        )

    # -- Program checks on #if records (P1-P4) ------------------------------

    @staticmethod
    def _declaration_path(declaration) -> str | None:
        source_file = getattr(declaration, "source_file", None)
        if not isinstance(source_file, str) or not source_file or source_file.startswith("<"):
            return None
        return SourceDependencyGraph.canonical_file(source_file)

    def verify_tests(self, program: Program, source: ResolvedSource) -> None:
        """Refuse a ``#if`` test whose answer C could see differently (P1, P4, P2, P3).

        Each record of an absent or this-file name is checked in resolution
        order, trying P1, P4, P2 and P3 in turn; the first match fails at the
        tested name in its own file.
        """

        tests = source.conditional_tests
        if not tests:
            return
        defines: dict[str, str] = {}
        undefines: dict[str, str] = {}
        native_names: set[str] = set()
        directives: list[tuple[str, str]] = []
        for declaration in program.declarations:
            if isinstance(getattr(declaration, "source_file", None), NativeHeaderSource):
                native_names.update(StdlibRepository._declaration_names(declaration))
                continue
            if not isinstance(declaration, PreprocessorDirective):
                continue
            path = self._declaration_path(declaration)
            if path is None:
                continue
            directives.append((path, declaration.text))
            directive = SourceSymbolDirective.parse(declaration.text)
            if directive is None:
                continue
            (defines if directive.operation == "define" else undefines).setdefault(directive.name, path)
        for test in tests:
            path = SourceDependencyGraph.canonical_file(test.path)
            message = self._test_failure(test, path, defines, undefines, native_names, directives, source)
            if message is not None:
                raise PreprocessorConditionalError(message, test.path, test.line, test.col)

    def _test_failure(
        self,
        test: ConditionalTest,
        path: str,
        defines: dict[str, str],
        undefines: dict[str, str],
        native_names: set[str],
        directives: list[tuple[str, str]],
        source: ResolvedSource,
    ) -> str | None:
        name = test.name
        here = os.path.basename(test.path)
        if not test.local:
            elsewhere = next(
                (owner for owner in self._owners(name, defines, directives, "define") if owner != path), None
            )
            if elsewhere is not None:
                return (
                    f"'{name}' is defined in {os.path.basename(elsewhere)}, but #if in {here} cannot see it; "
                    "#if sees only target macros and #defines earlier in the same file"
                )
        else:
            elsewhere = next(
                (owner for owner in self._owners(name, undefines, directives, "undef") if owner != path), None
            )
            if elsewhere is not None:
                return (
                    f"'{name}' is #undef'd in {os.path.basename(elsewhere)}, but #if in {here} cannot see that; "
                    "#if sees only #defines and #undefs earlier in the same file"
                )
            return None
        if name in native_names:
            return f"'{name}' comes from a native header; #if is evaluated before C compilation and cannot test it"
        evidence = self._c_evidence(path, here, directives, source)
        if evidence is not None:
            return (
                f"'{name}' may come from C that btrc does not read ({evidence}); "
                "#if is evaluated before C compilation and cannot test it"
            )
        return None

    @staticmethod
    def _owners(name: str, first: dict[str, str], directives: list[tuple[str, str]], operation: str):
        """Files whose live directives ``#define``/``#undef`` ``name``, in program order."""

        if name not in first:
            return
        for path, text in directives:
            directive = SourceSymbolDirective.parse(text)
            if directive is not None and directive.operation == operation and directive.name == name:
                yield path

    @staticmethod
    def _c_evidence(path: str, here: str, directives: list[tuple[str, str]], source: ResolvedSource) -> str | None:
        """What C that btrc does not read could define a macro for the file at ``path`` (P3)."""

        for owner, text in directives:
            if owner != path:
                continue
            match = _QUOTED_INCLUDE.match(text)
            if match is not None and not match.group(1)[1:-1].endswith(".btrc"):
                return f"{match.group(1)} in {here}"
        imported = sorted(
            dependency.target
            for each, dependency in source.graph.iter_edges()
            if SourceDependencyGraph.canonical_file(each) == path
            and dependency.kind is SourceDependencyKind.IMPORT
            and dependency.target.endswith(".c")
        )
        if imported:
            return f"{os.path.basename(imported[0])} imported by {here}"
        plan = source.native_plan
        roots = {package.name: os.path.realpath(package.root) for package in plan.packages}
        for item in plan.declarations:
            if item.kind != "header" or not item.selected_for(plan.target):
                continue
            if item.modules:
                applies = any(SourceDependencyGraph.canonical_file(module) == path for module in item.modules)
            else:
                root = roots.get(item.package)
                try:
                    applies = root is not None and os.path.commonpath((path, root)) == root
                except ValueError:
                    applies = False
            if applies:
                return f"native header {os.path.basename(item.value)} for {here}"
        for binding in plan.bindings:
            if SourceDependencyGraph.canonical_file(binding.module) == path:
                return f"native header {os.path.basename(binding.header)} for {here}"
        return None
