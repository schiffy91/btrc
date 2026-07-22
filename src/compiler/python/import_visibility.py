"""Per-file import visibility checks for resolved btrc programs.

Reference collection is scope-aware: identifiers bound by an enclosing
function/method/lambda parameter, local variable declaration, for-loop
variable, or catch variable are local and never treated as references to
top-level symbols. Type references always name top-level types or generic
parameters.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields, is_dataclass
from typing import Any

from . import ast_nodes as ast
from .frontend_models import SourceDependencyGraph
from .source_macros import source_macro_name

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


@dataclass(frozen=True)
class ImportReference:
    name: str
    line: int
    col: int


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

    def _in_frame(self, names, *nodes) -> None:
        self.scope.append(set(names))
        for node in nodes:
            self.visit(node)
        self.scope.pop()

    def visit(self, node: Any) -> None:
        if node is None:
            return
        if isinstance(node, ast.TypeExpr):
            self.add(node.base, node.line, node.col, typename=True)
            for arg in node.generic_args:
                self.visit(arg)
            self.visit(node.array_size)
            return
        if isinstance(node, ast.Identifier):
            self.add(node.name, node.line, node.col)
            return
        if isinstance(node, ast.ClassDecl):
            outer = self.generic_params
            self.generic_params = outer | set(node.generic_params)
            self.add(node.parent or "", node.line, node.col, typename=True)
            for iface in node.interfaces:
                self.add(iface, node.line, node.col, typename=True)
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
        if isinstance(node, (ast.FunctionDecl, ast.MethodDecl)):
            outer = self.generic_params
            self.generic_params = outer | set(getattr(node, "generic_params", []))
            self.visit(node.return_type)
            self._in_frame({p.name for p in node.params}, node.params, node.body)
            self.generic_params = outer
            return
        if isinstance(node, ast.LambdaExpr):
            self.visit(node.return_type)
            self.visit(node.captures)
            self._in_frame({p.name for p in node.params}, node.params, node.body)
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
        for field in fields(node):
            self.visit(getattr(node, field.name))


class ImportVisibilityChecker:
    """Validate AST references against resolved source dependency reachability."""

    def __init__(
        self,
        program: ast.Program,
        provenance: list[str],
        graph: SourceDependencyGraph,
    ):
        self.program = program
        self.provenance = provenance
        self.graph = graph

    @staticmethod
    def _decl_name(decl: Any) -> str:
        if isinstance(decl, ast.TypedefDecl):
            return decl.alias
        return getattr(decl, "name", "")

    def _line_file(self, line: int) -> str | None:
        if 1 <= line <= len(self.provenance):
            return self.provenance[line - 1]
        return None

    def _symbol_files(self) -> dict[str, set[str]]:
        symbols: dict[str, set[str]] = {}
        for decl in self.program.declarations:
            if isinstance(decl, ast.PreprocessorDirective):
                name = source_macro_name(decl.text) or ""
            elif isinstance(decl, _NAMED_DECLS):
                name = self._decl_name(decl)
            else:
                continue
            source_file = self._line_file(getattr(decl, "line", 0))
            if not source_file:
                continue
            canonical_file = SourceDependencyGraph.canonical_file(source_file)
            if name:
                symbols.setdefault(name, set()).add(canonical_file)
            if isinstance(decl, ast.EnumDecl):
                for value in decl.values:
                    if value.name:
                        symbols.setdefault(value.name, set()).add(canonical_file)
        return symbols

    def check(self) -> list[tuple[str, int, int]]:
        """Return visibility failures as ``(message, line, col)`` tuples."""

        symbol_files = self._symbol_files()
        reachable_cache: dict[str, set[str]] = {}
        errors: list[tuple[str, int, int]] = []

        for decl in self.program.declarations:
            if not isinstance(decl, _NAMED_DECLS):
                continue
            source_file = self._line_file(getattr(decl, "line", 0))
            if source_file is None:
                continue
            display_file = os.path.abspath(source_file)
            canonical_file = SourceDependencyGraph.canonical_file(source_file)
            reachable = reachable_cache.setdefault(
                canonical_file,
                self.graph.visibility_reachable(canonical_file),
            )
            collector = ImportReferenceCollector(set(getattr(decl, "generic_params", [])))
            collector.visit(decl)

            seen_refs: set[ImportReference] = set()
            for reference in collector.refs:
                if reference in seen_refs:
                    continue
                seen_refs.add(reference)
                declaring = symbol_files.get(reference.name)
                if not declaring or declaring & reachable:
                    continue
                owner = os.path.basename(sorted(declaring)[0])
                errors.append(
                    (
                        f"'{reference.name}' is defined in {owner} but "
                        f"{os.path.basename(display_file)} does not import it",
                        reference.line,
                        reference.col,
                    )
                )
        return errors
