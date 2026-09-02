"""Import resolution and strict per-file visibility."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

import src.compiler.python.syntax.ast.generated as ast
from src.compiler.python.syntax.ast.generated import (
    PackagePath,
    QuotedPath,
    RelativePath,
    StdGlob,
    StdModules,
)
from src.compiler.python.syntax.tokens import SourceSymbolDirective

from ..abi.hosted import HOSTED_ABI
from .packages import IncludeResolutionError, ResolvedPackages
from .sources import (
    CompilerStdlibSource,
    SourceDependencyGraph,
    SourceDirective,
    SourceDirectiveScanner,
    SourceDirectoryScanner,
    SourceFileReader,
    SourceReadError,
    StdlibRepository,
)


@dataclass(slots=True)
class ResolutionFrame:
    """One source file in progress during iterative import resolution."""

    absolute: str
    source_dir: str
    lines: list[str]
    by_start: dict[int, SourceDirective]
    covered: set[int]
    cursor: int = 0
    pending: list[tuple[str, int, str]] = field(default_factory=list)
    pending_cursor: int = 0

    def next_dependency(self) -> tuple[str, int, str] | None:
        """Take the next dependency spliced in by the current directive."""

        if self.pending_cursor >= len(self.pending):
            return None
        dependency = self.pending[self.pending_cursor]
        self.pending_cursor += 1
        return dependency

    def next_line(self) -> tuple[int, str] | None:
        """Advance one source line, or report that this frame is finished."""

        if self.cursor >= len(self.lines):
            return None
        line = self.lines[self.cursor]
        self.cursor += 1
        return self.cursor, line

    def directive_at(self, line_number: int) -> SourceDirective | None:
        return self.by_start.get(line_number)

    def emits(self, line_number: int) -> bool:
        return line_number not in self.covered


class ImportResolver:
    """Resolve one source graph against packages and a stdlib repository."""

    _C_TRIGRAPH_SUFFIXES = frozenset("=/'()!<>-")

    def __init__(
        self,
        stdlib: StdlibRepository | None = None,
        *,
        source_reader: SourceFileReader | None = None,
        directive_scanner: SourceDirectiveScanner | None = None,
        directory_scanner: SourceDirectoryScanner | None = None,
    ) -> None:
        self.stdlib = stdlib or StdlibRepository()
        self._source_reader = source_reader or SourceFileReader()
        self._directives = directive_scanner or SourceDirectiveScanner()
        self._directories = directory_scanner or SourceDirectoryScanner()

    def import_paths(
        self,
        spec,
        source_dir: str,
        packages: ResolvedPackages,
    ) -> list[str]:
        """Resolve a parsed import specification to filesystem paths."""
        if isinstance(spec, StdGlob):
            return [
                os.path.join(self.stdlib.directory(), filename) for filename in self.stdlib.relaxed_composition_files()
            ]
        if isinstance(spec, StdModules):
            return [self._stdlib_module_path(name) for name in spec.names]
        if isinstance(spec, PackagePath):
            dotted = ".".join(spec.segments)
            return list(packages.paths_for_import(dotted, source_dir)) or self._relative_paths(
                dotted,
                source_dir,
            )
        if isinstance(spec, (RelativePath, QuotedPath)):
            return list(packages.paths_for_import(spec.path, source_dir)) or self._relative_paths(
                spec.path,
                source_dir,
            )
        raise IncludeResolutionError(f"unsupported import spec: {spec!r}")

    def resolve_mapped(
        self,
        source: str,
        source_path: str,
        packages: ResolvedPackages,
        included: set[str] | None = None,
        *,
        exit_on_error: bool = True,
    ) -> tuple[str, list[str], list[tuple[str, int]], SourceDependencyGraph]:
        """Resolve a source graph with file and original-line provenance."""
        graph = SourceDependencyGraph()
        try:
            traced = self._resolve_traced(
                source,
                source_path,
                packages,
                set() if included is None else included,
                graph,
            )
        except IncludeResolutionError as error:
            if not exit_on_error:
                raise
            print(f"error: {error}", file=sys.stderr)
            raise SystemExit(1) from error

        resolved = "\n".join(text for text, _, _ in traced)
        provenance = [path for _, path, _ in traced]
        source_positions = [(path, line) for _, path, line in traced]
        return resolved, provenance, source_positions, graph

    def resolve(
        self,
        source: str,
        source_path: str,
        packages: ResolvedPackages,
        included: set[str] | None = None,
        *,
        exit_on_error: bool = True,
    ) -> str:
        """Resolve a source graph to its textually composed source."""
        resolved, _, _, _ = self.resolve_mapped(
            source,
            source_path,
            packages,
            included,
            exit_on_error=exit_on_error,
        )
        return resolved

    def resolve_with_graph(
        self,
        source: str,
        source_path: str,
        packages: ResolvedPackages,
        *,
        exit_on_error: bool = True,
    ) -> tuple[str, list[str], SourceDependencyGraph]:
        """Resolve source with file provenance and its dependency graph."""
        resolved, provenance, _, graph = self.resolve_mapped(
            source,
            source_path,
            packages,
            exit_on_error=exit_on_error,
        )
        return resolved, provenance, graph

    def _resolve_include_path(self, include_path: str, source_dir: str) -> str:
        local = os.path.join(source_dir, include_path)
        if os.path.exists(local):
            return local
        stdlib_path = self.stdlib.find_file(include_path)
        if stdlib_path is not None:
            return stdlib_path
        raise IncludeResolutionError(
            f"include file '{include_path}' not found\n  searched: {source_dir}\n  searched: {self.stdlib.directory()}"
        )

    def _stdlib_module_path(self, name: str) -> str:
        filename = name if name.endswith(".btrc") else f"{name}.btrc"
        path = self.stdlib.find_file(filename)
        if path is None:
            raise IncludeResolutionError(f"stdlib import 'std.{name}' not found\n  searched: {self.stdlib.directory()}")
        return path

    def _relative_paths(self, spec: str, source_dir: str) -> list[str]:
        recursive = spec.endswith("/**")
        direct_glob = spec.endswith("/*")
        if recursive or direct_glob:
            base = spec[:-3] if recursive else spec[:-2]
            root = base if os.path.isabs(base) else os.path.join(source_dir, base)
            if not os.path.isdir(root):
                raise IncludeResolutionError(f"import directory '{spec}' not found\n  searched: {root}")
            return self._directories.scan(root, recursive=recursive)

        candidate = spec if os.path.isabs(spec) else os.path.join(source_dir, spec)
        if os.path.isdir(candidate):
            return self._directories.scan(candidate, recursive=False)
        if os.path.exists(candidate):
            return [candidate]
        return [self._resolve_include_path(spec, source_dir)]

    def _read_source(self, path: str) -> str:
        try:
            return self._source_reader.read(path)
        except SourceReadError as error:
            raise IncludeResolutionError(str(error)) from error

    def render_c_include(self, path: str) -> str:
        """Return a safe quoted C include directive for one imported C file."""

        for character in path:
            if character == '"' or ord(character) < 0x20 or ord(character) == 0x7F:
                raise IncludeResolutionError(
                    f"cannot import C file with a quote or control character in its path: {path!r}"
                )
        for index in range(len(path) - 2):
            if path[index : index + 2] == "??" and path[index + 2] in self._C_TRIGRAPH_SUFFIXES:
                raise IncludeResolutionError(f"cannot import C file whose path contains a C trigraph: {path!r}")
        return f'#include "{path}"'

    def _open_frame(
        self,
        source: str,
        source_path: str,
        included: set[str],
        graph: SourceDependencyGraph,
    ) -> ResolutionFrame | None:
        """Register one source in the graph and start traversing it once."""

        absolute = os.path.abspath(source_path)
        identity = os.path.normcase(os.path.realpath(absolute))
        graph.ensure_source(absolute)
        if identity in included:
            return None
        included.add(identity)
        directives = self._directives.scan(source)
        return ResolutionFrame(
            absolute=absolute,
            source_dir=os.path.dirname(absolute),
            lines=source.split("\n"),
            by_start={directive.start: directive for directive in directives},
            covered={line for directive in directives for line in range(directive.start, directive.end + 1)},
        )

    def _splice_dependencies(
        self,
        frame: ResolutionFrame,
        directive: SourceDirective,
        line_number: int,
        packages: ResolvedPackages,
        graph: SourceDependencyGraph,
    ) -> None:
        """Queue the sources one directive contributes, in resolution order."""

        frame.pending.clear()
        frame.pending_cursor = 0
        if directive.kind == "btrc_include":
            target = os.path.abspath(
                self._resolve_include_path(
                    directive.payload,
                    frame.source_dir,
                )
            )
            graph.add_include(frame.absolute, target)
            frame.pending.append((target, line_number, "include"))
            return
        frame.pending.extend(
            (path, line_number, "import")
            for path in self.import_paths(
                directive.payload,
                frame.source_dir,
                packages,
            )
        )

    def _enter_dependency(
        self,
        frame: ResolutionFrame,
        dependency: tuple[str, int, str],
        packages: ResolvedPackages,
        included: set[str],
        graph: SourceDependencyGraph,
        output: list[tuple[str, str, int]],
    ) -> ResolutionFrame | None:
        """Inline one dependency, returning a child frame for btrc sources."""

        path, line_number, kind = dependency
        absolute = os.path.abspath(path)
        if kind == "import":
            graph.add_import(frame.absolute, absolute)
        if path.endswith(".c"):
            identity = os.path.normcase(os.path.realpath(absolute))
            if identity in included:
                return None
            included.add(identity)
            output.append((self.render_c_include(absolute), frame.absolute, line_number))
            return None
        return self._open_frame(
            self._read_source(path),
            path,
            included,
            graph,
        )

    def _resolve_traced(
        self,
        source: str,
        source_path: str,
        packages: ResolvedPackages,
        included: set[str],
        graph: SourceDependencyGraph,
    ) -> list[tuple[str, str, int]]:
        """Compose one source graph depth-first without host recursion.

        An explicit frame stack replaces recursive descent so import nesting is
        limited only by available memory rather than by a compiler-defined depth
        ceiling or the interpreter's call stack.
        """

        output: list[tuple[str, str, int]] = []
        root = self._open_frame(source, source_path, included, graph)
        stack: list[ResolutionFrame] = [] if root is None else [root]
        while stack:
            frame = stack[-1]
            dependency = frame.next_dependency()
            if dependency is not None:
                child = self._enter_dependency(
                    frame,
                    dependency,
                    packages,
                    included,
                    graph,
                    output,
                )
                if child is not None:
                    stack.append(child)
                continue
            advanced = frame.next_line()
            if advanced is None:
                stack.pop()
                continue
            line_number, line = advanced
            directive = frame.directive_at(line_number)
            if directive is not None:
                self._splice_dependencies(frame, directive, line_number, packages, graph)
            elif frame.emits(line_number):
                output.append((line, frame.absolute, line_number))
        return output


_NAMED_DECLS = (
    ast.ClassDecl,
    ast.InterfaceDecl,
    ast.FunctionDecl,
    ast.StructDecl,
    ast.EnumDecl,
    ast.RichEnumDecl,
    ast.TypedefDecl,
    ast.VarDeclStmt,
)
_REFERENCE_DECLS = _NAMED_DECLS + (ast.PreprocessorDirective,)


class FrontendVisibilityError(Exception):
    """Strict-import visibility failures."""

    def __init__(self, errors: list[tuple[str, int, int]]):
        self.errors = errors
        super().__init__("strict import visibility failed")


@dataclass(frozen=True)
class ImportReference:
    name: str
    line: int
    col: int


@dataclass(frozen=True)
class ImportVisibilityFailure:
    """One reference whose defining source is not reachable."""

    name: str
    source_file: str
    owner_file: str
    line: int
    col: int

    @property
    def message(self) -> str:
        return (
            f"'{self.name}' is defined in {os.path.basename(self.owner_file)} but "
            f"{os.path.basename(self.source_file)} does not import it"
        )

    def as_diagnostic(self) -> tuple[str, int, int]:
        return self.message, self.line, self.col


class ImportReferenceCollector:
    """Collect top-level references while respecting lexical scopes."""

    def __init__(self, generic_params: set[str]):
        self.refs: list[ImportReference] = []
        self.generic_params = generic_params
        self.scope: list[set[str]] = [set()]

    def _bound(self, name: str) -> bool:
        return any(name in frame for frame in self.scope)

    def add(self, name: str, line: int, col: int, *, typename: bool = False) -> None:
        if not name or name in self.generic_params:
            return
        if not typename and self._bound(name):
            return
        self.refs.append(ImportReference(name, line or 1, col or 1))

    def _in_frame(self, names: Iterable[str], *nodes) -> None:
        self.scope.append(set(names))
        for node in nodes:
            self.visit(node)
        self.scope.pop()

    def _visit_callable(self, node, *, implicit: Iterable[str] = ()) -> None:
        """Visit defaults left-to-right, binding each parameter afterwards."""

        outer = self.generic_params
        self.generic_params = outer | set(getattr(node, "generic_params", ()))
        self.visit(node.return_type)
        self.scope.append(set(implicit))
        for parameter in node.params:
            self.visit(parameter.type)
            self.visit(parameter.default)
            self.scope[-1].add(parameter.name)
        self.visit(getattr(node, "body", None))
        self.scope.pop()
        self.generic_params = outer

    def visit(self, node: Any) -> None:
        if node is None:
            return
        if isinstance(node, ast.TypeExpr):
            self.add(node.base, node.line, node.col, typename=True)
            for argument in node.generic_args:
                self.visit(argument)
            self.visit(node.array_size)
            return
        if isinstance(node, ast.Identifier):
            self.add(node.name, node.line, node.col)
            return
        if isinstance(node, ast.ClassDecl):
            outer = self.generic_params
            self.generic_params = outer | set(node.generic_params)
            self.add(node.parent or "", node.line, node.col, typename=True)
            for interface in node.interfaces:
                self.add(interface, node.line, node.col, typename=True)
            self.visit(node.members)
            self.generic_params = outer
            return
        if isinstance(node, ast.InterfaceDecl):
            outer = self.generic_params
            self.generic_params = outer | set(node.generic_params)
            self.add(node.parent or "", node.line, node.col, typename=True)
            self.visit(node.methods)
            self.generic_params = outer
            return
        if isinstance(node, ast.FunctionDecl):
            self._visit_callable(node)
            return
        if isinstance(node, ast.MethodDecl):
            implicit = () if node.access == "class" else ("self",)
            self._visit_callable(node, implicit=implicit)
            return
        if isinstance(node, ast.MethodSig):
            self._visit_callable(node)
            return
        if isinstance(node, ast.PropertyDecl):
            self.visit(node.type)
            implicit = () if node.access == "class" else ("self",)
            self._in_frame(implicit, node.getter_body)
            self._in_frame((*implicit, "value"), node.setter_body)
            return
        if isinstance(node, ast.RichEnumDecl):
            for variant in node.variants:
                self.scope.append(set())
                for parameter in variant.params:
                    self.visit(parameter.type)
                    self.visit(parameter.default)
                    self.scope[-1].add(parameter.name)
                self.scope.pop()
            return
        if isinstance(node, ast.LambdaExpr):
            self.visit(node.captures)
            self._visit_callable(node)
            return
        if isinstance(node, ast.Block):
            self._in_frame((), node.statements)
            return
        if isinstance(node, ast.VarDeclStmt):
            self.visit(node.type)
            self.visit(node.initializer)
            self.scope[-1].add(node.name)
            return
        if isinstance(node, (ast.ForInStmt, ast.ParallelForStmt)):
            self.visit(node.iterable)
            names = {node.var_name, getattr(node, "var_name2", None)} - {None}
            self._in_frame(names, node.body)
            return
        if isinstance(node, ast.CForStmt):
            self._in_frame((), node.init, node.condition, node.update, node.body)
            return
        if isinstance(node, ast.SwitchStmt):
            self.visit(node.value)
            for case in node.cases:
                self.visit(case.value)
                self._in_frame((), case.body)
            return
        if isinstance(node, ast.TryCatchStmt):
            self.visit(node.try_block)
            self.visit(node.catch_type)
            self._in_frame({node.catch_var}, node.catch_block)
            self.visit(node.finally_block)
            return
        if isinstance(node, list):
            for item in node:
                self.visit(item)
            return
        if not is_dataclass(node):
            return
        for member in fields(node):
            self.visit(getattr(node, member.name))


class ImportVisibilityChecker:
    """Validate AST references against resolved dependency reachability."""

    def __init__(
        self,
        program: ast.Program,
        provenance: tuple[str, ...] | list[str],
        graph: SourceDependencyGraph,
        *,
        external_symbol_files: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        self.program = program
        self.provenance = provenance
        self.graph = graph
        self.external_symbol_files = external_symbol_files or {}

    @staticmethod
    def _decl_name(declaration: Any) -> str:
        if isinstance(declaration, ast.TypedefDecl):
            return declaration.alias
        return getattr(declaration, "name", "")

    def _line_file(self, line: int) -> str | None:
        if 1 <= line <= len(self.provenance):
            return self.provenance[line - 1]
        return None

    def _declaration_file(self, declaration: Any) -> str | None:
        """Resolve provenance, falling back to native per-file AST metadata."""

        return self._line_file(getattr(declaration, "line", 0)) or getattr(
            declaration,
            "source_file",
            None,
        )

    def _symbol_files(self) -> dict[str, set[str]]:
        symbols = {
            name: {SourceDependencyGraph.canonical_file(path) for path in paths}
            for name, paths in self.external_symbol_files.items()
        }
        for declaration in self.program.declarations:
            if isinstance(declaration, ast.PreprocessorDirective):
                directive = SourceSymbolDirective.parse(declaration.text)
                name = directive.name if directive is not None and directive.operation == "define" else ""
            elif isinstance(declaration, _NAMED_DECLS):
                name = self._decl_name(declaration)
            else:
                continue
            source_file = self._declaration_file(declaration)
            if not source_file:
                continue
            canonical_file = SourceDependencyGraph.canonical_file(source_file)
            if name:
                symbols.setdefault(name, set()).add(canonical_file)
            if isinstance(declaration, ast.EnumDecl):
                for value in declaration.values:
                    if value.name:
                        symbols.setdefault(value.name, set()).add(canonical_file)
            elif isinstance(declaration, ast.RichEnumDecl):
                for variant in declaration.variants:
                    if variant.name:
                        symbols.setdefault(variant.name, set()).add(canonical_file)
        return symbols

    @staticmethod
    def _macro_references(declaration: ast.PreprocessorDirective) -> list[ImportReference]:
        directive = SourceSymbolDirective.parse(declaration.text)
        if directive is None:
            return []
        members = set(directive.replacement_member_identifiers())
        return [
            ImportReference(name, declaration.line or 1, declaration.col or 1)
            for name in directive.replacement_identifiers()
            if name not in members
        ]

    def _references(self, declaration) -> list[ImportReference]:
        if isinstance(declaration, ast.PreprocessorDirective):
            return self._macro_references(declaration)
        collector = ImportReferenceCollector(set(getattr(declaration, "generic_params", ())))
        collector.visit(declaration)
        return collector.refs

    @staticmethod
    def _binds_to_compiler_owned_hosted_symbol(
        declaration: Any,
        reference: ImportReference,
    ) -> bool:
        """Keep authenticated stdlib references bound to the hosted ABI.

        Source functions may intentionally shadow hosted names, but compiler
        stdlib internals retain their canonical hosted binding.  Visibility
        must make the same provenance-sensitive decision as semantic analysis
        instead of treating the user shadow as the referenced declaration.
        """

        return CompilerStdlibSource.authenticated(
            getattr(declaration, "source_file", None),
        ) and HOSTED_ABI.owned_name(reference.name)

    def failures(
        self,
        *,
        active_file: str | None = None,
    ) -> list[ImportVisibilityFailure]:
        """Return structured references hidden by missing imports."""

        symbol_files = self._symbol_files()
        reachable_cache: dict[str, set[str]] = {}
        failures: list[ImportVisibilityFailure] = []
        canonical_active = SourceDependencyGraph.canonical_file(active_file) if active_file is not None else None

        for declaration in self.program.declarations:
            if not isinstance(declaration, _REFERENCE_DECLS):
                continue
            source_file = self._declaration_file(declaration)
            if source_file is None:
                continue
            display_file = os.path.abspath(source_file)
            canonical_file = SourceDependencyGraph.canonical_file(source_file)
            if canonical_active is not None and canonical_file != canonical_active:
                continue
            reachable = reachable_cache.setdefault(
                canonical_file,
                self.graph.visibility_reachable(canonical_file),
            )

            seen_refs: set[ImportReference] = set()
            for reference in self._references(declaration):
                if reference in seen_refs:
                    continue
                seen_refs.add(reference)
                if self._binds_to_compiler_owned_hosted_symbol(
                    declaration,
                    reference,
                ):
                    continue
                declaring = symbol_files.get(reference.name)
                if not declaring or declaring & reachable:
                    continue
                failures.append(
                    ImportVisibilityFailure(
                        name=reference.name,
                        source_file=display_file,
                        owner_file=sorted(declaring)[0],
                        line=reference.line,
                        col=reference.col,
                    )
                )
        return failures

    def check(self, *, active_file: str | None = None) -> list[tuple[str, int, int]]:
        """Return visibility failures as ``(message, line, col)`` tuples."""

        return [failure.as_diagnostic() for failure in self.failures(active_file=active_file)]


__all__ = (
    "FrontendVisibilityError",
    "ImportReference",
    "ImportReferenceCollector",
    "ImportResolver",
    "ImportVisibilityChecker",
    "ImportVisibilityFailure",
    "ResolutionFrame",
)
