"""Per-file import visibility checks for resolved btrc programs.

Reference collection is scope-aware: identifiers bound by an enclosing
function/method/lambda parameter, local variable declaration, for-loop
variable, or catch variable are *local* and never treated as references to
top-level symbols — a local named like a top-level symbol must not demand an
import. Only expression identifiers are scope-filtered; type references
(TypeExpr) always name top-level types or generic parameters.
"""

from __future__ import annotations

import os
from collections import deque
from dataclasses import fields, is_dataclass
from typing import Any

from . import ast_nodes as ast

_NAMED_DECLS = (
    ast.ClassDecl,
    ast.InterfaceDecl,
    ast.FunctionDecl,
    ast.StructDecl,
    ast.EnumDecl,
    ast.RichEnumDecl,
    ast.TypedefDecl,
)


def _decl_name(decl: Any) -> str:
    if isinstance(decl, ast.TypedefDecl):
        return decl.alias
    return getattr(decl, "name", "")


def _line_file(provenance: list[str], line: int) -> str | None:
    if 1 <= line <= len(provenance):
        return provenance[line - 1]
    return None


def _canonical_file(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _canonical_graph(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    canonical: dict[str, set[str]] = {}
    for source, targets in graph.items():
        canonical.setdefault(_canonical_file(source), set()).update(_canonical_file(target) for target in targets)
    return canonical


def _reachable_files(start: str, graph: dict[str, set[str]]) -> set[str]:
    seen = {start}
    queue = deque(graph.get(start, set()))
    while queue:
        path = queue.popleft()
        if path in seen:
            continue
        seen.add(path)
        queue.extend(graph.get(path, set()) - seen)
    return seen


class _RefCollector:
    """Walk a declaration collecting top-level name references.

    ``scope`` is a stack of frames holding locally-bound names (params,
    var-decls, loop/catch variables); identifiers bound in any active frame
    are skipped.
    """

    def __init__(self, generic_params: set[str]):
        self.refs: list[tuple[str, int, int]] = []
        self.generic_params = generic_params
        self.scope: list[set[str]] = [set()]

    def _bound(self, name: str) -> bool:
        return any(name in frame for frame in self.scope)

    def add(self, name: str, line: int, col: int, *, typename: bool = False) -> None:
        if not name or name in self.generic_params:
            return
        if not typename and self._bound(name):
            return
        self.refs.append((name, line or 1, col or 1))

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
            self.visit(node.return_type)
            self._in_frame({p.name for p in node.params}, node.params, node.body)
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
            self.scope[-1].add(node.name)  # bound from here on
            return
        if isinstance(node, (ast.ForInStmt, ast.ParallelForStmt)):
            self.visit(node.iterable)
            names = {node.var_name, getattr(node, "var_name2", None)} - {None}
            self._in_frame(names, node.body)
            return
        if isinstance(node, ast.CForStmt):
            # The init var-decl scopes over condition/update/body.
            self._in_frame((), node.init, node.condition, node.update, node.body)
            return
        if isinstance(node, ast.TryCatchStmt):
            self.visit(node.try_block)
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


def _symbol_files(program: ast.Program, provenance: list[str]) -> dict[str, set[str]]:
    """Every file declaring each top-level name (duplicates keep all files)."""
    symbols: dict[str, set[str]] = {}
    for decl in program.declarations:
        if not isinstance(decl, _NAMED_DECLS):
            continue
        name = _decl_name(decl)
        source_file = _line_file(provenance, getattr(decl, "line", 0))
        if name and source_file:
            symbols.setdefault(name, set()).add(_canonical_file(source_file))
    return symbols


def check_visibility(
    program: ast.Program, provenance: list[str], graph: dict[str, set[str]]
) -> list[tuple[str, int, int]]:
    """Return import-visibility errors as ``(message, line, col)`` tuples.

    A reference is satisfied when *any* file declaring the symbol is the
    referencing file itself or reachable through its imports.
    """
    graph = _canonical_graph(graph)
    symbol_files = _symbol_files(program, provenance)
    reachable_cache: dict[str, set[str]] = {}
    errors: list[tuple[str, int, int]] = []

    for decl in program.declarations:
        if not isinstance(decl, _NAMED_DECLS):
            continue
        source_file = _line_file(provenance, getattr(decl, "line", 0))
        if source_file is None:
            continue
        display_file = os.path.abspath(source_file)
        source_file = _canonical_file(source_file)
        reachable = reachable_cache.setdefault(source_file, _reachable_files(source_file, graph))
        collector = _RefCollector(set(getattr(decl, "generic_params", [])))
        collector.visit(decl)

        seen_refs: set[tuple[str, int, int]] = set()
        for name, line, col in collector.refs:
            ref_key = (name, line, col)
            if ref_key in seen_refs:
                continue
            seen_refs.add(ref_key)
            declaring = symbol_files.get(name)
            if not declaring or declaring & reachable:
                continue
            shown = os.path.basename(sorted(declaring)[0])
            errors.append(
                (
                    f"'{name}' is defined in {shown} but {os.path.basename(display_file)} does not import it",
                    line,
                    col,
                )
            )
    return errors
