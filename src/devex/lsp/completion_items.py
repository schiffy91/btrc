"""Completion-item builders for instance and class member access."""

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import FieldDecl, MethodDecl, PropertyDecl
from src.devex.lsp.builtins import (
    STDLIB_STATIC_METHODS,
    BuiltinMember,
    get_members_for_type,
)
from src.devex.lsp.position_utils import type_repr


def _builtin_member_items(members: list[BuiltinMember]) -> list[lsp.CompletionItem]:
    items: list[lsp.CompletionItem] = []
    for member in members:
        if member.kind == "field":
            items.append(
                lsp.CompletionItem(
                    label=member.name,
                    kind=lsp.CompletionItemKind.Field,
                    detail=f"{member.return_type} (field)",
                    documentation=member.doc,
                    insert_text=member.name,
                )
            )
            continue
        params = ", ".join(f"{ptype} {name}" for ptype, name in member.params)
        items.append(
            lsp.CompletionItem(
                label=member.name,
                kind=lsp.CompletionItemKind.Method,
                detail=f"{member.return_type} {member.name}({params}) -- {member.doc}",
                insert_text=f"{member.name}($1)$0",
                insert_text_format=lsp.InsertTextFormat.Snippet,
            )
        )
    return items


def _field_item(class_name: str, name: str, field: FieldDecl) -> lsp.CompletionItem:
    return lsp.CompletionItem(
        label=name,
        kind=lsp.CompletionItemKind.Field,
        detail=f"{field.access} {type_repr(field.type)} {name}",
        documentation=f"Field of {class_name}",
        insert_text=name,
    )


def _method_item(class_name: str, name: str, method: MethodDecl) -> lsp.CompletionItem:
    params = ", ".join(f"{type_repr(param.type)} {param.name}" for param in method.params)
    static = " (static)" if method.access == "class" else ""
    return lsp.CompletionItem(
        label=name,
        kind=lsp.CompletionItemKind.Method,
        detail=f"{method.access} {type_repr(method.return_type)} {name}({params}){static}",
        documentation=f"Method of {class_name}",
        insert_text=f"{name}($1)$0",
        insert_text_format=lsp.InsertTextFormat.Snippet,
    )


def _property_item(
    class_name: str,
    name: str,
    prop: PropertyDecl,
) -> lsp.CompletionItem:
    accessors = ", ".join(
        accessor for accessor, present in (("get", prop.has_getter), ("set", prop.has_setter)) if present
    )
    return lsp.CompletionItem(
        label=name,
        kind=lsp.CompletionItemKind.Property,
        detail=f"{prop.access} {type_repr(prop.type)} {name} ({accessors})",
        documentation=f"Property of {class_name}",
        insert_text=name,
    )


def class_member_items(
    class_name: str,
    class_table: dict[str, ClassInfo],
    *,
    static_only: bool,
) -> list[lsp.CompletionItem]:
    """Build inherited live-class members for one access mode."""
    items: list[lsp.CompletionItem] = []
    seen: set[str] = set()
    current = class_name
    while current and current in class_table:
        info = class_table[current]
        fields = info.static_fields if static_only else info.fields
        for name, field in fields.items():
            if name in seen or not isinstance(field, FieldDecl):
                continue
            items.append(_field_item(current, name, field))
            seen.add(name)
        for name, prop in info.properties.items():
            if name in seen or not isinstance(prop, PropertyDecl):
                continue
            if (prop.access == "class") != static_only:
                continue
            items.append(_property_item(current, name, prop))
            seen.add(name)
        for name, method in info.methods.items():
            if name in seen or not isinstance(method, MethodDecl) or method is info.constructor:
                continue
            is_static = method.access == "class"
            if is_static != static_only:
                continue
            items.append(_method_item(current, name, method))
            seen.add(name)
        current = info.parent
    return items


def _static_method_items(
    class_name: str,
    methods: list[BuiltinMember],
) -> list[lsp.CompletionItem]:
    items: list[lsp.CompletionItem] = []
    for method in methods:
        params = ", ".join(f"{ptype} {name}" for ptype, name in method.params)
        items.append(
            lsp.CompletionItem(
                label=method.name,
                kind=lsp.CompletionItemKind.Method,
                detail=f"{method.return_type} {method.name}({params})",
                documentation=f"Static method of {class_name}",
                insert_text=f"{method.name}($1)$0",
                insert_text_format=lsp.InsertTextFormat.Snippet,
            )
        )
    return items


def static_completions(
    class_name: str,
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    """Return static members; a live class shadows generated stdlib metadata."""
    if class_name in class_table:
        return class_member_items(class_name, class_table, static_only=True)
    methods = STDLIB_STATIC_METHODS.get(class_name, [])
    return _static_method_items(class_name, methods)


def members_for_type(
    type_name: str,
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    """Return instance members, merging compiler intrinsics without duplicates."""
    items = class_member_items(type_name, class_table, static_only=False) if type_name in class_table else []
    seen = {item.label for item in items}
    for item in _builtin_member_items(get_members_for_type(type_name)):
        if item.label not in seen:
            items.append(item)
            seen.add(item.label)
    return items


_members_for_type = members_for_type
_static_completions = static_completions
