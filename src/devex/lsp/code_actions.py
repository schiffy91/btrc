"""textDocument/codeAction provider for btrc.

Two best-effort quick-fixes for an identifier that does not resolve:

  (a) Add import — when the name is defined by some workspace/stdlib unit that
      the active file does not currently pull in, insert the matching
      ``import std.<module>;`` (or ``import "<relpath>";``) line at the top of
      the file.
  (b) Did you mean — when the name is within a small edit distance of a known
      class/function/enum/struct/typedef name, offer a text edit that changes
      the identifier to that name.

Both fire only when confident: the import action needs an exact name->module
hit, and the spelling action needs a unique close match. Identifiers that
already resolve are never touched. The provider scans the identifiers that fall
inside the request range, so it answers the editor's lightbulb in-place.
"""

from __future__ import annotations

import os

from lsprotocol import types as lsp

from src.compiler.python import pkg
from src.compiler.python.frontend import _get_stdlib_dir
from src.compiler.python.tokens import TokenType
from src.devex.lsp.definition import DefinitionMap
from src.devex.lsp.diagnostics import AnalysisResult, analysis_is_current
from src.devex.lsp.occurrences import build_index
from src.devex.lsp.package_resolution import shares_project_manifest
from src.devex.lsp.utils import (
    BUILTIN_TYPES,
    active_decls,
    nav_tokens,
    result_location,
)

# Maximum Levenshtein distance for a "did you mean" suggestion.
_MAX_EDIT_DISTANCE = 2


def _known_names(result: AnalysisResult) -> set[str]:
    """Every top-level symbol name visible to the analyzer (composed program)."""
    names: set[str] = set(BUILTIN_TYPES)
    a = result.analyzed
    if a is not None:
        names |= set(a.class_table)
        names |= set(a.function_table)
        names |= set(a.enum_table)
        names |= set(a.rich_enum_table)
        names |= set(a.interface_table)
    dmap = DefinitionMap.from_result(result)
    names |= set(dmap.struct_defs)
    names |= set(dmap.typedef_defs)
    names |= set(dmap.enum_defs)
    return names


def _suggestable_names(result: AnalysisResult) -> list[str]:
    """Named decls that a typo could be corrected *to* (no builtins/keywords)."""
    a = result.analyzed
    names: set[str] = set()
    if a is not None:
        names |= set(a.class_table)
        names |= set(a.function_table)
        names |= set(a.enum_table)
        names |= set(a.rich_enum_table)
        names |= set(a.interface_table)
    dmap = DefinitionMap.from_result(result)
    names |= set(dmap.struct_defs)
    names |= set(dmap.typedef_defs)
    return [n for n in names if n]


def _levenshtein(a: str, b: str, cap: int) -> int:
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


# Minimum identifier length for a did-you-mean: too short and an edit-distance-2
# match is meaningless noise (``w`` -> ``Ui``).
_MIN_SUGGEST_LEN = 3


def _closest(name: str, candidates: list[str]) -> str | None:
    """The single closest candidate within ``_MAX_EDIT_DISTANCE``, if unique."""
    if len(name) < _MIN_SUGGEST_LEN:
        return None
    best: str | None = None
    best_d = _MAX_EDIT_DISTANCE + 1
    tie = False
    for cand in candidates:
        if cand == name:
            return None  # already exact: nothing to fix
        d = _levenshtein(name.lower(), cand.lower(), _MAX_EDIT_DISTANCE)
        if d < best_d:
            best_d, best, tie = d, cand, False
        elif d == best_d:
            tie = True
    if best is None or best_d > _MAX_EDIT_DISTANCE or tie:
        return None
    return best


def _module_imports(result: AnalysisResult):
    """Build {name -> import-spec-string} from workspace + stdlib units.

    The active file's own decls are excluded. A stdlib unit maps to
    ``std.<module>``; a workspace file maps to a relative ``"path"`` import.
    """
    from src.devex.lsp.diagnostics import WORKSPACE

    stdlib_dir = os.path.abspath(_get_stdlib_dir())
    active = os.path.abspath(result.path) if result.path else None
    active_dir = os.path.dirname(active) if active else None
    manifest = pkg.find_manifest(active_dir) if active_dir else None
    project_root = os.path.dirname(manifest) if manifest else active_dir
    by_name: dict[str, str] = {}

    def consider(path: str, defined: frozenset):
        ap = os.path.abspath(path)
        if ap == active:
            return
        spec = _import_spec_for(ap, stdlib_dir, active)
        if spec is None:
            return
        for name in defined:
            by_name.setdefault(name, spec)

    for unit in WORKSPACE.stdlib_units():
        consider(unit.path, unit.defined_names)
    for unit in WORKSPACE.cached_units(project_root):
        if shares_project_manifest(unit.path, manifest):
            consider(unit.path, unit.defined_names)
    return by_name


def _import_spec_for(path: str, stdlib_dir: str, active: str | None) -> str | None:
    if path.startswith(stdlib_dir + os.sep):
        module = os.path.splitext(os.path.basename(path))[0]
        return f"std.{module}"
    if active is None:
        return None
    rel = os.path.relpath(path, os.path.dirname(active))
    return f'"{rel}"'


def _existing_imports(result: AnalysisResult) -> set[str]:
    """Import-spec strings already present in the active file."""
    from src.compiler.python.ast_nodes import (
        ImportDecl,
        PackagePath,
        QuotedPath,
        RelativePath,
        StdModules,
    )

    out: set[str] = set()
    for decl in active_decls(result):
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


def _import_insert_line(result: AnalysisResult) -> int:
    """0-based line to insert a new import: after the last existing import."""
    from src.compiler.python.ast_nodes import ImportDecl

    last = 0
    for decl in active_decls(result):
        if isinstance(decl, ImportDecl) and decl.line:
            last = max(last, decl.line)
    return last  # decl.line is 1-based; inserting at this 0-based index is the next line


def _unresolved_identifiers(result: AnalysisResult, rng: lsp.Range):
    """Identifier tokens in *rng* that the analyzer did not resolve.

    A token is unresolved when it is not a known top-level symbol, not a
    resolved occurrence (local/param/etc.), and not the tail of a member
    access (``obj.field`` fields are not top-level names).
    """
    known = _known_names(result)
    index = build_index(result)
    dmap = DefinitionMap.from_result(result)
    out = []
    tokens = nav_tokens(result)
    for i, tok in enumerate(tokens):
        if tok.type != TokenType.IDENT:
            continue
        token_range = result_location(
            result,
            tok.line,
            tok.col,
            len(tok.value),
        ).range
        if not _ranges_overlap(token_range, rng):
            continue
        if i >= 1 and tokens[i - 1].value in (".", "->", "?."):
            continue  # member access tail: not a free name
        if tok.value in known:
            continue
        if (tok.line, tok.col) in index.by_position:
            continue  # resolved local/param/function by the analyzer
        if dmap.find_var_def(tok.value, tok.line, tok.col) is not None:
            continue  # a visible local/param/loop var (decl site or use)
        out.append(tok)
    return out


def get_code_actions(result: AnalysisResult, params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    """Quick-fixes for unresolved identifiers in the requested range."""
    if not result.tokens or not result.ast or not analysis_is_current(result):
        return []

    actions: list[lsp.CodeAction] = []
    seen: set[tuple[str, str]] = set()  # (title, target name) — dedupe per name

    module_imports = _module_imports(result)
    existing = _existing_imports(result)
    insert_line = _import_insert_line(result)
    suggest = _suggestable_names(result)

    for tok in _unresolved_identifiers(result, params.range):
        name = tok.value

        spec = module_imports.get(name)
        if spec is not None and spec not in existing:
            key = ("import", spec)
            if key not in seen:
                seen.add(key)
                actions.append(_import_action(result, name, spec, insert_line))

        suggestion = _closest(name, suggest)
        if suggestion is not None:
            key = ("rename", name + "->" + suggestion)
            if key not in seen:
                seen.add(key)
                actions.append(_rename_action(result, tok, suggestion))

    return actions


def _import_action(result: AnalysisResult, name: str, spec: str, insert_line: int) -> lsp.CodeAction:
    text = f"import {spec};\n"
    edit_range = lsp.Range(
        start=lsp.Position(line=insert_line, character=0),
        end=lsp.Position(line=insert_line, character=0),
    )
    return lsp.CodeAction(
        title=f"Add import for '{name}' ({spec})",
        kind=lsp.CodeActionKind.QuickFix,
        edit=lsp.WorkspaceEdit(changes={result.uri: [lsp.TextEdit(range=edit_range, new_text=text)]}),
    )


def _rename_action(result: AnalysisResult, tok, suggestion: str) -> lsp.CodeAction:
    edit_range = result_location(
        result,
        tok.line,
        tok.col,
        len(tok.value),
    ).range
    return lsp.CodeAction(
        title=f"Change '{tok.value}' to '{suggestion}'",
        kind=lsp.CodeActionKind.QuickFix,
        edit=lsp.WorkspaceEdit(changes={result.uri: [lsp.TextEdit(range=edit_range, new_text=suggestion)]}),
    )


def _ranges_overlap(left: lsp.Range, right: lsp.Range) -> bool:
    left_start = (left.start.line, left.start.character)
    left_end = (left.end.line, left.end.character)
    right_start = (right.start.line, right.start.character)
    right_end = (right.end.line, right.end.character)
    return left_start < right_end and right_start < left_end
