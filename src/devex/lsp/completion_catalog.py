"""Grammar-driven keywords, types, snippets, and top-level completions."""

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.tokens import KEYWORDS
from src.devex.lsp.builtins import _MEMBER_TABLES, STDLIB_STATIC_METHODS

_RESERVED_WITHOUT_SYNTAX = frozenset({"auto", "goto", "override", "register"})
_KEYWORD_DOCS = {
    "abstract": "Declare a class or method that requires an implementation",
    "break": "Exit the nearest loop or switch",
    "case": "Declare a switch branch",
    "catch": "Handle an error thrown by a try block",
    "class": "Declare a class",
    "continue": "Continue with the next loop iteration",
    "default": "Declare the fallback switch branch",
    "delete": "Free a heap-allocated object",
    "else": "Declare an alternative conditional branch",
    "extends": "Specify a parent class",
    "finally": "Run cleanup after try/catch",
    "for": "Declare a loop",
    "function": "Declare a function type",
    "implements": "Specify implemented interfaces",
    "import": "Import declarations from another source file",
    "in": "Iterate over a collection",
    "interface": "Declare an interface contract",
    "keep": "Retain an owned reference",
    "new": "Allocate an object",
    "parallel": "Run eligible loop iterations in parallel",
    "private": "Restrict a member to its class",
    "public": "Expose a member outside its class",
    "release": "Release an owned reference",
    "return": "Return from a function or method",
    "self": "Refer to the current object",
    "spawn": "Start concurrent work",
    "static": "Declare class-level storage or behavior",
    "super": "Refer to parent-class behavior",
    "throw": "Raise an error",
    "try": "Begin an error-handling region",
    "typedef": "Declare a type alias",
    "var": "Declare a variable with inferred type",
}

_PRIMITIVE_TYPES = (
    ("int", "Integer type"),
    ("float", "Floating-point type"),
    ("double", "Double-precision floating-point type"),
    ("string", "String type"),
    ("bool", "Boolean type"),
    ("char", "Character type"),
    ("void", "No-value type"),
    ("long", "Long integer type"),
    ("short", "Short integer type"),
    ("unsigned", "Unsigned integer modifier"),
)
_PRIMITIVE_NAMES = frozenset(name for name, _ in _PRIMITIVE_TYPES)

_SNIPPETS = (
    (
        "class",
        "class ... { ... }",
        "Class with constructor",
        (
            "class ${1:ClassName} {\n"
            "\tpublic ${2:int} ${3:field};\n\n"
            "\tpublic ${1:ClassName}(${2:int} ${3:field}) {\n"
            "\t\tself.${3:field} = ${3:field};\n\t}\n\n\t$0\n}"
        ),
    ),
    (
        "for in",
        "for ... in range(...) { ... }",
        "For-in loop with range",
        "for ${1:i} in range(${2:n}) {\n\t$0\n}",
    ),
    (
        "for in collection",
        "for ... in collection { ... }",
        "For-in loop over a collection",
        "for ${1:item} in ${2:collection} {\n\t$0\n}",
    ),
    (
        "try",
        "try { ... } catch(e) { ... }",
        "Try/catch block",
        "try {\n\t$1\n} catch(${2:e}) {\n\t$0\n}",
    ),
    ("if", "if (...) { ... }", "If statement", "if (${1:condition}) {\n\t$0\n}"),
    (
        "if else",
        "if (...) { ... } else { ... }",
        "If/else statement",
        "if (${1:condition}) {\n\t$2\n} else {\n\t$0\n}",
    ),
    (
        "while",
        "while (...) { ... }",
        "While loop",
        "while (${1:condition}) {\n\t$0\n}",
    ),
    (
        "public method",
        "public ... method(...) { ... }",
        "Public method declaration",
        "public ${1:void} ${2:methodName}(${3:}) {\n\t$0\n}",
    ),
    ("println", 'println("...")', "Print a line", 'println("${1:message}")$0'),
)


def keyword_completions() -> list[lsp.CompletionItem]:
    """Build completions from the grammar's authoritative keyword table."""
    return [
        lsp.CompletionItem(
            label=keyword,
            kind=lsp.CompletionItemKind.Keyword,
            detail=_KEYWORD_DOCS.get(keyword, f"btrc keyword: {keyword}"),
            insert_text=keyword,
        )
        for keyword in sorted(KEYWORDS)
        if keyword not in _RESERVED_WITHOUT_SYNTAX
    ]


def type_completions() -> list[lsp.CompletionItem]:
    types = list(_PRIMITIVE_TYPES)
    types.extend((name, f"Built-in type: {name}") for name in _MEMBER_TABLES if name not in _PRIMITIVE_NAMES)
    return [
        lsp.CompletionItem(
            label=name,
            kind=lsp.CompletionItemKind.Class,
            detail=doc,
            insert_text=name,
        )
        for name, doc in types
    ]


def snippet_completions() -> list[lsp.CompletionItem]:
    return [
        lsp.CompletionItem(
            label=label,
            kind=lsp.CompletionItemKind.Snippet,
            detail=doc,
            insert_text=body,
            insert_text_format=lsp.InsertTextFormat.Snippet,
            filter_text=filter_text,
        )
        for label, filter_text, doc, body in _SNIPPETS
    ]


def class_name_completions(
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    items: list[lsp.CompletionItem] = []
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


def general_completions(
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    items = keyword_completions() + type_completions() + snippet_completions()
    items.extend(class_name_completions(class_table))
    for name in STDLIB_STATIC_METHODS:
        if name not in class_table:
            items.append(
                lsp.CompletionItem(
                    label=name,
                    kind=lsp.CompletionItemKind.Class,
                    detail=f"stdlib class {name}",
                    insert_text=name,
                )
            )
    return items


# Compatibility aliases for callers that imported the former private builders.
_keyword_completions = keyword_completions
_type_completions = type_completions
_snippet_completions = snippet_completions
_class_name_completions = class_name_completions
