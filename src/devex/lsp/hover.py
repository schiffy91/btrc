"""Hover provider for btrc.

Shows type information when hovering over identifiers, keywords,
class names, and method calls.
"""


from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import (
    CallExpr,
    FieldDecl,
    Identifier,
    MethodDecl,
    NewExpr,
    VarDeclStmt,
)
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.builtins import _MEMBER_TABLES, get_hover_markdown
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.utils import (
    find_token_at_position,
    find_token_index,
    nav_tokens,
    resolve_chain_type,
    type_repr,
)


def _format_class_info(
    name: str,
    info: ClassInfo,
    class_table: dict[str, ClassInfo],
) -> str:
    """Format hover content for a class."""
    lines = [f"```btrc\nclass {name}"]
    if info.generic_params:
        lines[0] += f"<{', '.join(info.generic_params)}>"
    if info.parent:
        lines[0] += f" extends {info.parent}"
    lines[0] += "\n```"

    if info.fields:
        lines.append("\n**Fields:**")
        for fname, fdecl in info.fields.items():
            access = fdecl.access if isinstance(fdecl, FieldDecl) else "public"
            ftype = type_repr(fdecl.type, class_table) if isinstance(fdecl, FieldDecl) else "?"
            lines.append(f"- `{access} {ftype} {fname}`")

    if info.methods:
        lines.append("\n**Methods:**")
        for mname, mdecl in info.methods.items():
            if isinstance(mdecl, MethodDecl):
                params = ", ".join(
                    f"{type_repr(p.type, class_table)} {p.name}" for p in mdecl.params
                )
                ret = type_repr(mdecl.return_type, class_table)
                access = mdecl.access
                lines.append(f"- `{access} {ret} {mname}({params})`")

    if info.constructor and isinstance(info.constructor, MethodDecl):
        params = ", ".join(
            f"{type_repr(p.type, class_table)} {p.name}" for p in info.constructor.params
        )
        lines.append(f"\n**Constructor:** `{name}({params})`")

    return "\n".join(lines)


def _format_method_info(
    class_name: str,
    method_name: str,
    mdecl: MethodDecl,
    class_table: dict[str, ClassInfo],
) -> str:
    """Format hover content for a method."""
    params = ", ".join(f"{type_repr(p.type, class_table)} {p.name}" for p in mdecl.params)
    ret = type_repr(mdecl.return_type, class_table)
    access = mdecl.access
    static = " (static)" if access == "class" else ""
    return f"```btrc\n{access} {ret} {method_name}({params})\n```\nMethod of `{class_name}`{static}"


def _format_field_info(
    class_name: str,
    field_name: str,
    fdecl: FieldDecl,
    class_table: dict[str, ClassInfo],
) -> str:
    """Format hover content for a field."""
    ftype = type_repr(fdecl.type, class_table)
    return f"```btrc\n{fdecl.access} {ftype} {field_name}\n```\nField of `{class_name}`"


# Keywords with brief descriptions
_KEYWORD_DOCS = {
    "class": "Declares a class with fields and methods.",
    "extends": "Specifies parent class for inheritance.",
    "public": "Access modifier: visible outside the class.",
    "private": "Access modifier: only visible within the class.",
    "var": "Declares a variable with type inference.",
    "new": "Allocates an object on the heap.",
    "delete": "Frees a heap-allocated object.",
    "self": "Reference to the current object instance.",
    "for": "Loop construct. Use `for x in range(n)` or `for x in collection`.",
    "in": "Used in for-in loops: `for x in iterable`.",
    "try": "Begins a try/catch error handling block.",
    "catch": "Catches an error thrown in a try block.",
    "throw": "Throws an error (string value).",
    "null": "Null value for nullable types.",
    "parallel": "Marks a for loop for parallel execution.",
    "sizeof": "Returns the size of a type or expression in bytes.",
    "bool": "Boolean type: `true` or `false`.",
    "keep": "Marks a parameter as stored (refcount incremented at call site) "
            "or a return type as transferring ownership to the caller.",
    "release": "Decrements the reference count. If the count reaches zero, "
               "the object is destroyed and memory is freed. Sets the variable to NULL.",
}

for _tn, _members in _MEMBER_TABLES.items():
    if _tn in _KEYWORD_DOCS:
        continue
    _methods = [m.name for m in _members if m.kind == "method"]
    _fields = [m.name for m in _members if m.kind == "field"]
    _parts = []
    if _fields:
        _parts.append("Fields: " + ", ".join(_fields))
    if _methods:
        _preview = _methods[:6]
        _suffix = ", ..." if len(_methods) > 6 else ""
        _parts.append("Methods: " + ", ".join(f"{m}()" for m in _preview) + _suffix)
    _KEYWORD_DOCS[_tn] = f"Built-in type `{_tn}`. " + ". ".join(_parts) + "."
del _tn, _members, _methods, _fields, _parts, _preview, _suffix


def get_hover_info(
    result: AnalysisResult, position: lsp.Position
) -> lsp.Hover | None:
    """Return hover information for the token at the given position."""
    if not result.tokens:
        return None

    tokens = nav_tokens(result)
    token = find_token_at_position(tokens, position)
    if token is None:
        return None

    content: str | None = None
    class_table = result.analyzed.class_table if result.analyzed else {}

    if token.value in class_table:
        content = _format_class_info(token.value, class_table[token.value], class_table)

    elif token.value in _KEYWORD_DOCS:
        content = f"**`{token.value}`** — {_KEYWORD_DOCS[token.value]}"

    elif token.type == TokenType.IDENT:
        content = _try_member_hover(result, tokens, token, class_table)
        if content is None:
            content = _try_variable_hover(result, token, class_table, position)

    if content is None:
        return None

    return lsp.Hover(
        contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=content,
        ),
    )


def _try_member_hover(
    result: AnalysisResult,
    tokens: list[Token],
    token: Token,
    class_table: dict[str, ClassInfo],
) -> str | None:
    """Try to resolve hover for a member access (obj.field or obj.method)."""
    if not tokens:
        return None

    token_idx = find_token_index(tokens, token)
    if token_idx is None or token_idx < 2:
        return None

    prev = tokens[token_idx - 1]
    if prev.value not in (".", "->", "?."):
        return None

    member_name = token.value

    target_type = resolve_chain_type(result, tokens, token_idx - 2, class_table)
    if target_type is None:
        return None

    # Check built-in type members first
    builtin_doc = get_hover_markdown(target_type, member_name)
    if builtin_doc:
        return f"{builtin_doc}\nBuilt-in member of `{target_type}`"

    # Look up the member in the target class and its parent chain
    cname = target_type
    while cname and cname in class_table:
        cinfo = class_table[cname]
        if member_name in cinfo.methods:
            mdecl = cinfo.methods[member_name]
            if isinstance(mdecl, MethodDecl):
                return _format_method_info(cname, member_name, mdecl, class_table)
        if member_name in cinfo.fields:
            fdecl = cinfo.fields[member_name]
            if isinstance(fdecl, FieldDecl):
                return _format_field_info(cname, member_name, fdecl, class_table)
        cname = cinfo.parent

    return None


# ---------------------------------------------------------------------------
# Variable / parameter hover (scope-aware, via the DefinitionMap)
# ---------------------------------------------------------------------------


def _try_variable_hover(
    result: AnalysisResult,
    token: Token,
    class_table: dict[str, ClassInfo],
    position: lsp.Position | None = None,
) -> str | None:
    """Hover for the innermost variable definition visible at the cursor.

    Scope resolution is shared with go-to-definition/references via
    DefinitionMap.find_var_def — block ends are real closing-brace lines, so
    a variable never hovers outside its function or after its block ends.

    The displayed type prefers the analyzer-inferred type for this exact
    identifier (so a ``var`` shows its real inferred type, e.g. ``Vector<int>``)
    and falls back to the syntactic guess when the analyzer recorded nothing.
    """
    if not result.ast:
        return None

    from src.devex.lsp.definition import DefinitionMap
    from src.devex.lsp.occurrences import type_at

    dmap = DefinitionMap.from_result(result)
    vd = dmap.find_var_def(token.value, token.line, token.col)
    if vd is None:
        return None

    inferred = type_at(result, position) if position is not None else None

    name = vd.name
    if vd.kind == "param":
        type_str = (
            type_repr(inferred, class_table)
            if inferred is not None
            else type_repr(getattr(vd.node, "type", None), class_table)
        )
        return f"```btrc\n{type_str} {name}\n```\nParameter of `{vd.owner}`"
    if vd.kind in ("local", "cfor") and isinstance(vd.node, VarDeclStmt):
        type_str = (
            type_repr(inferred, class_table)
            if inferred is not None
            else _infer_var_type(vd.node, class_table)
        )
        ctx = "Local variable" if vd.kind == "local" else "Loop variable"
        return f"```btrc\n{type_str} {name}\n```\n{ctx}"
    if vd.kind == "loop":
        return f"```btrc\nvar {name}\n```\nLoop variable"
    if vd.kind == "loop_key":
        return f"```btrc\nvar {name}\n```\nLoop variable (key)"
    if vd.kind == "parallel":
        return f"```btrc\nvar {name}\n```\nParallel loop variable"
    if vd.kind == "catch":
        return f"```btrc\nstring {name}\n```\nCatch variable"
    return None


def _infer_var_type(stmt: VarDeclStmt, class_table: dict[str, ClassInfo]) -> str:
    """Infer a type string for a VarDeclStmt."""
    if stmt.type:
        return type_repr(stmt.type, class_table)
    if isinstance(stmt.initializer, CallExpr):
        callee = stmt.initializer.callee
        if isinstance(callee, Identifier):
            return callee.name
    if isinstance(stmt.initializer, NewExpr):
        if stmt.initializer.type:
            return type_repr(stmt.initializer.type, class_table)
    return "var"
