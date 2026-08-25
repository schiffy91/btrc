"""Definition, reference, rename, occurrence, and highlight navigation."""

from __future__ import annotations

import dataclasses
import os
import re
from dataclasses import dataclass

from lsprotocol import types as lsp

from src.compiler.python.analyzer.program import ClassInfo, Occurrence
from src.compiler.python.frontend.imports import ImportResolver
from src.compiler.python.frontend.packages import ResolvedPackages
from src.compiler.python.syntax.ast.generated import (
    ClassDecl,
    EnumDecl,
    FieldDecl,
    FunctionDecl,
    Identifier,
    ImportDecl,
    InterfaceDecl,
    MethodDecl,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
    TypeExpr,
)
from src.compiler.python.syntax.tokens import Token, TokenKind, TokenVocabulary
from src.devex.lsp.analysis.document import DocumentAnalysis
from src.devex.lsp.analysis.resolution import LexicalScopeIndex, SemanticResolver, VarDef
from src.devex.lsp.workspace.workspace import Workspace


class DefinitionMap:
    """Maps symbol names to their definition locations.

    Entries are file-qualified ``(file, line, col)``; positions are native to
    that file. ``file`` is None for decls without provenance (test snippets).
    Variable definitions are collected from the active document only — line
    ranges are meaningless across files.
    """

    def __init__(self, resolver: SemanticResolver):
        self._resolver = resolver
        self.class_defs: dict[str, tuple[str | None, int, int]] = {}
        self.function_defs: dict[str, tuple[str | None, int, int]] = {}
        self.method_defs: dict[tuple[str, str], tuple[str | None, int, int]] = {}
        self.field_defs: dict[tuple[str, str], tuple[str | None, int, int]] = {}
        self.property_defs: dict[tuple[str, str], tuple[str | None, int, int]] = {}
        self.enum_defs: dict[str, tuple[str | None, int, int]] = {}
        self.struct_defs: dict[str, tuple[str | None, int, int]] = {}
        self.typedef_defs: dict[str, tuple[str | None, int, int]] = {}
        self.var_defs: list[VarDef] = []

    @classmethod
    def from_analysis(cls, result: DocumentAnalysis, resolver: SemanticResolver) -> DefinitionMap:
        """Build (or return the cached) definition map for a snapshot."""
        cached = result._caches.get("dmap")
        if cached is not None:
            return cached
        dmap = cls(resolver)
        if result.ast:
            dmap._build(result)
        result._caches["dmap"] = dmap
        return dmap

    @staticmethod
    def _name_pos(node, file: str | None) -> tuple[str | None, int, int]:
        name_line = getattr(node, "name_line", 0)
        if name_line:
            return (file, name_line, getattr(node, "name_col", 0))
        return (file, getattr(node, "line", 0), getattr(node, "col", 0))

    def _build(self, result: DocumentAnalysis):
        for decl in result.ast.declarations:
            file = getattr(decl, "source_file", None)
            if isinstance(decl, ClassDecl):
                self.class_defs[decl.name] = self._name_pos(decl, file)
                self._collect_class_members(decl, file)
            elif isinstance(decl, InterfaceDecl):
                self.class_defs[decl.name] = self._name_pos(decl, file)
                for sig in decl.methods:
                    self.method_defs[decl.name, sig.name] = self._name_pos(sig, file)
            elif isinstance(decl, FunctionDecl):
                self.function_defs[decl.name] = self._name_pos(decl, file)
            elif isinstance(decl, EnumDecl):
                self.enum_defs[decl.name] = self._name_pos(decl, file)
                for v in decl.values:
                    self.enum_defs.setdefault(v.name, self._name_pos(v, file))
            elif isinstance(decl, RichEnumDecl):
                self.enum_defs[decl.name] = self._name_pos(decl, file)
                for variant in decl.variants:
                    self.enum_defs.setdefault(variant.name, self._name_pos(variant, file))
            elif isinstance(decl, StructDecl):
                if not decl.is_forward or decl.name not in self.struct_defs:
                    self.struct_defs[decl.name] = self._name_pos(decl, file)
            elif isinstance(decl, TypedefDecl):
                self.typedef_defs[decl.alias] = self._name_pos(decl, file)
        self.var_defs.extend(LexicalScopeIndex.from_analysis(result, self._resolver).definitions)

    def _collect_class_members(self, cls: ClassDecl, file: str | None):
        """Collect all member definitions from a class declaration."""
        for member in cls.members:
            if isinstance(member, FieldDecl):
                self.field_defs[cls.name, member.name] = self._name_pos(member, file)
            elif isinstance(member, MethodDecl):
                self.method_defs[cls.name, member.name] = self._name_pos(member, file)
            elif isinstance(member, PropertyDecl):
                self.property_defs[cls.name, member.name] = self._name_pos(member, file)

    def find_var_def(self, name: str, line: int, col: int) -> VarDef | None:
        """Innermost definition of *name* visible at 1-based (line, col).

        A definition is a candidate when the position is inside its scope and
        at/after the definition site; the definition's own name token always
        matches (so params declared before the body's `{` resolve too).
        Innermost = max scope_start, then latest definition line.
        """
        return LexicalScopeIndex.find_visible_var_def(self.var_defs, name, line, col)

    def find_var(self, name: str, cursor_line: int) -> tuple[int, int] | None:
        """Thin wrapper over :meth:`find_var_def` returning (line, col)."""
        vd = self.find_var_def(name, cursor_line, 10**9)
        if vd is not None:
            return (vd.line, vd.col)
        return None


DefSite = tuple


@dataclass
class OccurrenceIndex:
    """Per-snapshot map from identifier position to its resolved occurrence."""

    by_position: dict[tuple[int, int], Occurrence]
    by_def_site: dict[DefSite, list[tuple[int, int]]]
    type_by_position: dict[tuple[int, int], object]
    resolved_by_def_site: dict[DefSite, list[tuple[str | None, int, int]]]
    type_positions: dict[str, list[tuple[str | None, int, int]]]


Ref = tuple
_IDENTIFIER_PATTERN = re.compile("[A-Za-z_][A-Za-z0-9_]*\\Z")
_ASSIGN_OPS = frozenset({"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="})


class NavigationProvider:
    """Definition, reference, rename, occurrence, and highlight navigation."""

    def __init__(self, resolver: SemanticResolver, workspace: Workspace) -> None:
        self.resolver = resolver
        self.workspace = workspace

    def definition_map(self, result: DocumentAnalysis) -> DefinitionMap:
        return DefinitionMap.from_analysis(result, self.resolver)

    def _import_target(self, result: DocumentAnalysis, position: lsp.Position) -> lsp.Location | None:
        """Jump to the file an ``import`` statement's path refers to."""
        if not result.ast or not result.path:
            return None
        target_line = position.line + 1
        for declaration in result.ast.declarations:
            if not (
                isinstance(declaration, ImportDecl)
                and declaration.line == target_line
                and getattr(declaration, "source_file", None) in (None, result.path)
            ):
                continue
            source_dir = os.path.dirname(result.path)
            try:
                candidates = ImportResolver().import_paths(declaration.spec, source_dir, ResolvedPackages.empty())
            except Exception:
                return None
            for candidate in candidates:
                if os.path.isfile(candidate):
                    return self.resolver.result_location(result, 1, 0, 0, file=candidate)
            return None
        return None

    def get_definition(self, result: DocumentAnalysis, position: lsp.Position) -> lsp.Location | None:
        """Return the definition location for the symbol at the given position."""
        if not result.tokens or not result.ast or (not result.is_current_at(position.line)):
            return None
        import_target = self._import_target(result, position)
        if import_target is not None:
            return import_target
        tokens = self.resolver.nav_tokens(result)
        token = self.resolver.find_token_at_position(tokens, position, result.source)
        if token is None or token.type != TokenKind.IDENT:
            return None
        class_table = result.analyzed.class_table if result.analyzed else {}
        dmap = self.definition_map(result)
        occ = self.occurrence_at(result, position)
        if occ is not None and (occ.def_line or occ.def_file):
            if not self._at_def_site(result, token, occ.def_file, occ.def_line, occ.def_col):
                return self.resolver.result_location(
                    result, occ.def_line, occ.def_col, len(token.value), file=occ.def_file
                )
        loc = self._try_member_definition(result, tokens, token, class_table, dmap)
        if loc:
            return loc
        for table in (dmap.class_defs, dmap.function_defs, dmap.enum_defs, dmap.struct_defs, dmap.typedef_defs):
            if token.value in table:
                def_file, def_line, def_col = table[token.value]
                if not self._at_def_site(result, token, def_file, def_line, def_col):
                    return self.resolver.result_location(result, def_line, def_col, len(token.value), file=def_file)
        vd = dmap.find_var_def(token.value, token.line, token.col)
        if vd is not None:
            return self.resolver.result_location(result, vd.line, vd.col, len(token.value))
        return None

    def _at_def_site(
        self, result: DocumentAnalysis, token: Token, def_file: str | None, def_line: int, def_col: int
    ) -> bool:
        """True when the cursor token *is* the definition's name token."""
        if def_file is not None and def_file != result.path:
            return False
        return token.line == def_line and token.col == def_col

    def _try_member_definition(
        self,
        result: DocumentAnalysis,
        tokens: list[Token],
        token: Token,
        class_table: dict[str, ClassInfo],
        dmap: DefinitionMap,
    ) -> lsp.Location | None:
        """Try to resolve a go-to-definition for a member access."""
        if not tokens:
            return None
        token_idx = self.resolver.find_token_index(tokens, token)
        if token_idx is None or token_idx < 2:
            return None
        prev = tokens[token_idx - 1]
        if prev.value not in (".", "->", "?."):
            return None
        member_name = token.value
        target_class = self.resolver.resolve_chain_type(result, tokens, token_idx - 2, class_table)
        if target_class is None:
            return None
        name_len = len(member_name)
        current_class = target_class
        while current_class:
            key = (current_class, member_name)
            for table in (dmap.method_defs, dmap.field_defs, dmap.property_defs):
                if key in table:
                    def_file, def_line, def_col = table[key]
                    return self.resolver.result_location(result, def_line, def_col, name_len, file=def_file)
            cinfo = class_table.get(current_class)
            if cinfo and cinfo.parent and (cinfo.parent in class_table):
                current_class = cinfo.parent
            else:
                break
        return None

    def _occ_def_site(self, occ: Occurrence) -> DefSite:
        return (occ.def_file, occ.def_line, occ.def_col)

    def _collect_nodes(
        self, node, file: str | None, occ_map: dict[int, Occurrence], identifiers: list, type_positions: dict
    ) -> None:
        """Collect resolved identifiers and syntactic type sites from one unit."""
        if node is None:
            return
        if isinstance(node, Identifier):
            occ = occ_map.get(id(node))
            if occ is not None:
                identifiers.append((file, node, occ))
            return
        if isinstance(node, TypeExpr):
            if node.base and node.line and node.col:
                type_positions.setdefault(node.base, []).append((file, node.line, node.col))
            for argument in node.generic_args:
                self._collect_nodes(argument, file, occ_map, identifiers, type_positions)
            self._collect_nodes(node.array_size, file, occ_map, identifiers, type_positions)
            return
        if not dataclasses.is_dataclass(node):
            return
        for f in dataclasses.fields(node):
            child = getattr(node, f.name, None)
            if isinstance(child, (list, tuple)):
                for item in child:
                    if isinstance(item, (list, tuple)):
                        for sub in item:
                            self._collect_nodes(sub, file, occ_map, identifiers, type_positions)
                    else:
                        self._collect_nodes(item, file, occ_map, identifiers, type_positions)
            else:
                self._collect_nodes(child, file, occ_map, identifiers, type_positions)

    def build_index(self, result: DocumentAnalysis) -> OccurrenceIndex:
        """Build (or return the cached) occurrence index for a snapshot."""
        cached = result._caches.get("occ_index")
        if cached is not None:
            return cached
        occ_map: dict[int, Occurrence] = {}
        node_types: dict = {}
        if result.analyzed is not None:
            occ_map = result.analyzed.occurrences or {}
            node_types = result.analyzed.node_types or {}
        by_position: dict[tuple[int, int], Occurrence] = {}
        by_def_site: dict[DefSite, list[tuple[int, int]]] = {}
        type_by_position: dict[tuple[int, int], object] = {}
        resolved_by_def_site: dict[DefSite, list[tuple[str | None, int, int]]] = {}
        type_positions: dict[str, list[tuple[str | None, int, int]]] = {}
        pairs: list = []
        active = self.resolver.active_decls(result)
        lexical_vars = LexicalScopeIndex.collect_lexical_vars(active, result.tokens)
        for decl in active:
            self._collect_nodes(decl, result.path or None, occ_map, pairs, type_positions)
        for unit in result.units:
            if unit.path == result.path:
                continue
            for decl in unit.decls:
                self._collect_nodes(decl, unit.path, occ_map, pairs, type_positions)
        for file, node, occ in pairs:
            if not node.line:
                continue
            pos = (node.line, node.col)
            site = self._occ_def_site(occ)
            lexical_type = None
            if file in (None, result.path):
                var_def = LexicalScopeIndex.find_visible_var_def(lexical_vars, node.name, node.line, node.col)
                if var_def is not None:
                    lexical_site = (result.path or None, var_def.line, var_def.col)
                    if lexical_site != site:
                        occ = Occurrence(
                            kind=var_def.kind,
                            name=node.name,
                            def_file=lexical_site[0],
                            def_line=lexical_site[1],
                            def_col=lexical_site[2],
                        )
                        site = lexical_site
                        lexical_type = getattr(var_def.node, "type", None)
            resolved_by_def_site.setdefault(site, []).append((file, *pos))
            if file in (None, result.path):
                by_position[pos] = occ
                by_def_site.setdefault(site, []).append(pos)
            inferred = lexical_type or node_types.get(id(node))
            if inferred is not None and file in (None, result.path):
                type_by_position[pos] = inferred
        index = OccurrenceIndex(
            by_position=by_position,
            by_def_site=by_def_site,
            type_by_position=type_by_position,
            resolved_by_def_site=resolved_by_def_site,
            type_positions=type_positions,
        )
        result._caches["occ_index"] = index
        return index

    def occurrence_at(self, result: DocumentAnalysis, position: lsp.Position) -> Occurrence | None:
        """The analyzer-resolved occurrence for the identifier at *position*, or None."""
        if result.analyzed is None or not result.tokens:
            return None
        token = self.resolver.find_token_at_position(self.resolver.nav_tokens(result), position, result.source)
        return self.occurrence_for_token(result, token)

    def occurrence_for_token(self, result: DocumentAnalysis, token) -> Occurrence | None:
        """Return an occurrence for an already-resolved active-file token."""
        if token is None or result.analyzed is None:
            return None
        return self.build_index(result).by_position.get((token.line, token.col))

    def type_at(self, result: DocumentAnalysis, position: lsp.Position):
        """The analyzer-inferred TypeExpr for the identifier at *position*, or None.

        Only returns a type for identifiers the analyzer resolved (so it reflects a
        real ``var`` inference rather than a syntactic guess). None otherwise.
        """
        if result.analyzed is None or not result.tokens:
            return None
        index = self.build_index(result)
        if not index.type_by_position:
            return None
        token = self.resolver.find_token_at_position(self.resolver.nav_tokens(result), position, result.source)
        if token is None:
            return None
        return index.type_by_position.get((token.line, token.col))

    def references_to(self, result: DocumentAnalysis, def_site: DefSite) -> list[tuple[int, int]]:
        """Active-document identifier positions resolving to *def_site*.

        Returns 1-based ``(line, col)`` pairs; empty when the def site has no
        recorded uses (the caller then falls back to its heuristic).
        """
        index = self.build_index(result)
        return list(index.by_def_site.get(def_site, []))

    def resolved_references_to(self, result: DocumentAnalysis, def_site: DefSite) -> list[tuple[str | None, int, int]]:
        """File-qualified analyzer-resolved identifiers for one definition site."""
        index = self.build_index(result)
        refs = index.resolved_by_def_site.get(def_site)
        if refs is not None:
            return list(refs)
        if def_site[0] == result.path:
            return list(index.resolved_by_def_site.get((None, *def_site[1:]), []))
        return []

    def _token_streams(self, result: DocumentAnalysis) -> list[tuple[str | None, list[Token], list]]:
        """(file, tokens, decls) per scannable unit; the active document first.

        The active document scans the navigation stream (f-string expressions
        expanded with true positions). ``decls`` provide the scope context for
        chain resolution in that file.
        """
        streams: list[tuple[str | None, list[Token], list]] = [
            (result.path or None, self.resolver.nav_tokens(result), self.resolver.active_decls(result))
        ]
        for unit in result.units:
            if result.path and unit.path == result.path:
                continue
            if unit.tokens:
                streams.append((unit.path, unit.tokens, unit.decls))
        return streams

    def _matching(self, tokens: list[Token], name: str) -> list[tuple[int, Token]]:
        """(index, token) for identifier tokens spelling *name*."""
        return [(i, tok) for i, tok in enumerate(tokens) if tok.type == TokenKind.IDENT and tok.value == name]

    def _is_member_access(self, tokens: list[Token], idx: int) -> bool:
        return idx >= 1 and tokens[idx - 1].value in (".", "->", "?.")

    def _same_site(self, ref: Ref, def_loc: tuple[str | None, int, int] | None) -> bool:
        if def_loc is None:
            return False
        rfile, rline, rcol = ref
        dfile, dline, dcol = def_loc
        return (rline, rcol) == (dline, dcol) and (rfile or None) == (dfile or None)

    def find_name_references(
        self,
        name: str,
        result: DocumentAnalysis,
        def_loc: tuple[str | None, int, int] | None,
        include_declaration: bool,
    ) -> list[Ref]:
        """References to a top-level name (class/enum/struct/typedef) across units."""
        refs = self.resolved_references_to(result, def_loc) if def_loc else []
        refs.extend(self.build_index(result).type_positions.get(name, []))
        refs.extend(self._inheritance_references(name, result))
        constructor = self.definition_map(result).method_defs.get((name, name))
        if constructor is not None:
            refs.append(constructor)
        return self._with_declaration(refs, def_loc, include_declaration)

    def find_function_references(
        self, name: str, result: DocumentAnalysis, dmap: DefinitionMap, include_declaration: bool
    ) -> list[Ref]:
        """References to a function name across all units."""
        def_loc = dmap.function_defs.get(name)
        refs = self.resolved_references_to(result, def_loc) if def_loc else []
        return self._with_declaration(refs, def_loc, include_declaration)

    def _with_declaration(self, refs: list[Ref], definition: Ref | None, include_declaration: bool) -> list[Ref]:
        unique = list(dict.fromkeys(refs))
        if definition is None:
            return unique
        unique = [ref for ref in unique if not self._same_site(ref, definition)]
        return [definition, *unique] if include_declaration else unique

    def _inheritance_references(self, name: str, result: DocumentAnalysis) -> list[Ref]:
        refs: list[Ref] = []
        for file, tokens, _decls in self._token_streams(result):
            for index, token in self._matching(tokens, name):
                if self._in_inheritance_clause(tokens, index):
                    refs.append((file, token.line, token.col))
        return refs

    def _in_inheritance_clause(self, tokens: list[Token], index: int) -> bool:
        for token in reversed(tokens[max(0, index - 32) : index]):
            if token.value in ("extends", "implements"):
                return True
            if token.value in ("{", "}", ";"):
                return False
        return False

    def find_member_references(
        self,
        class_name: str,
        member_name: str,
        kind: str,
        result: DocumentAnalysis,
        class_table: dict[str, ClassInfo],
        dmap: DefinitionMap,
        include_declaration: bool,
    ) -> list[Ref]:
        """References to a class member (method or field) across all units."""
        refs: list[Ref] = []
        if kind == "method":
            def_loc = dmap.method_defs.get((class_name, member_name))
        else:
            def_loc = dmap.field_defs.get((class_name, member_name))
        if include_declaration and def_loc:
            refs.append(def_loc)
        valid_classes = {class_name}
        for cname, cinfo in class_table.items():
            parent = cinfo.parent
            while parent:
                if parent == class_name:
                    valid_classes.add(cname)
                    break
                parent = class_table[parent].parent if parent in class_table else None
        for file, tokens, decls in self._token_streams(result):
            for idx, tok in self._matching(tokens, member_name):
                if idx < 2 or not self._is_member_access(tokens, idx):
                    continue
                ref = (file, tok.line, tok.col)
                if self._same_site(ref, def_loc):
                    continue
                target_class = self.resolver.resolve_chain_type(result, tokens, idx - 2, class_table, decls=decls)
                if target_class in valid_classes:
                    refs.append(ref)
        return refs

    def find_variable_references(
        self, name: str, result: DocumentAnalysis, dmap: DefinitionMap, token: Token, tokens: list[Token]
    ) -> list[Ref]:
        """Scope-aware references to a variable within the active document.

        Primary path: the analyzer's occurrence table. When the cursor resolves to
        a recorded occurrence with a definition site, every identifier whose
        occurrence shares that def site is an exact, scope-correct reference. The
        definition's own name token (which is not an identifier node) is added so
        the declaration is part of the result.

        Fallback (no occurrence — e.g. the analyzer never resolved this node):
        the cursor token anchors a ``VarDef`` and a candidate counts only when it
        resolves to that same definition. Unresolvable cursor yields just itself.
        """
        here = result.path or None
        occ = self.occurrence_for_token(result, token)
        if occ is not None and (occ.def_line or occ.def_file):
            def_site = (occ.def_file, occ.def_line, occ.def_col)
            positions = self.references_to(result, def_site)
            refs: list[Ref] = [(here, line, col) for line, col in positions]
            if occ.def_file in (None, result.path):
                decl_ref = (here, occ.def_line, occ.def_col)
                if decl_ref not in refs:
                    refs.append(decl_ref)
            return refs
        anchor = dmap.find_var_def(name, token.line, token.col)
        if anchor is None:
            return [(here, token.line, token.col)]
        refs = []
        for idx, tok in self._matching(tokens, name):
            if self._is_member_access(tokens, idx):
                continue
            if dmap.find_var_def(name, tok.line, tok.col) is anchor:
                refs.append((here, tok.line, tok.col))
        return refs

    def _classify_symbol(
        self,
        token: Token,
        tokens: list[Token],
        result: DocumentAnalysis,
        class_table: dict[str, ClassInfo],
        dmap: DefinitionMap,
    ) -> tuple[str, str | None, str | None]:
        """Classify the symbol under cursor.

        Returns (kind, class_name, member_name) where kind is one of:
        'class', 'enum', 'struct', 'typedef', 'function', 'method', 'field',
        'variable'.
        """
        name = token.value
        token_idx = self.resolver.find_token_index(tokens, token)
        if token_idx is not None and token_idx >= 2:
            prev = tokens[token_idx - 1]
            if prev.value in (".", "->", "?."):
                target_class = self.resolver.resolve_chain_type(result, tokens, token_idx - 2, class_table)
                if target_class:
                    cinfo = class_table.get(target_class)
                    if cinfo:
                        if name in cinfo.methods:
                            return ("method", target_class, name)
                        if name in cinfo.fields:
                            return ("field", target_class, name)
                        parent = cinfo.parent
                        while parent and parent in class_table:
                            pc = class_table[parent]
                            if name in pc.methods:
                                return ("method", parent, name)
                            if name in pc.fields:
                                return ("field", parent, name)
                            parent = pc.parent
        here = (result.path or None, token.line, token.col)
        for (cls, mem), (dfile, dline, dcol) in dmap.method_defs.items():
            if mem == name and (dfile or None, dline, dcol) == here:
                return ("method", cls, name)
        for (cls, mem), (dfile, dline, dcol) in dmap.field_defs.items():
            if mem == name and (dfile or None, dline, dcol) == here:
                return ("field", cls, name)
        if name in dmap.class_defs:
            return ("class", name, None)
        if name in dmap.function_defs:
            return ("function", None, name)
        if name in dmap.enum_defs:
            return ("enum", None, name)
        if name in dmap.struct_defs:
            return ("struct", None, name)
        if name in dmap.typedef_defs:
            return ("typedef", None, name)
        return ("variable", None, name)

    def _definition_entry(
        self, kind: str, class_name: str | None, name: str, dmap: DefinitionMap
    ) -> tuple[str | None, int, int] | None:
        """The (file, line, col) definition entry for a classified symbol."""
        if kind == "class":
            return dmap.class_defs.get(name)
        if kind == "enum":
            return dmap.enum_defs.get(name)
        if kind == "struct":
            return dmap.struct_defs.get(name)
        if kind == "typedef":
            return dmap.typedef_defs.get(name)
        if kind == "function":
            return dmap.function_defs.get(name)
        if kind == "method" and class_name:
            return dmap.method_defs.get((class_name, name))
        if kind == "field" and class_name:
            return dmap.field_defs.get((class_name, name))
        return None

    def _is_stdlib_file(self, path: str | None) -> bool:
        """True when *path* lives under the installed stdlib directory."""
        if not path:
            return False
        stdlib_dir = os.path.abspath(self.workspace.stdlib_directory())
        return os.path.abspath(path).startswith(stdlib_dir + os.sep)

    def _locate_symbol(self, result: DocumentAnalysis, position: lsp.Position):
        """Resolve and classify the identifier at *position*, or None."""
        if not result.tokens or not result.ast:
            return None
        tokens = self.resolver.nav_tokens(result)
        token = self.resolver.find_token_at_position(tokens, position, result.source)
        if token is None or token.type != TokenKind.IDENT:
            return None
        class_table = result.analyzed.class_table if result.analyzed else {}
        dmap = self.definition_map(result)
        kind, class_name, member_name = self._classify_symbol(token, tokens, result, class_table, dmap)
        return (token, tokens, class_table, dmap, kind, class_name, member_name)

    def get_references(
        self, result: DocumentAnalysis, position: lsp.Position, include_declaration: bool = True
    ) -> list[lsp.Location]:
        """Return all reference locations for the symbol at position."""
        if not result.is_current():
            return []
        sym = self._locate_symbol(result, position)
        if sym is None:
            return []
        token, tokens, class_table, dmap, kind, class_name, member_name = sym
        name = token.value
        if kind in ("class", "enum", "struct", "typedef"):
            refs = self.find_name_references(
                name, result, self._definition_entry(kind, class_name, name, dmap), include_declaration
            )
        elif kind == "function":
            refs = self.find_function_references(name, result, dmap, include_declaration)
        elif kind in ("method", "field"):
            refs = self.find_member_references(
                class_name, member_name, kind, result, class_table, dmap, include_declaration
            )
        else:
            refs = self.find_variable_references(name, result, dmap, token, tokens)
        return [self.resolver.result_location(result, line, col, len(name), file=file) for file, line, col in refs]

    def _rename_blocked(self, result: DocumentAnalysis, position: lsp.Position) -> bool:
        """True when rename at *position* must be refused.

        Refusals: unresolvable variables (no visible definition to anchor a
        scope-correct rename) and symbols whose definition lives in the stdlib
        (rename would edit installed stdlib files on disk).
        """
        sym = self._locate_symbol(result, position)
        if sym is None:
            return True
        token, _tokens, _class_table, dmap, kind, class_name, _member_name = sym
        if kind == "variable":
            return dmap.find_var_def(token.value, token.line, token.col) is None
        entry = self._definition_entry(kind, class_name, token.value, dmap)
        return self._is_stdlib_file(entry[0] if entry else None)

    def get_rename_edits(
        self, result: DocumentAnalysis, position: lsp.Position, new_name: str
    ) -> lsp.WorkspaceEdit | None:
        """Return workspace edits to rename the symbol at position."""
        if (
            not result.tokens
            or not result.ast
            or (not result.is_current())
            or (not self._valid_rename_identifier(new_name))
        ):
            return None
        token = self.resolver.find_token_at_position(self.resolver.nav_tokens(result), position, result.source)
        if token is None or token.type != TokenKind.IDENT:
            return None
        if self._rename_blocked(result, position):
            return None
        locations = self.get_references(result, position, include_declaration=True)
        if not locations:
            return None
        changes: dict[str, list[lsp.TextEdit]] = {}
        for loc in locations:
            edit_range = loc.range
            changes.setdefault(loc.uri, []).append(lsp.TextEdit(range=edit_range, new_text=new_name))
        return lsp.WorkspaceEdit(changes=changes)

    def _valid_rename_identifier(self, name: str) -> bool:
        """Apply the grammar's ASCII identifier shape and keyword reservation."""
        return (
            isinstance(name, str)
            and bool(_IDENTIFIER_PATTERN.fullmatch(name))
            and (name not in TokenVocabulary.canonical().keywords)
        )

    def prepare_rename(self, result: DocumentAnalysis, position: lsp.Position) -> lsp.Range | None:
        """Check if rename is possible at position and return the symbol range."""
        if not result.tokens or not result.is_current():
            return None
        tokens = self.resolver.nav_tokens(result) if result.ast else result.tokens
        token = self.resolver.find_token_at_position(tokens, position, result.source)
        if token is None or token.type != TokenKind.IDENT:
            return None
        if result.ast and self._rename_blocked(result, position):
            return None
        return self.resolver.result_location(result, token.line, token.col, len(token.value)).range

    def _write_positions(self, tokens, name: str) -> set[tuple[int, int]]:
        """1-based (line, col) of *name* tokens that are assignment targets.

        A bare identifier immediately followed by an assignment operator (and not
        itself a member access tail like ``obj.x`` — that still counts as a write of
        ``x``) is treated as a write. ``==`` is excluded by the operator set.
        """
        writes: set[tuple[int, int]] = set()
        for i, tok in enumerate(tokens):
            if tok.type != TokenKind.IDENT or tok.value != name:
                continue
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if nxt is not None and nxt.value in _ASSIGN_OPS:
                writes.add((tok.line, tok.col))
        return writes

    def get_document_highlights(self, result: DocumentAnalysis, position: lsp.Position) -> list[lsp.DocumentHighlight]:
        """All in-scope occurrences of the symbol at *position*, active file only."""
        if not result.is_current():
            return []
        sym = self._locate_symbol(result, position)
        if sym is None:
            return []
        token, tokens, class_table, dmap, kind, class_name, member_name = sym
        name = token.value
        if kind in ("class", "enum", "struct", "typedef"):
            refs = self.find_name_references(name, result, self._definition_entry(kind, class_name, name, dmap), True)
        elif kind == "function":
            refs = self.find_function_references(name, result, dmap, True)
        elif kind in ("method", "field"):
            refs = self.find_member_references(class_name, member_name, kind, result, class_table, dmap, True)
        else:
            refs = self.find_variable_references(name, result, dmap, token, tokens)
        here = result.path or None
        writes = self._write_positions(self.resolver.nav_tokens(result), name)
        highlights: list[lsp.DocumentHighlight] = []
        seen: set[tuple[int, int]] = set()
        for file, line, col in refs:
            if (file or None) != here:
                continue
            if (line, col) in seen:
                continue
            seen.add((line, col))
            hl_kind = lsp.DocumentHighlightKind.Write if (line, col) in writes else lsp.DocumentHighlightKind.Read
            location = self.resolver.result_location(result, line, col, len(name), file=file)
            highlights.append(lsp.DocumentHighlight(range=location.range, kind=hl_kind))
        return highlights
