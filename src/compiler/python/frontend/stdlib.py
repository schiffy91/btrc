"""Standard-library discovery, composition, caching, and symbol ownership."""

from __future__ import annotations

import os
import re
from contextlib import suppress

from .. import ast_nodes as ast
from ..artifacts.cache.compiler_cache import CacheDirectory, ToolchainFingerprint
from ..frontend_limits import SourceResolutionPolicy
from ..lexer import Lexer
from ..numeric_literals import NumericLiteralSemantics
from ..parser.parser import Parser
from ..pipeline.models import StdlibSource
from ..pkg import IncludeResolutionError
from ..source_macros import SourceSymbolDirective
from ..stdlib_ast_cache import StdlibAstCache
from .dependencies import SourceDependencyGraph
from .source_io import SourceDirectiveScanner, SourceFileReader, SourceReadError

_DEFAULT_STDLIB_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "stdlib"))
_PRIORITY_FILES = (
    "vector.btrc",
    "list.btrc",
    "strings.btrc",
    "platform.btrc",
    "process.btrc",
    "fs.btrc",
    "daemon.btrc",
    "ui.btrc",
)
_CLASS_NAME = re.compile(
    r"^\s*(?:abstract\s+)?class\s+(\w+)(?:\s*<[^>\n]+>)?\s*"
    r"(?:extends\s+\w+(?:\s*<[^>\n]+>)?\s*)?"
    r"(?:implements\s+\w+(?:\s*,\s*\w+)*\s*)?\{",
    re.MULTILINE,
)
_INTERFACE_NAME = re.compile(
    r"^\s*interface\s+(\w+)(?:\s*<[^>\n]+>)?\s*"
    r"(?:extends\s+\w+(?:\s*<[^>\n]+>)?\s*)?\{",
    re.MULTILINE,
)


class StdlibRepository:
    """Own access to the compiler's canonical standard-library sources."""

    def __init__(
        self,
        ast_cache: StdlibAstCache | None = None,
        cache_directory: CacheDirectory | None = None,
        fingerprint: ToolchainFingerprint | None = None,
        source_reader: SourceFileReader | None = None,
        directive_scanner: SourceDirectiveScanner | None = None,
        *,
        directory: str | None = None,
        resolution_policy: SourceResolutionPolicy | None = None,
        numeric_literals: NumericLiteralSemantics | None = None,
    ) -> None:
        self.resolution_policy = resolution_policy or SourceResolutionPolicy()
        self.ast_cache = ast_cache or StdlibAstCache()
        self._cache_directory = cache_directory or CacheDirectory()
        self._ast_version = (fingerprint or ToolchainFingerprint()).digest("frontend")
        self._source_reader = source_reader or SourceFileReader(self.resolution_policy.max_source_bytes)
        self._directives = directive_scanner or SourceDirectiveScanner()
        self._directory = os.path.abspath(directory or _DEFAULT_STDLIB_DIRECTORY)
        self._symbol_files: dict[str, frozenset[str]] | None = None
        self.numeric_literals = numeric_literals if numeric_literals is not None else NumericLiteralSemantics()

    @property
    def ast_version(self) -> str:
        return self._ast_version

    def directory(self) -> str:
        return self._directory

    def discover_files(self) -> list[str]:
        """Return root stdlib modules in their deterministic composition order."""
        try:
            files = sorted(name for name in os.listdir(self._directory) if name.endswith(".btrc"))
        except OSError:
            return []
        prioritized = [name for name in _PRIORITY_FILES if name in files]
        prioritized.extend(name for name in files if name not in _PRIORITY_FILES)
        return prioritized

    def find_file(self, include_path: str) -> str | None:
        """Find a stdlib file by root-relative path or nested basename."""
        direct = os.path.join(self._directory, include_path)
        if os.path.isfile(direct):
            return direct
        filename = os.path.basename(include_path)
        try:
            entries = os.listdir(self._directory)
        except OSError:
            return None
        for entry in entries:
            candidate = os.path.join(self._directory, entry, filename)
            if os.path.isfile(candidate):
                return candidate
        return None

    def defined_names(self, source: str) -> set[str]:
        return set(_CLASS_NAME.findall(source)) | set(_INTERFACE_NAME.findall(source))

    def source(self, user_source: str = "") -> str:
        return self.source_mapped(user_source).source

    def source_mapped(self, user_source: str = "") -> StdlibSource:
        """Compose relaxed-mode stdlib text with native source positions."""
        user_names = self.defined_names(user_source)
        lines: list[str] = []
        source_positions: list[tuple[str, int]] = []
        budget = self.resolution_policy.new_budget()
        for filename in self.discover_files():
            path = os.path.join(self._directory, filename)
            if not os.path.isfile(path):
                continue
            try:
                content = self._source_reader.read(path)
            except SourceReadError as error:
                raise IncludeResolutionError(str(error)) from error
            budget.enter(content, path, 0)
            if self.defined_names(content) & user_names:
                continue
            file_lines, file_positions = self._source_without_imports(
                content,
                path,
            )
            lines.extend(file_lines)
            source_positions.extend(file_positions)
        return StdlibSource(
            source="\n".join(lines),
            source_positions=tuple(source_positions),
        )

    def cached_declarations(self, stdlib_source: str) -> list:
        """Return independently decoded declarations from the persistent cache."""
        try:
            cache_dir = self._cache_directory.resolve()
        except OSError:
            return self._parse_declarations(stdlib_source)
        self.ast_cache.prune(cache_dir)
        content_hash = self.ast_cache.source_hash(stdlib_source)
        path = self.ast_cache.path(
            cache_dir,
            self.ast_version,
            stdlib_source,
        )
        cached = self.ast_cache.load(path, content_hash)
        if cached is not None:
            return cached
        declarations = self._parse_declarations(stdlib_source)
        with suppress(OSError, TypeError, ValueError):
            self.ast_cache.store(path, content_hash, declarations)
        return declarations

    def _parse_declarations(self, stdlib_source: str) -> list:
        tokens = Lexer(stdlib_source, "<stdlib>").tokenize()
        return (
            Parser(
                tokens,
                self.numeric_literals,
            )
            .parse()
            .declarations
        )

    def _source_without_imports(
        self,
        content: str,
        path: str,
    ) -> tuple[list[str], list[tuple[str, int]]]:
        covered = {
            line
            for directive in self._directives.scan(content)
            if directive.kind == "import"
            for line in range(directive.start, directive.end + 1)
        }
        lines: list[str] = []
        positions: list[tuple[str, int]] = []
        for line_number, line in enumerate(content.split("\n"), start=1):
            if line_number in covered:
                continue
            lines.append(line)
            positions.append((path, line_number))
        return lines, positions

    @staticmethod
    def _declaration_names(declaration) -> tuple[str, ...]:
        if isinstance(declaration, ast.PreprocessorDirective):
            directive = SourceSymbolDirective.parse(declaration.text)
            return (directive.name,) if directive is not None and directive.operation == "define" else ()
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
                source = self._source_reader.read(path)
            except SourceReadError as error:
                raise IncludeResolutionError(str(error)) from error
            program = Parser(
                Lexer(source, path).tokenize(),
                self.numeric_literals,
            ).parse()
            canonical = SourceDependencyGraph.canonical_file(path)
            for declaration in program.declarations:
                for name in self._declaration_names(declaration):
                    owners.setdefault(name, set()).add(canonical)
        self._symbol_files = {name: frozenset(paths) for name, paths in owners.items()}
        return self._symbol_files
