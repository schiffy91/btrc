"""Scope-aware, per-file strict-import visibility validation."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from typing import Any

from .. import ast_nodes as ast
from ..source_macros import (
    source_macro_name,
    source_macro_replacement_identifiers,
    source_macro_replacement_member_identifiers,
    source_symbol_directive,
)
from .dependencies import SourceDependencyGraph

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
        for field in fields(node):
            self.visit(getattr(node, field.name))


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
                name = source_macro_name(declaration.text) or ""
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
        directive = source_symbol_directive(declaration.text)
        if directive is None:
            return []
        members = set(source_macro_replacement_member_identifiers(directive))
        return [
            ImportReference(name, declaration.line or 1, declaration.col or 1)
            for name in source_macro_replacement_identifiers(directive)
            if name not in members
        ]

    def _references(self, declaration) -> list[ImportReference]:
        if isinstance(declaration, ast.PreprocessorDirective):
            return self._macro_references(declaration)
        collector = ImportReferenceCollector(set(getattr(declaration, "generic_params", ())))
        collector.visit(declaration)
        return collector.refs

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
