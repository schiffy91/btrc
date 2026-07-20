"""Resolution of chained receivers and their member result types."""

from __future__ import annotations

from dataclasses import dataclass

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import FieldDecl, MethodDecl, PropertyDecl
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.builtins import (
    BUILTIN_FUNCTION_SIGNATURES,
    base_type_name,
    get_member,
)
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.position_utils import active_decls
from src.devex.lsp.scope_utils import (
    find_enclosing_class,
    find_enclosing_class_from_source,
)
from src.devex.lsp.variable_resolution import resolve_variable_type


@dataclass(frozen=True)
class ChainResolution:
    """The resolved receiver type and whether it denotes a type itself."""

    type_name: str
    direct_type_reference: bool = False


def resolve_chain(
    result: AnalysisResult,
    tokens: list[Token],
    end_idx: int,
    class_table: dict[str, ClassInfo],
    decls: list | None = None,
) -> ChainResolution | None:
    """Resolve the base type produced by an identifier/member/call chain."""
    root_idx, was_call = _chain_segment(tokens, end_idx)
    if root_idx is None or not _is_chain_identifier(tokens[root_idx]):
        return None
    chain: list[tuple[str, bool]] = [(tokens[root_idx].value, was_call)]

    while root_idx >= 2 and tokens[root_idx - 1].value in (".", "->", "?."):
        candidate, was_call = _chain_segment(tokens, root_idx - 2)
        if candidate is None or not _is_chain_identifier(tokens[candidate]):
            return None
        root_idx = candidate
        chain.append((tokens[root_idx].value, was_call))
    chain.reverse()

    root, root_called = chain[0]
    scope_decls = decls if decls is not None else active_decls(result)
    root_resolution = _resolve_root(
        result,
        root,
        root_called,
        tokens[root_idx],
        scope_decls,
        class_table,
        use_scope_map=decls is None,
    )
    if root_resolution is None:
        return None
    current_type = root_resolution.type_name

    receiver_is_type = root_resolution.direct_type_reference
    for member, called in chain[1:]:
        current_type = resolve_member_type(
            current_type,
            member,
            class_table,
            prefer_method=called,
            static_access=receiver_is_type,
        )
        if current_type is None:
            return None
        receiver_is_type = False

    return ChainResolution(
        current_type,
        direct_type_reference=(len(chain) == 1 and root_resolution.direct_type_reference),
    )


def _resolve_root(
    result: AnalysisResult,
    root: str,
    called: bool,
    token: Token,
    decls: list,
    class_table: dict[str, ClassInfo],
    *,
    use_scope_map: bool,
) -> ChainResolution | None:
    if called:
        if root in class_table:
            return ChainResolution(root)
        function_table = result.analyzed.function_table if result.analyzed else {}
        function = function_table.get(root)
        if function is not None and function.return_type:
            return ChainResolution(function.return_type.base)
        builtin = BUILTIN_FUNCTION_SIGNATURES.get(root)
        return ChainResolution(base_type_name(builtin[0])) if builtin else None
    if root == "self":
        enclosing = None
        if use_scope_map:
            enclosing = find_enclosing_class_from_source(
                decls,
                result.source,
                token.line - 1,
            )
        enclosing = enclosing or find_enclosing_class(decls, token.line)
        return ChainResolution(enclosing) if enclosing else None

    variable_type = resolve_variable_type(
        root,
        decls,
        class_table,
        token.line,
        result=result if use_scope_map else None,
        cursor_col=token.col,
    )
    if variable_type is not None:
        return ChainResolution(variable_type)
    return ChainResolution(root, direct_type_reference=True) if root in class_table else None


def resolve_chain_type(
    result: AnalysisResult,
    tokens: list[Token],
    end_idx: int,
    class_table: dict[str, ClassInfo],
    decls: list | None = None,
) -> str | None:
    """Compatibility wrapper returning only the type name."""
    resolved = resolve_chain(result, tokens, end_idx, class_table, decls)
    return resolved.type_name if resolved else None


def _is_chain_identifier(token: Token) -> bool:
    return token.type in (TokenType.IDENT, TokenType.SELF)


def _chain_segment(tokens: list[Token], index: int) -> tuple[int | None, bool]:
    if index < 0 or index >= len(tokens):
        return None, False
    if tokens[index].value != ")":
        return index, False
    return _skip_call_to_callee(tokens, index), True


def _skip_call_to_callee(tokens: list[Token], index: int) -> int | None:
    if index < 0 or index >= len(tokens):
        return None
    if tokens[index].value != ")":
        return index
    depth = 1
    index -= 1
    while index >= 0:
        if tokens[index].value == ")":
            depth += 1
        elif tokens[index].value == "(":
            depth -= 1
            if depth == 0:
                return index - 1 if index > 0 else None
        index -= 1
    return None


def resolve_member_type(
    owner_type: str,
    member_name: str,
    class_table: dict[str, ClassInfo],
    *,
    prefer_method: bool = False,
    static_access: bool | None = None,
) -> str | None:
    """Resolve the base type of a field or method result."""
    class_name = owner_type
    while class_name and class_name in class_table:
        info = class_table[class_name]
        if prefer_method:
            found, result = _method_return_type(info, member_name, static_access)
            if found:
                return result
        field = info.fields.get(member_name)
        if isinstance(field, FieldDecl) and field.type:
            if static_access is not None and (field.access == "class") != static_access:
                return None
            return field.type.base
        prop = info.properties.get(member_name)
        if isinstance(prop, PropertyDecl) and prop.type:
            if static_access is not None and (prop.access == "class") != static_access:
                return None
            return prop.type.base
        if not prefer_method:
            found, result = _method_return_type(info, member_name, static_access)
            if found:
                return result
        class_name = info.parent

    if static_access:
        return None
    member = get_member(owner_type, member_name)
    return base_type_name(member.return_type) if member else None


def _method_return_type(
    info: ClassInfo,
    name: str,
    static_access: bool | None,
) -> tuple[bool, str | None]:
    method = info.methods.get(name)
    if isinstance(method, MethodDecl) and method.return_type:
        if static_access is not None and (method.access == "class") != static_access:
            return True, None
        return True, method.return_type.base
    return False, None
