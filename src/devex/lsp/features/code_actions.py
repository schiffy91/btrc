"""Quick-fix and source-import code actions."""

from __future__ import annotations

import os
from dataclasses import dataclass

from lsprotocol import types as lsp

from src.compiler.python.syntax.tokens import TokenKind
from src.devex.lsp.analysis.document import DocumentAnalysis
from src.devex.lsp.analysis.resolution import SemanticResolver
from src.devex.lsp.catalog.builtins import BuiltinCatalog

_MAX_EDIT_DISTANCE = 2
_PRIMITIVE_TYPES = frozenset({"int", "float", "double", "long", "short", "char", "bool", "void", "unsigned"})


@dataclass(frozen=True)
class ModuleImportCandidate:
    """One exact symbol owner that can be imported into the active file."""

    spec: str
    owner_file: str


_MIN_SUGGEST_LEN = 3


class CodeActionProvider:
    """Quick-fix and source-import code actions."""

    def __init__(self, catalog: BuiltinCatalog, resolver: SemanticResolver, navigation, workspace) -> None:
        self.catalog = catalog
        self.resolver = resolver
        self.navigation = navigation
        self.workspace = workspace

    def _known_names(self, result: DocumentAnalysis) -> set[str]:
        """Every top-level symbol name visible to the analyzer (composed program)."""
        names: set[str] = set(_PRIMITIVE_TYPES | self.catalog.type_names)
        a = result.analyzed
        if a is not None:
            names |= set(a.class_table)
            names |= set(a.function_table)
            names |= set(a.enum_table)
            names |= set(a.rich_enum_table)
            names |= set(a.interface_table)
        dmap = self.navigation.definition_map(result)
        names |= set(dmap.struct_defs)
        names |= set(dmap.typedef_defs)
        names |= set(dmap.enum_defs)
        return names

    def _suggestable_names(self, result: DocumentAnalysis) -> list[str]:
        """Named decls that a typo could be corrected *to* (no builtins/keywords)."""
        a = result.analyzed
        names: set[str] = set()
        if a is not None:
            names |= set(a.class_table)
            names |= set(a.function_table)
            names |= set(a.enum_table)
            names |= set(a.rich_enum_table)
            names |= set(a.interface_table)
        dmap = self.navigation.definition_map(result)
        names |= set(dmap.struct_defs)
        names |= set(dmap.typedef_defs)
        return [n for n in names if n]

    def _levenshtein(self, a: str, b: str, cap: int) -> int:
        """Edit distance, short-circuiting once the running minimum exceeds *cap*."""
        if abs(len(a) - len(b)) > cap:
            return cap + 1
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            row_min = i
            for j, cb in enumerate(b, 1):
                cost = 0 if ca == cb else 1
                v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
                cur.append(v)
                row_min = min(row_min, v)
            if row_min > cap:
                return cap + 1
            prev = cur
        return prev[-1]

    def _closest(self, name: str, candidates: list[str]) -> str | None:
        """The single closest candidate within ``_MAX_EDIT_DISTANCE``, if unique."""
        if len(name) < _MIN_SUGGEST_LEN:
            return None
        best: str | None = None
        best_d = _MAX_EDIT_DISTANCE + 1
        tie = False
        for cand in candidates:
            if cand == name:
                return None
            d = self._levenshtein(name.lower(), cand.lower(), _MAX_EDIT_DISTANCE)
            if d < best_d:
                best_d, best, tie = (d, cand, False)
            elif d == best_d:
                tie = True
        if best is None or best_d > _MAX_EDIT_DISTANCE or tie:
            return None
        return best

    def _module_imports(self, result: DocumentAnalysis):
        """Build symbol-to-owner candidates from workspace and stdlib units.

        The active file's own decls are excluded. A stdlib unit maps to
        ``std.<module>``; a workspace file maps to a relative ``"path"`` import.
        """
        stdlib_dir = os.path.abspath(self.workspace.stdlib_directory())
        active = os.path.abspath(result.path) if result.path else None
        active_dir = os.path.dirname(active) if active else None
        manifest = self.workspace.project_manifest(active) if active else None
        project_root = os.path.dirname(manifest) if manifest else active_dir
        by_name: dict[str, list[ModuleImportCandidate]] = {}

        def consider(path: str, defined: frozenset):
            ap = os.path.abspath(path)
            if ap == active:
                return
            spec = self._import_spec_for(ap, stdlib_dir, active)
            if spec is None:
                return
            for name in defined:
                candidate = ModuleImportCandidate(spec=spec, owner_file=ap)
                candidates = by_name.setdefault(name, [])
                if candidate not in candidates:
                    candidates.append(candidate)

        for unit in self.workspace.stdlib_units():
            consider(unit.path, unit.defined_names)
        for unit in self.workspace.cached_units(project_root):
            if self.workspace.shares_project_manifest(unit.path, manifest):
                consider(unit.path, unit.defined_names)
        return by_name

    def _import_spec_for(self, path: str, stdlib_dir: str, active: str | None) -> str | None:
        if path.startswith(stdlib_dir + os.sep):
            module = os.path.splitext(os.path.basename(path))[0]
            return f"std.{module}"
        if active is None:
            return None
        rel = os.path.relpath(path, os.path.dirname(active))
        return f'"{rel}"'

    def _existing_imports(self, result: DocumentAnalysis) -> set[str]:
        """Import-spec strings already present in the active file."""
        from src.compiler.python.syntax.ast.generated import (
            ImportDecl,
            PackagePath,
            QuotedPath,
            RelativePath,
            StdModules,
        )

        out: set[str] = set()
        for decl in self.resolver.active_decls(result):
            if not isinstance(decl, ImportDecl):
                continue
            spec = decl.spec
            if isinstance(spec, StdModules):
                for n in spec.names:
                    out.add(f"std.{n}")
            elif isinstance(spec, (QuotedPath, RelativePath)):
                out.add(f'"{spec.path}"')
            elif isinstance(spec, PackagePath):
                out.add(".".join(spec.segments))
        return out

    def _import_insert_line(self, result: DocumentAnalysis) -> int:
        """0-based line to insert a new import: after the last existing import."""
        from src.compiler.python.syntax.ast.generated import ImportDecl

        last = 0
        for decl in self.resolver.active_decls(result):
            if isinstance(decl, ImportDecl) and decl.line:
                last = max(last, decl.line)
        return last

    def _actionable_identifiers(self, result: DocumentAnalysis, rng: lsp.Range):
        """Unresolved or strict-import-hidden identifier tokens in *rng*.

        A token is actionable when strict visibility identifies its exact hidden
        owner, or when it is not a known top-level symbol, resolved occurrence,
        local definition, or member-access tail.
        """
        known = self._known_names(result)
        index = self.navigation.build_index(result)
        dmap = self.navigation.definition_map(result)
        strict_missing = {(failure.name, failure.line, failure.col) for failure in result.visibility_failures}
        out = []
        tokens = self.resolver.nav_tokens(result)
        for i, tok in enumerate(tokens):
            if tok.type != TokenKind.IDENT:
                continue
            token_range = self.resolver.result_location(result, tok.line, tok.col, len(tok.value)).range
            if not self._ranges_overlap(token_range, rng):
                continue
            if i >= 1 and tokens[i - 1].value in (".", "->", "?."):
                continue
            requires_import = (tok.value, tok.line, tok.col) in strict_missing
            if not requires_import:
                if tok.value in known:
                    continue
                if (tok.line, tok.col) in index.by_position:
                    continue
                if dmap.find_var_def(tok.value, tok.line, tok.col) is not None:
                    continue
            out.append(tok)
        return out

    def get_code_actions(self, result: DocumentAnalysis, params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
        """Quick-fixes for unresolved identifiers in the requested range."""
        if not result.tokens or not result.ast or not result.is_current():
            return []
        actions: list[lsp.CodeAction] = []
        seen: set[tuple[str, str]] = set()
        module_imports = self._module_imports(result)
        existing = self._existing_imports(result)
        insert_line = self._import_insert_line(result)
        suggest = self._suggestable_names(result)
        failure_owners = {
            (failure.name, failure.line, failure.col): failure.owner_file for failure in result.visibility_failures
        }
        for tok in self._actionable_identifiers(result, params.range):
            name = tok.value
            candidates = module_imports.get(name, [])
            owner = failure_owners.get((name, tok.line, tok.col))
            candidate = next(
                (
                    item
                    for item in candidates
                    if owner is None or os.path.normcase(os.path.realpath(item.owner_file)) == owner
                ),
                None,
            )
            spec = candidate.spec if candidate is not None else None
            if spec is not None and spec not in existing:
                key = ("import", spec)
                if key not in seen:
                    seen.add(key)
                    actions.append(self._import_action(result, name, spec, insert_line))
            suggestion = self._closest(name, suggest)
            if suggestion is not None:
                key = ("rename", name + "->" + suggestion)
                if key not in seen:
                    seen.add(key)
                    actions.append(self._rename_action(result, tok, suggestion))
        return actions

    def _import_action(self, result: DocumentAnalysis, name: str, spec: str, insert_line: int) -> lsp.CodeAction:
        text = f"import {spec};\n"
        edit_range = lsp.Range(
            start=lsp.Position(line=insert_line, character=0), end=lsp.Position(line=insert_line, character=0)
        )
        return lsp.CodeAction(
            title=f"Add import for '{name}' ({spec})",
            kind=lsp.CodeActionKind.QuickFix,
            edit=lsp.WorkspaceEdit(changes={result.uri: [lsp.TextEdit(range=edit_range, new_text=text)]}),
        )

    def _rename_action(self, result: DocumentAnalysis, tok, suggestion: str) -> lsp.CodeAction:
        edit_range = self.resolver.result_location(result, tok.line, tok.col, len(tok.value)).range
        return lsp.CodeAction(
            title=f"Change '{tok.value}' to '{suggestion}'",
            kind=lsp.CodeActionKind.QuickFix,
            edit=lsp.WorkspaceEdit(changes={result.uri: [lsp.TextEdit(range=edit_range, new_text=suggestion)]}),
        )

    def _ranges_overlap(self, left: lsp.Range, right: lsp.Range) -> bool:
        left_start = (left.start.line, left.start.character)
        left_end = (left.end.line, left.end.character)
        right_start = (right.start.line, right.start.character)
        right_end = (right.end.line, right.end.character)
        return left_start < right_end and right_start < left_end
