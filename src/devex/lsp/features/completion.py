"""Completion ownership for grammar, snippets, types, and member access."""

from __future__ import annotations

import re
from types import MappingProxyType

from lsprotocol import types as lsp

from src.compiler.python.analyzer.program import ClassInfo
from src.compiler.python.syntax.ast.generated import FieldDecl, MethodDecl, PropertyDecl
from src.compiler.python.syntax.tokens import Token, TokenKind, TokenVocabulary
from src.devex.lsp.analysis.document import DocumentAnalysis
from src.devex.lsp.analysis.resolution import LexicalScopeIndex, SemanticResolver
from src.devex.lsp.catalog.builtins import BuiltinCatalog
from src.devex.lsp.catalog.generated import BuiltinMemberSpec

_RESERVED_WITHOUT_SYNTAX = frozenset({"auto", "goto", "override", "register"})
_KEYWORD_DOCS = MappingProxyType(
    {
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
)
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
_PRIMITIVE_NAMES = frozenset((name for name, _ in _PRIMITIVE_TYPES))
_SNIPPETS = (
    (
        "class",
        "class ... { ... }",
        "Class with constructor",
        "class ${1:ClassName} {\n\tpublic ${2:int} ${3:field};\n\n\tpublic ${1:ClassName}(${2:int} ${3:field}) {\n\t\tself.${3:field} = ${3:field};\n\t}\n\n\t$0\n}",
    ),
    ("for in", "for ... in range(...) { ... }", "For-in loop with range", "for ${1:i} in range(${2:n}) {\n\t$0\n}"),
    (
        "for in collection",
        "for ... in collection { ... }",
        "For-in loop over a collection",
        "for ${1:item} in ${2:collection} {\n\t$0\n}",
    ),
    ("try", "try { ... } catch(e) { ... }", "Try/catch block", "try {\n\t$1\n} catch(${2:e}) {\n\t$0\n}"),
    ("if", "if (...) { ... }", "If statement", "if (${1:condition}) {\n\t$0\n}"),
    ("if else", "if (...) { ... } else { ... }", "If/else statement", "if (${1:condition}) {\n\t$2\n} else {\n\t$0\n}"),
    ("while", "while (...) { ... }", "While loop", "while (${1:condition}) {\n\t$0\n}"),
    (
        "public method",
        "public ... method(...) { ... }",
        "Public method declaration",
        "public ${1:void} ${2:methodName}(${3:}) {\n\t$0\n}",
    ),
    ("println", 'println("...")', "Print a line", 'println("${1:message}")$0'),
)
_ACCESS_VALUES = frozenset({".", "?.", "->"})
_MEMBER_ACCESS_RE = re.compile(
    "([A-Za-z_]\\w*(?:\\s*(?:\\?\\.|->|\\.)\\s*[A-Za-z_]\\w*)*)\\s*(?:\\?\\.|->|\\.)\\s*(?:[A-Za-z_]\\w*)?\\s*$"
)


class CompletionProvider:
    """Completion ownership for grammar, snippets, types, and member access."""

    def __init__(self, catalog: BuiltinCatalog, resolver: SemanticResolver) -> None:
        self.catalog = catalog
        self.resolver = resolver

    def keyword_completions(self) -> list[lsp.CompletionItem]:
        """Build completions from the grammar's authoritative keyword table."""
        return [
            lsp.CompletionItem(
                label=keyword,
                kind=lsp.CompletionItemKind.Keyword,
                detail=_KEYWORD_DOCS.get(keyword, f"btrc keyword: {keyword}"),
                insert_text=keyword,
            )
            for keyword in sorted(TokenVocabulary.canonical().keywords)
            if keyword not in _RESERVED_WITHOUT_SYNTAX
        ]

    def type_completions(self) -> list[lsp.CompletionItem]:
        types = list(_PRIMITIVE_TYPES)
        types.extend(
            (name, f"Built-in type: {name}") for name in self.catalog.type_names if name not in _PRIMITIVE_NAMES
        )
        return [
            lsp.CompletionItem(label=name, kind=lsp.CompletionItemKind.Class, detail=doc, insert_text=name)
            for name, doc in types
        ]

    def snippet_completions(self) -> list[lsp.CompletionItem]:
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

    def class_name_completions(self, class_table: dict[str, ClassInfo]) -> list[lsp.CompletionItem]:
        items: list[lsp.CompletionItem] = []
        for name, info in class_table.items():
            detail = f"class {name}"
            if info.generic_params:
                detail += f"<{', '.join(info.generic_params)}>"
            if info.parent:
                detail += f" extends {info.parent}"
            items.append(
                lsp.CompletionItem(label=name, kind=lsp.CompletionItemKind.Class, detail=detail, insert_text=name)
            )
        return items

    def general_completions(self, class_table: dict[str, ClassInfo]) -> list[lsp.CompletionItem]:
        items = self.keyword_completions() + self.type_completions() + self.snippet_completions()
        items.extend(self.class_name_completions(class_table))
        for name in self.catalog.static_class_names:
            if name not in class_table:
                items.append(
                    lsp.CompletionItem(
                        label=name, kind=lsp.CompletionItemKind.Class, detail=f"stdlib class {name}", insert_text=name
                    )
                )
        return items

    def _builtin_member_items(self, members: tuple[BuiltinMemberSpec, ...]) -> list[lsp.CompletionItem]:
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
            params = ", ".join((f"{ptype} {name}" for ptype, name in member.params))
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

    def _field_item(self, class_name: str, name: str, field: FieldDecl) -> lsp.CompletionItem:
        return lsp.CompletionItem(
            label=name,
            kind=lsp.CompletionItemKind.Field,
            detail=f"{field.access} {self.resolver.type_repr(field.type)} {name}",
            documentation=f"Field of {class_name}",
            insert_text=name,
        )

    def _method_item(self, class_name: str, name: str, method: MethodDecl) -> lsp.CompletionItem:
        params = ", ".join(f"{self.resolver.type_repr(param.type)} {param.name}" for param in method.params)
        static = " (static)" if method.access == "class" else ""
        return lsp.CompletionItem(
            label=name,
            kind=lsp.CompletionItemKind.Method,
            detail=f"{method.access} {self.resolver.type_repr(method.return_type)} {name}({params}){static}",
            documentation=f"Method of {class_name}",
            insert_text=f"{name}($1)$0",
            insert_text_format=lsp.InsertTextFormat.Snippet,
        )

    def _property_item(self, class_name: str, name: str, prop: PropertyDecl) -> lsp.CompletionItem:
        accessors = ", ".join(
            (accessor for accessor, present in (("get", prop.has_getter), ("set", prop.has_setter)) if present)
        )
        return lsp.CompletionItem(
            label=name,
            kind=lsp.CompletionItemKind.Property,
            detail=f"{prop.access} {self.resolver.type_repr(prop.type)} {name} ({accessors})",
            documentation=f"Property of {class_name}",
            insert_text=name,
        )

    def class_member_items(
        self, class_name: str, class_table: dict[str, ClassInfo], *, static_only: bool
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
                items.append(self._field_item(current, name, field))
                seen.add(name)
            for name, prop in info.properties.items():
                if name in seen or not isinstance(prop, PropertyDecl):
                    continue
                if (prop.access == "class") != static_only:
                    continue
                items.append(self._property_item(current, name, prop))
                seen.add(name)
            for name, method in info.methods.items():
                if name in seen or not isinstance(method, MethodDecl) or method is info.constructor:
                    continue
                is_static = method.access == "class"
                if is_static != static_only:
                    continue
                items.append(self._method_item(current, name, method))
                seen.add(name)
            current = info.parent
        return items

    def _static_method_items(self, class_name: str, methods: tuple[BuiltinMemberSpec, ...]) -> list[lsp.CompletionItem]:
        items: list[lsp.CompletionItem] = []
        for method in methods:
            params = ", ".join((f"{ptype} {name}" for ptype, name in method.params))
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

    def static_completions(self, class_name: str, class_table: dict[str, ClassInfo]) -> list[lsp.CompletionItem]:
        """Return static members; a live class shadows generated stdlib metadata."""
        if class_name in class_table:
            return self.class_member_items(class_name, class_table, static_only=True)
        methods = self.catalog.static_methods(class_name) or ()
        return self._static_method_items(class_name, methods)

    def members_for_type(self, type_name: str, class_table: dict[str, ClassInfo]) -> list[lsp.CompletionItem]:
        """Return instance members, merging compiler intrinsics without duplicates."""
        items = self.class_member_items(type_name, class_table, static_only=False) if type_name in class_table else []
        seen = {item.label for item in items}
        for item in self._builtin_member_items(self.catalog.members(type_name)):
            if item.label not in seen:
                items.append(item)
                seen.add(item.label)
        return items

    def get_completions(self, result: DocumentAnalysis, position: lsp.Position) -> list[lsp.CompletionItem]:
        """Compute completion items at a document position."""
        position = result.text.source_position(position)
        class_table = result.analyzed.class_table if result.analyzed else {}
        token_items = self._dot_completions_from_tokens(result, position, class_table)
        if token_items is not None:
            return token_items
        match = _MEMBER_ACCESS_RE.search(self.resolver.get_text_before_cursor(result.source, position))
        if match:
            return self._dot_completions(result, match.group(1), position, class_table)
        return self.general_completions(class_table)

    def _dot_completions_from_tokens(
        self, result: DocumentAnalysis, position: lsp.Position, class_table: dict[str, ClassInfo]
    ) -> list[lsp.CompletionItem] | None:
        if not result.tokens or result.line_changed_since_snapshot(position.line):
            return None
        tokens = self.resolver.nav_tokens(result)
        access_idx = self._access_token_before_cursor(tokens, position)
        if access_idx is None or access_idx < 1:
            return None
        owner_idx = access_idx - 1
        resolved = self.resolver.resolve_chain(result, tokens, owner_idx, class_table)
        if resolved is not None:
            if resolved.direct_type_reference:
                return self.static_completions(resolved.type_name, class_table)
            return self.members_for_type(resolved.type_name, class_table)
        owner = tokens[owner_idx]
        if self._is_simple_receiver(tokens, owner_idx) and self.catalog.static_methods(owner.value) is not None:
            return self.static_completions(owner.value, class_table)
        return []

    def _access_token_before_cursor(self, tokens: list[Token], position: lsp.Position) -> int | None:
        """Find access punctuation immediately before an optional partial member."""
        line = position.line + 1
        caret_col = position.character + 1
        for index, token in enumerate(tokens):
            if token.line != line or token.type not in (TokenKind.IDENT, TokenKind.SELF):
                continue
            token_end = token.col + len(token.value)
            if token.col <= caret_col <= token_end and index > 0:
                if tokens[index - 1].value in _ACCESS_VALUES:
                    return index - 1
        latest: tuple[int, int] | None = None
        for index, token in enumerate(tokens):
            if token.line != line or token.value not in _ACCESS_VALUES:
                continue
            token_end = token.col + len(token.value)
            if token_end <= caret_col and (latest is None or token_end > latest[1]):
                latest = (index, token_end)
        if latest is None:
            return None
        access_idx, access_end = latest
        for token in tokens[access_idx + 1 :]:
            if token.line != line:
                continue
            if token.col < caret_col and token.col >= access_end:
                return None
        return access_idx

    def _is_simple_receiver(self, tokens: list[Token], index: int) -> bool:
        if index < 0 or index >= len(tokens) or tokens[index].value == ")":
            return False
        return index < 1 or tokens[index - 1].value not in _ACCESS_VALUES

    def _dot_completions(
        self, result: DocumentAnalysis, receiver: str, position: lsp.Position, class_table: dict[str, ClassInfo]
    ) -> list[lsp.CompletionItem]:
        """Resolve a live-text receiver during the analysis debounce window."""
        parts = re.split("\\s*(?:\\?\\.|->|\\.)\\s*", receiver.strip())
        head, hops = (parts[0], parts[1:])
        current_type = self._resolve_var_type(result, head, position)
        receiver_is_type = False
        if not hops and current_type is None:
            if head in class_table or self.catalog.static_methods(head) is not None:
                return self.static_completions(head, class_table)
        if current_type is None and head in class_table:
            current_type = head
            receiver_is_type = True
        for hop in hops:
            if current_type is None:
                return []
            current_type = self.resolver.resolve_member_type(
                current_type, hop, class_table, static_access=receiver_is_type
            )
            receiver_is_type = False
        return self.members_for_type(current_type, class_table) if current_type else []

    def _resolve_var_type(self, result: DocumentAnalysis, var_name: str, position: lsp.Position) -> str | None:
        if not result.ast:
            return None
        line = position.line + 1
        if var_name == "self":
            decls = self.resolver.active_decls(result)
            return LexicalScopeIndex.find_enclosing_class_from_source(
                decls, result.source, position.line
            ) or LexicalScopeIndex.find_enclosing_class(decls, line)
        class_table = result.analyzed.class_table if result.analyzed else {}
        return self.resolver.resolve_variable_type(
            var_name,
            self.resolver.active_decls(result),
            class_table,
            line,
            result=result,
            cursor_col=position.character + 1,
        )

    def _class_member_items(self, class_name: str, info: ClassInfo) -> list[lsp.CompletionItem]:
        return self.class_member_items(class_name, {class_name: info}, static_only=False)

    def _static_completions(self, class_name: str, class_table: dict[str, ClassInfo]) -> list[lsp.CompletionItem]:
        return self.static_completions(class_name, class_table)

    def _members_for_type(self, type_base: str, class_table: dict[str, ClassInfo]) -> list[lsp.CompletionItem]:
        return self.members_for_type(type_base, class_table)
