"""Hover provider for btrc.

Shows type information when hovering over identifiers, keywords,
class names, and method calls.
"""

from typing import Optional

from lsprotocol import types as lsp

from src.compiler.python.tokens import Token, TokenType
from src.compiler.python.analyzer import ClassInfo
from src.compiler.python.ast_nodes import (
    Block, ClassDecl, FieldDecl, FunctionDecl, MethodDecl, Param,
    VarDeclStmt, ForInStmt, CForStmt, ParallelForStmt, TryCatchStmt,
    IfStmt, WhileStmt, DoWhileStmt, SwitchStmt, CaseClause,
    CallExpr, Identifier, NewExpr, Program,
)

from devex.lsp.diagnostics import AnalysisResult
from devex.lsp.definition import (
    _resolve_variable_type, _find_enclosing_class, _body_range,
)


# ---------------------------------------------------------------------------
# Built-in member docs for hover on chained access (e.g. list.push)
# ---------------------------------------------------------------------------

_BUILTIN_METHODS: dict[str, dict[str, str]] = {
    "string": {
        "len": "```btrc\nint len\n```\nLength of the string (bytes)",
        "charAt": "```btrc\nchar charAt(int index)\n```\nCharacter at index",
        "trim": "```btrc\nstring trim()\n```\nRemove leading/trailing whitespace",
        "toUpper": "```btrc\nstring toUpper()\n```\nConvert to uppercase",
        "toLower": "```btrc\nstring toLower()\n```\nConvert to lowercase",
        "contains": "```btrc\nbool contains(string sub)\n```\nCheck if contains substring",
        "startsWith": "```btrc\nbool startsWith(string prefix)\n```\nCheck prefix",
        "endsWith": "```btrc\nbool endsWith(string suffix)\n```\nCheck suffix",
        "indexOf": "```btrc\nint indexOf(string sub)\n```\nIndex of first occurrence",
        "lastIndexOf": "```btrc\nint lastIndexOf(string sub)\n```\nIndex of last occurrence",
        "substring": "```btrc\nstring substring(int start, int end)\n```\nExtract substring",
        "equals": "```btrc\nbool equals(string other)\n```\nCompare strings",
        "split": "```btrc\nList<string> split(string delim)\n```\nSplit into list",
        "replace": "```btrc\nstring replace(string old, string new)\n```\nReplace occurrences",
        "isEmpty": "```btrc\nbool isEmpty()\n```\nTrue if string is empty",
        "reverse": "```btrc\nstring reverse()\n```\nReverse the string",
        "toInt": "```btrc\nint toInt()\n```\nParse as integer",
        "toFloat": "```btrc\nfloat toFloat()\n```\nParse as float",
    },
    "List": {
        "len": "```btrc\nint len\n```\nNumber of elements in the list",
        "push": "```btrc\nvoid push(T value)\n```\nAppend element to list",
        "get": "```btrc\nT get(int index)\n```\nGet element at index",
        "set": "```btrc\nvoid set(int index, T value)\n```\nSet element at index",
        "remove": "```btrc\nvoid remove(int index)\n```\nRemove element at index",
        "pop": "```btrc\nT pop()\n```\nRemove and return last element",
        "contains": "```btrc\nbool contains(T value)\n```\nCheck if list contains value",
        "indexOf": "```btrc\nint indexOf(T value)\n```\nIndex of first occurrence",
        "sort": "```btrc\nvoid sort()\n```\nSort the list in-place",
        "reverse": "```btrc\nvoid reverse()\n```\nReverse the list in-place",
        "slice": "```btrc\nList<T> slice(int start, int end)\n```\nExtract sub-list",
        "join": "```btrc\nstring join(string separator)\n```\nJoin elements with separator",
        "forEach": "```btrc\nvoid forEach(fn callback)\n```\nCall fn for each element",
        "filter": "```btrc\nList<T> filter(fn predicate)\n```\nFilter by predicate",
        "map": "```btrc\nList<T> map(fn transform)\n```\nApply fn to each element",
        "isEmpty": "```btrc\nbool isEmpty()\n```\nTrue if list has no elements",
        "first": "```btrc\nT first()\n```\nGet first element",
        "last": "```btrc\nT last()\n```\nGet last element",
        "free": "```btrc\nvoid free()\n```\nFree list memory",
    },
    "Map": {
        "len": "```btrc\nint len\n```\nNumber of entries in the map",
        "put": "```btrc\nvoid put(K key, V value)\n```\nInsert or update entry",
        "get": "```btrc\nV get(K key)\n```\nGet value by key",
        "has": "```btrc\nbool has(K key)\n```\nCheck if key exists",
        "contains": "```btrc\nbool contains(K key)\n```\nCheck if key exists",
        "keys": "```btrc\nList<K> keys()\n```\nGet list of keys",
        "values": "```btrc\nList<V> values()\n```\nGet list of values",
        "remove": "```btrc\nvoid remove(K key)\n```\nRemove entry by key",
        "isEmpty": "```btrc\nbool isEmpty()\n```\nTrue if map has no entries",
        "free": "```btrc\nvoid free()\n```\nFree map memory",
    },
    "Set": {
        "len": "```btrc\nint len\n```\nNumber of elements in the set",
        "add": "```btrc\nvoid add(T value)\n```\nAdd element to set",
        "contains": "```btrc\nbool contains(T value)\n```\nCheck if set contains value",
        "has": "```btrc\nbool has(T value)\n```\nCheck if set contains value",
        "remove": "```btrc\nvoid remove(T value)\n```\nRemove element from set",
        "toList": "```btrc\nList<T> toList()\n```\nConvert to list",
        "isEmpty": "```btrc\nbool isEmpty()\n```\nTrue if set has no elements",
        "free": "```btrc\nvoid free()\n```\nFree set memory",
    },
}


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
        if tok.col <= target_col < tok_end_col:
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
        # Try member access first (obj.member), then local variable/parameter
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


def _resolve_chain_type(
    result: AnalysisResult,
    tokens: list[Token],
    end_idx: int,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Walk backwards through a chained access (a.b.c) and resolve the base type.

    Given tokens ending at *end_idx* (the token before the final dot), resolves
    the type of the full chain.  Returns a base type string like "List", "string",
    "ClassInfo", etc.
    """
    # Walk backwards collecting the chain
    idx = end_idx
    chain: list[str] = [tokens[idx].value]

    while idx >= 2:
        prev = tokens[idx - 1]
        if prev.value not in ('.', '->', '?.'):
            break
        idx -= 2
        chain.append(tokens[idx].value)

    chain.reverse()  # now chain is [root, member1, member2, ...]

    # Resolve the root to a type
    root = chain[0]
    current_type: Optional[str] = None

    if root in class_table:
        current_type = root
    elif root == "self" and result.ast:
        current_type = _find_enclosing_class(result.ast, tokens[idx].line)
    elif result.ast:
        current_type = _resolve_variable_type(root, result.ast, class_table)

    if current_type is None:
        return None

    # Walk through the rest of the chain resolving field types
    for member in chain[1:]:
        resolved = _resolve_member_type(current_type, member, class_table)
        if resolved is None:
            return None
        current_type = resolved

    return current_type


def _resolve_member_type(
    owner_type: str,
    member_name: str,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Resolve the type of a member access on a given type.

    Returns the base type string of the member, or None.
    """
    # Check user-defined classes (walk inheritance chain)
    cname = owner_type
    while cname and cname in class_table:
        cinfo = class_table[cname]

        if member_name in cinfo.fields:
            fdecl = cinfo.fields[member_name]
            if isinstance(fdecl, FieldDecl) and fdecl.type:
                return fdecl.type.base
        if member_name in cinfo.methods:
            mdecl = cinfo.methods[member_name]
            if isinstance(mdecl, MethodDecl) and mdecl.return_type:
                return mdecl.return_type.base

        cname = cinfo.parent

    # Built-in type field types (simplified)
    if owner_type == "string":
        if member_name == "len":
            return "int"
    elif owner_type in ("List", "Map", "Set"):
        if member_name == "len":
            return "int"

    return None


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

    # The token before the dot is the object
    obj_token = result.tokens[token_idx - 2]
    member_name = token.value

    # Resolve the object's type via chain resolution (handles a.b.c patterns)
    target_type = _resolve_chain_type(
        result, result.tokens, token_idx - 2, class_table
    )

    # If no type resolved, try fallback: search all classes
    if target_type is None:
        for cname, cinfo in class_table.items():
            if member_name in cinfo.methods or member_name in cinfo.fields:
                target_type = cname
                break

    if target_type is None:
        return None

    # Check built-in type members first
    if target_type in _BUILTIN_METHODS:
        builtin_doc = _BUILTIN_METHODS[target_type].get(member_name)
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

        # Walk up the inheritance chain
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
    """Compute the scope end for a class member by looking at the next member's line."""
    members = decl.members
    # Use the next member's line - 1 as the scope boundary
    for i in range(member_idx + 1, len(members)):
        next_line = getattr(members[i], 'line', 0)
        if next_line > 0:
            return next_line - 1
    # Last member: use a generous bound
    return getattr(members[member_idx], 'line', 0) + 500


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
                info = _check_callable(name, cursor_line, member,
                                       decl.name, class_table, scope_end)
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
        _, scope_end = _body_range(node.body, node.line)

    if not (scope_start <= cursor_line <= scope_end):
        return None

    # Check parameters first
    for p in node.params:
        if p.name == name:
            type_str = _type_repr(p.type)
            ctx = f"Parameter of `{class_name}.{node.name}`" if class_name else f"Parameter of `{node.name}`"
            return f"```btrc\n{type_str} {name}\n```\n{ctx}"

    # Check body statements
    if node.body:
        return _scan_block_for_var(name, cursor_line, node.body, class_name,
                                   node.name, class_table)
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
        result = _check_stmt_for_var(name, cursor_line, stmt,
                                     class_name, func_name, class_table)
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
            r = _scan_block_for_var(name, cursor_line, stmt.body,
                                    class_name, func_name, class_table)
            if r:
                return r

    elif isinstance(stmt, ParallelForStmt):
        if stmt.var_name == name and stmt.line <= cursor_line:
            return f"```btrc\nvar {name}\n```\nParallel loop variable"
        if stmt.body:
            r = _scan_block_for_var(name, cursor_line, stmt.body,
                                    class_name, func_name, class_table)
            if r:
                return r

    elif isinstance(stmt, CForStmt):
        if isinstance(stmt.init, VarDeclStmt):
            if stmt.init.name == name and stmt.init.line <= cursor_line:
                type_str = _infer_var_type(stmt.init, class_table)
                return f"```btrc\n{type_str} {name}\n```\nLoop variable"
        if stmt.body:
            r = _scan_block_for_var(name, cursor_line, stmt.body,
                                    class_name, func_name, class_table)
            if r:
                return r

    elif isinstance(stmt, TryCatchStmt):
        if stmt.catch_var == name and stmt.line <= cursor_line:
            return f"```btrc\nstring {name}\n```\nCatch variable"
        for block in (stmt.try_block, stmt.catch_block):
            if block:
                r = _scan_block_for_var(name, cursor_line, block,
                                        class_name, func_name, class_table)
                if r:
                    return r

    elif isinstance(stmt, IfStmt):
        if stmt.then_block:
            r = _scan_block_for_var(name, cursor_line, stmt.then_block,
                                    class_name, func_name, class_table)
            if r:
                return r
        if isinstance(stmt.else_block, Block):
            r = _scan_block_for_var(name, cursor_line, stmt.else_block,
                                    class_name, func_name, class_table)
            if r:
                return r
        elif isinstance(stmt.else_block, IfStmt):
            r = _check_stmt_for_var(name, cursor_line, stmt.else_block,
                                    class_name, func_name, class_table)
            if r:
                return r

    elif isinstance(stmt, (WhileStmt, DoWhileStmt)):
        if stmt.body:
            r = _scan_block_for_var(name, cursor_line, stmt.body,
                                    class_name, func_name, class_table)
            if r:
                return r

    elif isinstance(stmt, SwitchStmt):
        for case in stmt.cases:
            if isinstance(case, CaseClause):
                for s in case.body:
                    r = _check_stmt_for_var(name, cursor_line, s,
                                            class_name, func_name, class_table)
                    if r:
                        return r

    return None


def _infer_var_type(stmt: VarDeclStmt, class_table: dict[str, ClassInfo]) -> str:
    """Infer a type string for a VarDeclStmt."""
    # Explicit type annotation
    if stmt.type:
        return _type_repr(stmt.type)
    # Constructor call: var x = ClassName(...)
    if isinstance(stmt.initializer, CallExpr):
        callee = stmt.initializer.callee
        if isinstance(callee, Identifier):
            if callee.name in class_table:
                return callee.name
            return callee.name  # might be a function, still useful
    # new ClassName(...)
    if isinstance(stmt.initializer, NewExpr):
        if stmt.initializer.type:
            return _type_repr(stmt.initializer.type)
    return "var"
