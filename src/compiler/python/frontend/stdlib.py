"""Standard-library discovery, composition, caching, and symbol ownership."""

from __future__ import annotations

import os

from .. import ast_nodes as ast
from .. import frontend_stdlib as legacy_stdlib
from ..lexer import Lexer
from ..parser.parser import Parser
from ..pipeline.models import StdlibSource
from ..pkg import IncludeResolutionError
from ..source_io import SourceReadError, read_source
from ..source_macros import source_macro_name
from .dependencies import SourceDependencyGraph


class StdlibRepository:
    """Own access to the compiler's canonical standard-library sources."""

    def __init__(self) -> None:
        self._symbol_files: dict[str, frozenset[str]] | None = None

    @property
    def ast_version(self) -> str:
        return legacy_stdlib._STDLIB_AST_VERSION

    def directory(self) -> str:
        return legacy_stdlib._get_stdlib_dir()

    def discover_files(self) -> list[str]:
        return legacy_stdlib._discover_stdlib_files()

    def find_file(self, include_path: str) -> str | None:
        return legacy_stdlib._find_stdlib_file(include_path)

    def defined_names(self, source: str) -> set[str]:
        return legacy_stdlib._defined_stdlib_names(source)

    def source(self, user_source: str = "") -> str:
        return legacy_stdlib.get_stdlib_source(user_source)

    def source_mapped(self, user_source: str = "") -> StdlibSource:
        source = legacy_stdlib.get_stdlib_source_mapped(user_source)
        return StdlibSource(source.source, tuple(source.source_positions))

    def cached_declarations(self, stdlib_source: str) -> list:
        return legacy_stdlib._cached_stdlib_decls(stdlib_source)

    @staticmethod
    def _declaration_names(declaration) -> tuple[str, ...]:
        if isinstance(declaration, ast.PreprocessorDirective):
            name = source_macro_name(declaration.text)
            return (name,) if name else ()
        if isinstance(declaration, ast.TypedefDecl):
            return (declaration.alias,) if declaration.alias else ()
        if isinstance(
            declaration,
            (
                ast.ClassDecl,
                ast.InterfaceDecl,
                ast.FunctionDecl,
                ast.StructDecl,
                ast.EnumDecl,
                ast.RichEnumDecl,
                ast.VarDeclStmt,
            ),
        ):
            names = [declaration.name] if declaration.name else []
            if isinstance(declaration, ast.EnumDecl):
                names.extend(value.name for value in declaration.values if value.name)
            elif isinstance(declaration, ast.RichEnumDecl):
                names.extend(variant.name for variant in declaration.variants if variant.name)
            return tuple(names)
        return ()

    def symbol_files(self) -> dict[str, frozenset[str]]:
        """Map every canonical stdlib symbol to the file that owns it.

        Strict visibility must know about compiler-recognized stdlib types even
        when their source was not imported into the current AST. The map is
        derived from the stdlib itself rather than a second hardcoded table.
        """

        if self._symbol_files is not None:
            return self._symbol_files

        owners: dict[str, set[str]] = {}
        root = self.directory()
        for filename in self.discover_files():
            path = os.path.join(root, filename)
            if not os.path.isfile(path):
                continue
            try:
                source = read_source(path)
            except SourceReadError as error:
                raise IncludeResolutionError(str(error)) from error
            program = Parser(Lexer(source, path).tokenize()).parse()
            canonical = SourceDependencyGraph.canonical_file(path)
            for declaration in program.declarations:
                for name in self._declaration_names(declaration):
                    owners.setdefault(name, set()).add(canonical)
        self._symbol_files = {name: frozenset(paths) for name, paths in owners.items()}
        return self._symbol_files
