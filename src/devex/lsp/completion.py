"""Code completion provider for btrc.

Provides keyword, type, member access, static method, and snippet completions.
"""

import re

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import (
    FieldDecl,
    MethodDecl,
)
from src.devex.lsp.builtins import (
    _MEMBER_TABLES,
    STDLIB_STATIC_METHODS,
    BuiltinMember,
    get_members_for_type,
)
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.utils import (
    document_position_to_resolved,
    find_enclosing_class,
    get_text_before_cursor,
    navigation_tokens,
    resolve_chain_type,
    resolve_member_type,
    resolve_variable_type,
    type_repr,
)

# ---------------------------------------------------------------------------
# Keyword completions
# ---------------------------------------------------------------------------

_BTRC_KEYWORDS = [
    ("class", "Declares a class with fields and methods"),
    ("public", "Access modifier: visible outside the class"),
    ("private", "Access modifier: only visible within the class"),
    ("if", "Conditional branch"),
    ("else", "Alternative branch of an if statement"),
    ("while", "Loop while condition is true"),
    ("for", "Loop construct (for-in)"),
    ("in", "Used in for-in loops"),
    ("return", "Return a value from a function/method"),
    ("var", "Declare a variable with type inference"),
    ("new", "Allocate an object on the heap"),
    ("delete", "Free a heap-allocated object"),
    ("try", "Begin a try/catch error handling block"),
    ("catch", "Catch an error thrown in a try block"),
    ("throw", "Throw an error (string value)"),
    ("null", "Null value for nullable types"),
    ("true", "Boolean literal true"),
    ("false", "Boolean literal false"),
    ("self", "Reference to the current object instance"),
    ("extends", "Specifies parent class for inheritance"),
    ("break", "Break out of a loop"),
    ("continue", "Skip to next loop iteration"),
    ("switch", "Multi-way branch"),
    ("case", "Branch in a switch statement"),
    ("default", "Default branch in a switch statement"),
    ("enum", "Declare an enumeration"),
    ("struct", "Declare a C-style struct"),
    ("typedef", "Create a type alias"),
    ("sizeof", "Size of a type or expression in bytes"),
    ("parallel", "Mark a for loop for parallel execution"),
    ("keep", "Marks a parameter as stored (rc++) or a return as transferring ownership"),
    ("release", "Decrement reference count; free at zero; set variable to NULL"),
]


# ---------------------------------------------------------------------------
# Type completions
# ---------------------------------------------------------------------------

# Primitive types are always present; collection/stdlib types come from builtins
_PRIMITIVE_TYPES = [
    ("int", "Integer type"),
    ("float", "Floating-point type"),
    ("double", "Double-precision floating-point type"),
    ("string", "String type"),
    ("bool", "Boolean type"),
    ("char", "Character type"),
    ("void", "Void type (no value)"),
    ("long", "Long integer type"),
    ("short", "Short integer type"),
    ("unsigned", "Unsigned integer modifier"),
]

# Auto-generate type entries from _MEMBER_TABLES (string is already above)
_BTRC_TYPES = list(_PRIMITIVE_TYPES) + [
    (name, f"Built-in type: {name}") for name in _MEMBER_TABLES if name not in {t[0] for t in _PRIMITIVE_TYPES}
]


# ---------------------------------------------------------------------------
# Snippet completions
# ---------------------------------------------------------------------------

_SNIPPETS = [
    (
        "class",
        "class ... { ... }",
        "Class with constructor",
        (
            "class ${1:ClassName} {\n"
            "\tpublic ${2:int} ${3:field};\n"
            "\n"
            "\tpublic ${1:ClassName}(${2:int} ${3:field}) {\n"
            "\t\tself.${3:field} = ${3:field};\n"
            "\t}\n"
            "\n"
            "\t$0\n"
            "}"
        ),
    ),
    (
        "for in",
        "for ... in range(...) { ... }",
        "For-in loop with range",
        ("for ${1:i} in range(${2:n}) {\n\t$0\n}"),
    ),
    (
        "for in collection",
        "for ... in collection { ... }",
        "For-in loop over collection",
        ("for ${1:item} in ${2:collection} {\n\t$0\n}"),
    ),
    (
        "try",
        "try { ... } catch(e) { ... }",
        "Try/catch block",
        ("try {\n\t$1\n} catch(${2:e}) {\n\t$0\n}"),
    ),
    (
        "if",
        "if (...) { ... }",
        "If statement",
        ("if (${1:condition}) {\n\t$0\n}"),
    ),
    (
        "if else",
        "if (...) { ... } else { ... }",
        "If/else statement",
        ("if (${1:condition}) {\n\t$2\n} else {\n\t$0\n}"),
    ),
    (
        "while",
        "while (...) { ... }",
        "While loop",
        ("while (${1:condition}) {\n\t$0\n}"),
    ),
    (
        "public method",
        "public ... method(...) { ... }",
        "Public method declaration",
        ("public ${1:void} ${2:methodName}(${3:}) {\n\t$0\n}"),
    ),
    (
        "println",
        'println("...")',
        "Print line",
        'println("${1:message}")$0',
    ),
]


# ---------------------------------------------------------------------------
# Completion builders
# ---------------------------------------------------------------------------


def _keyword_completions() -> list[lsp.CompletionItem]:
    items = []
    for kw, doc in _BTRC_KEYWORDS:
        items.append(
            lsp.CompletionItem(
                label=kw,
                kind=lsp.CompletionItemKind.Keyword,
                detail=doc,
                insert_text=kw,
            )
        )
    return items


def _type_completions() -> list[lsp.CompletionItem]:
    items = []
    for name, doc in _BTRC_TYPES:
        items.append(
            lsp.CompletionItem(
                label=name,
                kind=lsp.CompletionItemKind.Class,
                detail=doc,
                insert_text=name,
            )
        )
    return items


def _snippet_completions() -> list[lsp.CompletionItem]:
    items = []
    for label, filter_text, doc, body in _SNIPPETS:
        items.append(
            lsp.CompletionItem(
                label=label,
                kind=lsp.CompletionItemKind.Snippet,
                detail=doc,
                insert_text=body,
                insert_text_format=lsp.InsertTextFormat.Snippet,
                filter_text=filter_text,
            )
        )
    return items


def _class_name_completions(
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    items = []
    for name, info in class_table.items():
        detail = f"class {name}"
        if info.generic_params:
            detail += f"<{', '.join(info.generic_params)}>"
        if info.parent:
            detail += f" extends {info.parent}"
        items.append(
            lsp.CompletionItem(
                label=name,
                kind=lsp.CompletionItemKind.Class,
                detail=detail,
                insert_text=name,
            )
        )
    return items


def _builtin_member_items(members: list[BuiltinMember]) -> list[lsp.CompletionItem]:
    """Build completion items from BuiltinMember list."""
    items = []
    for m in members:
        if m.kind == "field":
            items.append(
                lsp.CompletionItem(
                    label=m.name,
                    kind=lsp.CompletionItemKind.Field,
                    detail=f"{m.return_type} (field)",
                    documentation=m.doc,
                    insert_text=m.name,
                )
            )
        else:
            params_str = ", ".join(f"{pt} {pn}" for pt, pn in m.params)
            detail = f"{m.return_type} {m.name}({params_str}) -- {m.doc}"
            items.append(
                lsp.CompletionItem(
                    label=m.name,
                    kind=lsp.CompletionItemKind.Method,
                    detail=detail,
                    insert_text=f"{m.name}($1)$0",
                    insert_text_format=lsp.InsertTextFormat.Snippet,
                )
            )
    return items


def _class_member_items(class_name: str, info: ClassInfo) -> list[lsp.CompletionItem]:
    items = []
    for fname, fdecl in info.fields.items():
        if isinstance(fdecl, FieldDecl):
            ftype = type_repr(fdecl.type)
            items.append(
                lsp.CompletionItem(
                    label=fname,
                    kind=lsp.CompletionItemKind.Field,
                    detail=f"{fdecl.access} {ftype} {fname}",
                    documentation=f"Field of {class_name}",
                    insert_text=fname,
                )
            )
    for mname, mdecl in info.methods.items():
        if isinstance(mdecl, MethodDecl):
            params = ", ".join(f"{type_repr(p.type)} {p.name}" for p in mdecl.params)
            ret = type_repr(mdecl.return_type)
            access = mdecl.access
            static = " (static)" if access == "class" else ""
            items.append(
                lsp.CompletionItem(
                    label=mname,
                    kind=lsp.CompletionItemKind.Method,
                    detail=f"{access} {ret} {mname}({params}){static}",
                    documentation=f"Method of {class_name}",
                    insert_text=f"{mname}($1)$0",
                    insert_text_format=lsp.InsertTextFormat.Snippet,
                )
            )
    return items


def _static_method_items(class_name: str, methods: list[BuiltinMember]) -> list[lsp.CompletionItem]:
    """Build completion items for stdlib static methods."""
    items = []
    for m in methods:
        params_str = ", ".join(f"{pt} {pn}" for pt, pn in m.params)
        doc = f"{m.return_type} {m.name}({params_str})"
        items.append(
            lsp.CompletionItem(
                label=m.name,
                kind=lsp.CompletionItemKind.Method,
                detail=doc,
                documentation=f"Static method of {class_name}",
                insert_text=f"{m.name}($1)$0",
                insert_text_format=lsp.InsertTextFormat.Snippet,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Main completion entry point
# ---------------------------------------------------------------------------


def get_completions(
    result: AnalysisResult,
    position: lsp.Position,
) -> list[lsp.CompletionItem]:
    """Compute completion items for the given cursor position."""
    text_before = get_text_before_cursor(result.source, position)
    class_table = result.analyzed.class_table if result.analyzed else {}

    token_items = _dot_completions_from_tokens(result, position, class_table)
    if token_items is not None:
        return token_items

    # Member-access completions on a (possibly chained) receiver ending in one
    # of . / ?. / -> , e.g. `obj.`, `obj?.`, `obj->`, or a chain `o.inner.`.
    chain_match = re.search(
        r"([A-Za-z_]\w*(?:\s*(?:\?\.|->|\.)\s*[A-Za-z_]\w*)*)\s*(?:\?\.|->|\.)\s*$",
        text_before,
    )
    if chain_match:
        return _dot_completions(result, chain_match.group(1), position, class_table)

    # General completions: keywords + types + snippets + class names
    items: list[lsp.CompletionItem] = []
    items.extend(_keyword_completions())
    items.extend(_type_completions())
    items.extend(_snippet_completions())
    items.extend(_class_name_completions(class_table))

    # Add stdlib class names that might not be in the class_table
    for stdlib_name in STDLIB_STATIC_METHODS:
        if stdlib_name not in class_table:
            items.append(
                lsp.CompletionItem(
                    label=stdlib_name,
                    kind=lsp.CompletionItemKind.Class,
                    detail=f"stdlib class {stdlib_name}",
                    insert_text=stdlib_name,
                )
            )

    return items


def _dot_completions_from_tokens(
    result: AnalysisResult,
    position: lsp.Position,
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem] | None:
    if not result.tokens:
        return None

    tokens = navigation_tokens(result.tokens)
    resolved_position = document_position_to_resolved(result, position)
    access_idx = _access_token_before_cursor(tokens, resolved_position)
    if access_idx is None or access_idx < 1:
        return None

    owner_idx = access_idx - 1
    owner = tokens[owner_idx]
    if owner.value in class_table or owner.value in STDLIB_STATIC_METHODS:
        return _static_completions(owner.value, class_table)

    owner_type = resolve_chain_type(result, tokens, owner_idx, class_table)
    if owner_type is None:
        return []
    return _members_for_type(owner_type, class_table)


def _access_token_before_cursor(tokens, position: lsp.Position) -> int | None:
    line = position.line + 1
    col = position.character + 1
    last_idx = None
    last_end = -1
    for index, token in enumerate(tokens):
        if token.line != line:
            continue
        start = token.col
        end = token.col + len(token.value)
        if start < col < end:
            return None
        if end <= col and end > last_end:
            last_idx = index
            last_end = end
    if last_idx is None or tokens[last_idx].value not in (".", "?.", "->"):
        return None
    return last_idx


def _static_completions(
    class_name: str,
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    items: list[lsp.CompletionItem] = []
    if class_name in class_table:
        items.extend(_class_member_items(class_name, class_table[class_name]))
    stdlib_methods = STDLIB_STATIC_METHODS.get(class_name)
    if stdlib_methods:
        existing_labels = {item.label for item in items}
        for item in _static_method_items(class_name, stdlib_methods):
            if item.label not in existing_labels:
                items.append(item)
    return items


def _dot_completions(
    result: AnalysisResult,
    receiver: str,
    position: lsp.Position,
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    """Completions after . / ?. / -> on a receiver, which may be a chain.

    A single segment that names a class gives static-method completions; a
    variable (or chain) is resolved to its type — walking each member hop via
    resolve_member_type — and that type's members are offered.
    """
    parts = re.split(r"\s*(?:\?\.|->|\.)\s*", receiver.strip())
    head, hops = parts[0], parts[1:]

    # Single-segment class name → static-method access.
    if not hops:
        items = _static_completions(head, class_table)
        if items:
            return items

    # Resolve the head's type (class-as-value or variable), then walk member hops.
    cur_type = head if head in class_table else _resolve_var_type(result, head, position.line)
    for hop in hops:
        if not cur_type:
            return []
        cur_type = resolve_member_type(cur_type, hop, class_table)

    if cur_type is not None:
        return _members_for_type(cur_type, class_table)

    return []


def _resolve_var_type(
    result: AnalysisResult,
    var_name: str,
    cursor_line: int,
) -> str | None:
    """Resolve variable type, handling 'self' specially."""
    if not result.ast:
        return None
    resolved_line = (
        document_position_to_resolved(
            result,
            lsp.Position(line=cursor_line, character=0),
        ).line
        + 1
    )
    if var_name == "self":
        return find_enclosing_class(result.ast, resolved_line)
    class_table = result.analyzed.class_table if result.analyzed else {}
    return resolve_variable_type(var_name, result.ast, class_table, resolved_line)


def _members_for_type(
    type_base: str,
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    """Return member completion items for a given base type."""
    # Built-in types
    members = get_members_for_type(type_base)
    if members:
        return _builtin_member_items(members)

    # User-defined class
    if type_base in class_table:
        return _class_member_items(type_base, class_table[type_base])

    return []
