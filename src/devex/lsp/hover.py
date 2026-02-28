"""Hover provider for btrc.

Shows type information when hovering over identifiers, keywords,
class names, and method calls.
"""

from typing import Optional

from lsprotocol import types as lsp

from src.compiler.python.tokens import Token, TokenType
from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import (
    Block,
    ClassDecl,
    ElseBlock,
    ElseIf,
    FieldDecl,
    ForInitVar,
    FunctionDecl,
    MethodDecl,
    VarDeclStmt,
    ForInStmt,
    CForStmt,
    ParallelForStmt,
    TryCatchStmt,
    IfStmt,
    WhileStmt,
    DoWhileStmt,
    SwitchStmt,
    CaseClause,
    CallExpr,
    Identifier,
    NewExpr,
)

from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.builtins import get_hover_markdown, _MEMBER_TABLES
from src.devex.lsp.utils import (
    type_repr,
    find_token_at_position,
    find_token_index,
    body_range,
    resolve_chain_type,
)


def _format_class_info(name: str, info: ClassInfo) -> str:
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
            ftype = type_repr(fdecl.type) if isinstance(fdecl, FieldDecl) else "?"
            lines.append(f"- `{access} {ftype} {fname}`")

    if info.methods:
        lines.append("\n**Methods:**")
        for mname, mdecl in info.methods.items():
            if isinstance(mdecl, MethodDecl):
                params = ", ".join(
                    f"{type_repr(p.type)} {p.name}" for p in mdecl.params
                )
                ret = type_repr(mdecl.return_type)
                access = mdecl.access
                lines.append(f"- `{access} {ret} {mname}({params})`")

    if info.constructor and isinstance(info.constructor, MethodDecl):
        params = ", ".join(
            f"{type_repr(p.type)} {p.name}" for p in info.constructor.params
        )
        lines.append(f"\n**Constructor:** `{name}({params})`")

    return "\n".join(lines)


def _format_method_info(class_name: str, method_name: str, mdecl: MethodDecl) -> str:
    """Format hover content for a method."""
    params = ", ".join(f"{type_repr(p.type)} {p.name}" for p in mdecl.params)
    ret = type_repr(mdecl.return_type)
    access = mdecl.access
    static = " (static)" if access == "class" else ""
    return f"```btrc\n{access} {ret} {method_name}({params})\n```\nMethod of `{class_name}`{static}"


def _format_field_info(class_name: str, field_name: str, fdecl: FieldDecl) -> str:
    """Format hover content for a field."""
    ftype = type_repr(fdecl.type)
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

# Auto-generate hover docs for types in _MEMBER_TABLES
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
) -> Optional[lsp.Hover]:
    """Return hover information for the token at the given position."""
    if not result.tokens:
        return None

    token = find_token_at_position(result.tokens, position)
    if token is None:
        return None

    content: Optional[str] = None
    class_table = result.analyzed.class_table if result.analyzed else {}

    # Check if it's a class name
    if token.value in class_table:
        content = _format_class_info(token.value, class_table[token.value])

    # Check if it's a keyword/type with documentation
    elif token.value in _KEYWORD_DOCS:
        content = f"**`{token.value}`** — {_KEYWORD_DOCS[token.value]}"

    # Check if it's a method or field being accessed (look at preceding tokens)
    elif token.type == TokenType.IDENT:
        content = _try_member_hover(result, token, class_table)
        if content is None:
            content = _try_variable_hover(result, token, class_table)

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
    token: Token,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Try to resolve hover for a member access (obj.field or obj.method)."""
    if not result.tokens:
        return None

    token_idx = find_token_index(result.tokens, token)
    if token_idx is None or token_idx < 2:
        return None

    prev = result.tokens[token_idx - 1]
    if prev.value not in (".", "->", "?."):
        return None

    member_name = token.value

    target_type = resolve_chain_type(result, result.tokens, token_idx - 2, class_table)

    if target_type is None:
        for cname, cinfo in class_table.items():
            if member_name in cinfo.methods or member_name in cinfo.fields:
                target_type = cname
                break

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
                return _format_method_info(cname, member_name, mdecl)
        if member_name in cinfo.fields:
            fdecl = cinfo.fields[member_name]
            if isinstance(fdecl, FieldDecl):
                return _format_field_info(cname, member_name, fdecl)
        cname = cinfo.parent

    return None


# ---------------------------------------------------------------------------
# Variable / parameter hover
# ---------------------------------------------------------------------------


def _try_variable_hover(
    result: AnalysisResult,
    token: Token,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Try to resolve hover for a local variable, parameter, or loop variable."""
    if not result.ast:
        return None

    name = token.value
    cursor_line = token.line  # 1-based

    for decl in result.ast.declarations:
        info = _find_var_hover_in_decl(name, cursor_line, decl, class_table)
        if info:
            return info
    return None


def _member_scope_end(decl: ClassDecl, member_idx: int) -> int:
    """Compute the scope end for a class member."""
    members = decl.members
    for i in range(member_idx + 1, len(members)):
        next_line = getattr(members[i], "line", 0)
        if next_line > 0:
            return next_line - 1
    return getattr(members[member_idx], "line", 0) + 500


def _find_var_hover_in_decl(
    name: str,
    cursor_line: int,
    decl,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Search a top-level declaration for a variable/param matching *name*."""
    if isinstance(decl, ClassDecl):
        for i, member in enumerate(decl.members):
            if isinstance(member, MethodDecl):
                scope_end = _member_scope_end(decl, i)
                info = _check_callable(
                    name, cursor_line, member, decl.name, class_table, scope_end
                )
                if info:
                    return info
    elif isinstance(decl, FunctionDecl):
        return _check_callable(name, cursor_line, decl, None, class_table)
    return None


def _check_callable(
    name: str,
    cursor_line: int,
    node,
    class_name: Optional[str],
    class_table: dict[str, ClassInfo],
    scope_end_override: Optional[int] = None,
) -> Optional[str]:
    """Check parameters and body of a function/method for *name*."""
    if not isinstance(node, (FunctionDecl, MethodDecl)):
        return None

    scope_start = node.line
    if scope_end_override is not None:
        scope_end = scope_end_override
    else:
        _, scope_end = body_range(node.body, node.line)

    if not (scope_start <= cursor_line <= scope_end):
        return None

    for p in node.params:
        if p.name == name:
            type_str = type_repr(p.type)
            ctx = (
                f"Parameter of `{class_name}.{node.name}`"
                if class_name
                else f"Parameter of `{node.name}`"
            )
            return f"```btrc\n{type_str} {name}\n```\n{ctx}"

    if node.body:
        return _scan_block_for_var(
            name, cursor_line, node.body, class_name, node.name, class_table
        )
    return None


def _scan_block_for_var(
    name: str,
    cursor_line: int,
    block: Block,
    class_name: Optional[str],
    func_name: str,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Scan statements in a block for a variable declaration matching *name*."""
    best: Optional[str] = None
    for stmt in block.statements:
        result = _check_stmt_for_var(
            name, cursor_line, stmt, class_name, func_name, class_table
        )
        if result:
            best = result
    return best


def _check_stmt_for_var(
    name: str,
    cursor_line: int,
    stmt,
    class_name: Optional[str],
    func_name: str,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Check a single statement for a variable declaration."""
    if isinstance(stmt, VarDeclStmt):
        if stmt.name == name and stmt.line <= cursor_line:
            type_str = _infer_var_type(stmt, class_table)
            return f"```btrc\n{type_str} {name}\n```\nLocal variable"

    elif isinstance(stmt, ForInStmt):
        if stmt.line <= cursor_line:
            if stmt.var_name == name:
                return f"```btrc\nvar {name}\n```\nLoop variable"
            if stmt.var_name2 == name:
                return f"```btrc\nvar {name}\n```\nLoop variable (key)"
        if stmt.body:
            r = _scan_block_for_var(
                name, cursor_line, stmt.body, class_name, func_name, class_table
            )
            if r:
                return r

    elif isinstance(stmt, ParallelForStmt):
        if stmt.var_name == name and stmt.line <= cursor_line:
            return f"```btrc\nvar {name}\n```\nParallel loop variable"
        if stmt.body:
            r = _scan_block_for_var(
                name, cursor_line, stmt.body, class_name, func_name, class_table
            )
            if r:
                return r

    elif isinstance(stmt, CForStmt):
        if isinstance(stmt.init, ForInitVar):
            var_decl = stmt.init.var_decl
            if isinstance(var_decl, VarDeclStmt):
                if var_decl.name == name and var_decl.line <= cursor_line:
                    type_str = _infer_var_type(var_decl, class_table)
                    return f"```btrc\n{type_str} {name}\n```\nLoop variable"
        if stmt.body:
            r = _scan_block_for_var(
                name, cursor_line, stmt.body, class_name, func_name, class_table
            )
            if r:
                return r

    elif isinstance(stmt, TryCatchStmt):
        if stmt.catch_var == name and stmt.line <= cursor_line:
            return f"```btrc\nstring {name}\n```\nCatch variable"
        for block in (stmt.try_block, stmt.catch_block):
            if block:
                r = _scan_block_for_var(
                    name, cursor_line, block, class_name, func_name, class_table
                )
                if r:
                    return r

    elif isinstance(stmt, IfStmt):
        if stmt.then_block:
            r = _scan_block_for_var(
                name, cursor_line, stmt.then_block, class_name, func_name, class_table
            )
            if r:
                return r
        if isinstance(stmt.else_block, ElseBlock) and stmt.else_block.body:
            r = _scan_block_for_var(
                name, cursor_line, stmt.else_block.body, class_name, func_name, class_table
            )
            if r:
                return r
        elif isinstance(stmt.else_block, ElseIf) and stmt.else_block.if_stmt:
            r = _check_stmt_for_var(
                name, cursor_line, stmt.else_block.if_stmt, class_name, func_name, class_table
            )
            if r:
                return r

    elif isinstance(stmt, (WhileStmt, DoWhileStmt)):
        if stmt.body:
            r = _scan_block_for_var(
                name, cursor_line, stmt.body, class_name, func_name, class_table
            )
            if r:
                return r

    elif isinstance(stmt, SwitchStmt):
        for case in stmt.cases:
            if isinstance(case, CaseClause):
                for s in case.body:
                    r = _check_stmt_for_var(
                        name, cursor_line, s, class_name, func_name, class_table
                    )
                    if r:
                        return r

    return None


def _infer_var_type(stmt: VarDeclStmt, class_table: dict[str, ClassInfo]) -> str:
    """Infer a type string for a VarDeclStmt."""
    if stmt.type:
        return type_repr(stmt.type)
    if isinstance(stmt.initializer, CallExpr):
        callee = stmt.initializer.callee
        if isinstance(callee, Identifier):
            if callee.name in class_table:
                return callee.name
            return callee.name
    if isinstance(stmt.initializer, NewExpr):
        if stmt.initializer.type:
            return type_repr(stmt.initializer.type)
    return "var"
