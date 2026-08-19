"""Hover resolution and rendering."""

from __future__ import annotations

from types import MappingProxyType

from lsprotocol import types as lsp

from src.compiler.python.analyzer.program import ClassInfo
from src.compiler.python.syntax.ast.generated import CallExpr, FieldDecl, Identifier, MethodDecl, NewExpr, VarDeclStmt
from src.compiler.python.syntax.tokens import Token, TokenKind
from src.devex.lsp.analysis.document import DocumentAnalysis
from src.devex.lsp.analysis.resolution import SemanticResolver
from src.devex.lsp.catalog.builtins import BuiltinCatalog

_KEYWORD_DOCS = MappingProxyType(
    {
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
        "keep": "Marks a parameter as stored (refcount incremented at call site) or a return type as transferring ownership to the caller.",
        "release": "Decrements the reference count. If the count reaches zero, the object is destroyed and memory is freed. Sets the variable to NULL.",
    }
)


class HoverProvider:
    """Hover resolution and rendering."""

    def __init__(self, catalog: BuiltinCatalog, resolver: SemanticResolver, navigation) -> None:
        self.catalog = catalog
        self.resolver = resolver
        self.navigation = navigation
        self.keyword_docs = dict(_KEYWORD_DOCS)
        for type_name in catalog.type_names:
            if type_name in self.keyword_docs:
                continue
            members = catalog.members(type_name)
            methods = [member.name for member in members if member.kind == "method"]
            fields = [member.name for member in members if member.kind == "field"]
            parts = []
            if fields:
                parts.append("Fields: " + ", ".join(fields))
            if methods:
                preview = methods[:6]
                suffix = ", ..." if len(methods) > 6 else ""
                parts.append("Methods: " + ", ".join(f"{name}()" for name in preview) + suffix)
            self.keyword_docs[type_name] = f"Built-in type `{type_name}`. " + ". ".join(parts) + "."

    def _format_class_info(self, name: str, info: ClassInfo, class_table: dict[str, ClassInfo]) -> str:
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
                ftype = self.resolver.type_repr(fdecl.type, class_table) if isinstance(fdecl, FieldDecl) else "?"
                lines.append(f"- `{access} {ftype} {fname}`")
        if info.methods:
            lines.append("\n**Methods:**")
            for mname, mdecl in info.methods.items():
                if isinstance(mdecl, MethodDecl):
                    params = ", ".join(f"{self.resolver.type_repr(p.type, class_table)} {p.name}" for p in mdecl.params)
                    ret = self.resolver.type_repr(mdecl.return_type, class_table)
                    access = mdecl.access
                    lines.append(f"- `{access} {ret} {mname}({params})`")
        if info.constructor and isinstance(info.constructor, MethodDecl):
            params = ", ".join(
                f"{self.resolver.type_repr(p.type, class_table)} {p.name}" for p in info.constructor.params
            )
            lines.append(f"\n**Constructor:** `{name}({params})`")
        return "\n".join(lines)

    def _format_method_info(
        self, class_name: str, method_name: str, mdecl: MethodDecl, class_table: dict[str, ClassInfo]
    ) -> str:
        """Format hover content for a method."""
        params = ", ".join(f"{self.resolver.type_repr(p.type, class_table)} {p.name}" for p in mdecl.params)
        ret = self.resolver.type_repr(mdecl.return_type, class_table)
        access = mdecl.access
        static = " (static)" if access == "class" else ""
        return f"```btrc\n{access} {ret} {method_name}({params})\n```\nMethod of `{class_name}`{static}"

    def _format_field_info(
        self, class_name: str, field_name: str, fdecl: FieldDecl, class_table: dict[str, ClassInfo]
    ) -> str:
        """Format hover content for a field."""
        ftype = self.resolver.type_repr(fdecl.type, class_table)
        return f"```btrc\n{fdecl.access} {ftype} {field_name}\n```\nField of `{class_name}`"

    def get_hover_info(self, result: DocumentAnalysis, position: lsp.Position) -> lsp.Hover | None:
        """Return hover information for the token at the given position."""
        if not result.tokens or not result.is_current_at(position.line):
            return None
        tokens = self.resolver.nav_tokens(result)
        token = self.resolver.find_token_at_position(tokens, position, result.source)
        if token is None:
            return None
        content: str | None = None
        class_table = result.analyzed.class_table if result.analyzed else {}
        if token.value in class_table:
            content = self._format_class_info(token.value, class_table[token.value], class_table)
        elif token.value in self.keyword_docs:
            content = f"**`{token.value}`** — {self.keyword_docs[token.value]}"
        elif token.type == TokenKind.IDENT:
            content = self._try_member_hover(result, tokens, token, class_table)
            if content is None:
                content = self._try_variable_hover(result, token, class_table, position)
        if content is None:
            return None
        return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=content))

    def _try_member_hover(
        self, result: DocumentAnalysis, tokens: list[Token], token: Token, class_table: dict[str, ClassInfo]
    ) -> str | None:
        """Try to resolve hover for a member access (obj.field or obj.method)."""
        if not tokens:
            return None
        token_idx = self.resolver.find_token_index(tokens, token)
        if token_idx is None or token_idx < 2:
            return None
        prev = tokens[token_idx - 1]
        if prev.value not in (".", "->", "?."):
            return None
        member_name = token.value
        target_type = self.resolver.resolve_chain_type(result, tokens, token_idx - 2, class_table)
        if target_type is None:
            return None
        builtin_doc = self.catalog.hover_markdown(target_type, member_name)
        if builtin_doc:
            return f"{builtin_doc}\nBuilt-in member of `{target_type}`"
        cname = target_type
        while cname and cname in class_table:
            cinfo = class_table[cname]
            if member_name in cinfo.methods:
                mdecl = cinfo.methods[member_name]
                if isinstance(mdecl, MethodDecl):
                    return self._format_method_info(cname, member_name, mdecl, class_table)
            if member_name in cinfo.fields:
                fdecl = cinfo.fields[member_name]
                if isinstance(fdecl, FieldDecl):
                    return self._format_field_info(cname, member_name, fdecl, class_table)
            cname = cinfo.parent
        return None

    def _try_variable_hover(
        self,
        result: DocumentAnalysis,
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
        dmap = self.navigation.definition_map(result)
        vd = dmap.find_var_def(token.value, token.line, token.col)
        if vd is None:
            return None
        inferred = self.navigation.type_at(result, position) if position is not None else None
        name = vd.name
        if vd.kind == "param":
            type_str = (
                self.resolver.type_repr(inferred, class_table)
                if inferred is not None
                else self.resolver.type_repr(getattr(vd.node, "type", None), class_table)
            )
            return f"```btrc\n{type_str} {name}\n```\nParameter of `{vd.owner}`"
        if vd.kind in ("local", "cfor") and isinstance(vd.node, VarDeclStmt):
            type_str = (
                self.resolver.type_repr(inferred, class_table)
                if inferred is not None
                else self._infer_var_type(vd.node, class_table)
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

    def _infer_var_type(self, stmt: VarDeclStmt, class_table: dict[str, ClassInfo]) -> str:
        """Infer a type string for a VarDeclStmt."""
        if stmt.type:
            return self.resolver.type_repr(stmt.type, class_table)
        if isinstance(stmt.initializer, CallExpr):
            callee = stmt.initializer.callee
            if isinstance(callee, Identifier):
                return callee.name
        if isinstance(stmt.initializer, NewExpr):
            if stmt.initializer.type:
                return self.resolver.type_repr(stmt.initializer.type, class_table)
        return "var"
