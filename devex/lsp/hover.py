"""Hover provider for btrc.

Shows type information when hovering over identifiers, keywords,
class names, and method calls.
"""

from typing import Optional

from lsprotocol import types as lsp

from src.compiler.python.tokens import Token, TokenType
from src.compiler.python.analyzer import ClassInfo
from src.compiler.python.ast_nodes import FieldDecl, MethodDecl

from devex.lsp.diagnostics import AnalysisResult


def _find_token_at_position(tokens: list[Token], position: lsp.Position) -> Optional[Token]:
    """Find the token that covers the given 0-based position."""
    target_line = position.line + 1  # btrc tokens use 1-based lines
    target_col = position.character + 1  # btrc tokens use 1-based cols

    best: Optional[Token] = None
    for tok in tokens:
        if tok.type == TokenType.EOF:
            continue
        if tok.line != target_line:
            continue
        tok_end_col = tok.col + len(tok.value)
        if tok.col <= target_col <= tok_end_col:
            best = tok
            break

    return best


def _type_repr(type_expr) -> str:
    """Format a TypeExpr as a string."""
    if type_expr is None:
        return "void"
    return repr(type_expr)


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
            ftype = _type_repr(fdecl.type) if isinstance(fdecl, FieldDecl) else "?"
            lines.append(f"- `{access} {ftype} {fname}`")

    if info.methods:
        lines.append("\n**Methods:**")
        for mname, mdecl in info.methods.items():
            if isinstance(mdecl, MethodDecl):
                params = ", ".join(f"{_type_repr(p.type)} {p.name}" for p in mdecl.params)
                ret = _type_repr(mdecl.return_type)
                access = mdecl.access
                lines.append(f"- `{access} {ret} {mname}({params})`")

    if info.constructor and isinstance(info.constructor, MethodDecl):
        params = ", ".join(f"{_type_repr(p.type)} {p.name}" for p in info.constructor.params)
        lines.append(f"\n**Constructor:** `{name}({params})`")

    return "\n".join(lines)


def _format_method_info(class_name: str, method_name: str, mdecl: MethodDecl) -> str:
    """Format hover content for a method."""
    params = ", ".join(f"{_type_repr(p.type)} {p.name}" for p in mdecl.params)
    ret = _type_repr(mdecl.return_type)
    access = mdecl.access
    static = " (static)" if access == "class" else ""
    return f"```btrc\n{access} {ret} {method_name}({params})\n```\nMethod of `{class_name}`{static}"


def _format_field_info(class_name: str, field_name: str, fdecl: FieldDecl) -> str:
    """Format hover content for a field."""
    ftype = _type_repr(fdecl.type)
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
    "List": "Generic dynamic array: `List<T>`. Methods: push(), get(), set(), len, pop(), free().",
    "Map": "Generic hash map: `Map<K, V>`. Methods: put(), get(), has(), remove(), free().",
    "Set": "Generic hash set: `Set<T>`. Methods: add(), contains(), has(), remove(), toList(), free().",
    "Array": "Fixed-size array type.",
    "string": "String type. Methods: .len(), .charAt(), .substring(), .trim(), .split(), .toUpper(), .toLower(), etc.",
    "bool": "Boolean type: `true` or `false`.",
}


def get_hover_info(result: AnalysisResult, position: lsp.Position) -> Optional[lsp.Hover]:
    """Return hover information for the token at the given position."""
    if not result.tokens:
        return None

    token = _find_token_at_position(result.tokens, position)
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
        # Try to find what class this identifier belongs to by looking for
        # preceding dot/arrow access patterns in the token stream
        content = _try_member_hover(result, token, class_table)

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

    # Find this token's index
    token_idx = None
    for i, t in enumerate(result.tokens):
        if t is token:
            token_idx = i
            break

    if token_idx is None or token_idx < 2:
        return None

    # Check if preceded by . or -> or ?.
    prev = result.tokens[token_idx - 1]
    if prev.value not in ('.', '->', '?.'):
        return None

    # The token before the dot is the object — check if it's a known class name
    obj_token = result.tokens[token_idx - 2]

    # Try to find the class: object could be a class name (for static methods)
    # or an instance variable whose type is a known class
    target_class = None
    if obj_token.value in class_table:
        target_class = obj_token.value
    else:
        # Check if the object name matches a constructor call pattern
        # (i.e., the variable was declared as `var x = ClassName(...)`)
        # For now, search all classes for this member name
        for cname, cinfo in class_table.items():
            if token.value in cinfo.methods or token.value in cinfo.fields:
                target_class = cname
                # Don't break — might be more specific match later

    if target_class is None:
        return None

    cinfo = class_table[target_class]
    member_name = token.value

    if member_name in cinfo.methods:
        mdecl = cinfo.methods[member_name]
        if isinstance(mdecl, MethodDecl):
            return _format_method_info(target_class, member_name, mdecl)

    if member_name in cinfo.fields:
        fdecl = cinfo.fields[member_name]
        if isinstance(fdecl, FieldDecl):
            return _format_field_info(target_class, member_name, fdecl)

    return None
