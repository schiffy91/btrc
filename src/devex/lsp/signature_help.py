"""Function, constructor, and method signature help for btrc."""

import re

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import FunctionDecl, MethodDecl
from src.compiler.python.tokens import Token
from src.devex.lsp.builtins import (
    BUILTIN_FUNCTION_SIGNATURES,
    get_signature_params,
    get_stdlib_signature,
)
from src.devex.lsp.diagnostics import AnalysisResult, line_changed_since_snapshot
from src.devex.lsp.signature_context import (
    _active_call_callee_index as _active_call_callee_index,
)
from src.devex.lsp.signature_context import (
    _active_parameter_from_tokens,
    _call_site,
    _count_active_parameter,
    _find_call_context,
    _tokens_for_position,
)
from src.devex.lsp.signature_items import (
    _signature_from_function_decl,
    _signature_from_method_decl,
    _signature_from_param_list,
)
from src.devex.lsp.text_coordinates import source_position
from src.devex.lsp.utils import resolve_chain

_ACCESS_VALUES = frozenset({".", "->", "?."})


def get_signature_help(
    result: AnalysisResult,
    position: lsp.Position,
) -> lsp.SignatureHelp | None:
    """Compute signature help from lexical call structure, then semantic types."""
    if not result.source:
        return None
    position = source_position(result.source, position)
    class_table = result.analyzed.class_table if result.analyzed else {}
    function_table = result.analyzed.function_table if result.analyzed else {}
    tokens = _tokens_for_position(result, position)
    site = _call_site(tokens, position)
    if site is not None:
        open_index, callee_index = site
        active_param = _active_parameter_from_tokens(tokens, open_index, position)
        return _resolve_token_call(
            result,
            tokens,
            callee_index,
            class_table,
            function_table,
            active_param,
        )

    # A complete snapshot proves that the caret is not in code-call syntax.
    # Only changed live lines or degraded tokenless results need text fallback.
    if tokens is not None and not line_changed_since_snapshot(result, position.line):
        return None
    context = _find_call_context(result.source, position)
    if context is None:
        return None
    return _resolve_raw_call(
        context,
        class_table,
        function_table,
        _count_active_parameter(result.source, position),
    )


def _resolve_token_call(
    result: AnalysisResult,
    tokens: list[Token],
    callee_index: int,
    class_table: dict[str, ClassInfo],
    function_table: dict[str, FunctionDecl],
    active_param: int,
) -> lsp.SignatureHelp | None:
    callee = tokens[callee_index]
    if callee_index >= 2 and tokens[callee_index - 1].value in _ACCESS_VALUES:
        return _resolve_member_call(
            result,
            tokens,
            callee_index - 2,
            callee.value,
            class_table,
            active_param,
        )
    if callee_index >= 1 and tokens[callee_index - 1].value == "new":
        return _resolve_constructor(callee.value, class_table, active_param)
    return _resolve_plain_call(callee.value, class_table, function_table, active_param)


def _resolve_raw_call(
    context: str,
    class_table: dict[str, ClassInfo],
    function_table: dict[str, FunctionDecl],
    active_param: int,
) -> lsp.SignatureHelp | None:
    new_match = re.fullmatch(r"new\s+(\w+)", context)
    if new_match:
        return _resolve_constructor(new_match.group(1), class_table, active_param)
    parts = re.split(r"(?:\.|->|\?\.)", context)
    if len(parts) == 2:
        receiver, method = parts
        if receiver in class_table:
            return _resolve_method_on_type(
                receiver,
                method,
                class_table,
                active_param,
                require_static=True,
            )
        params = get_stdlib_signature(receiver, method)
        if params is not None:
            return _signature_from_param_list(
                f"{receiver}.{method}",
                "",
                params,
                active_param,
                context=f"Static method of {receiver}",
            )
        return None
    return _resolve_plain_call(context, class_table, function_table, active_param)


def _resolve_plain_call(
    name: str,
    class_table: dict[str, ClassInfo],
    function_table: dict[str, FunctionDecl],
    active_param: int,
) -> lsp.SignatureHelp | None:
    if name in class_table:
        return _resolve_constructor(name, class_table, active_param)
    function = function_table.get(name)
    if function is not None:
        return _signature_from_function_decl(function, active_param)
    builtin = BUILTIN_FUNCTION_SIGNATURES.get(name)
    if builtin:
        return _signature_from_param_list(
            name,
            builtin[0],
            builtin[1],
            active_param,
            context="Built-in function",
        )
    return None


def _resolve_constructor(
    class_name: str,
    class_table: dict[str, ClassInfo],
    active_param: int,
) -> lsp.SignatureHelp | None:
    info = class_table.get(class_name)
    if info is None:
        return None
    if isinstance(info.constructor, MethodDecl):
        return _signature_from_method_decl(
            class_name,
            info.constructor,
            active_param,
            is_constructor=True,
        )
    return _signature_from_param_list(
        class_name,
        class_name,
        [],
        active_param,
        context=f"Constructor of {class_name}",
    )


def _resolve_member_call(
    result: AnalysisResult,
    tokens: list[Token],
    receiver_end_idx: int,
    method_name: str,
    class_table: dict[str, ClassInfo],
    active_param: int,
) -> lsp.SignatureHelp | None:
    receiver = resolve_chain(result, tokens, receiver_end_idx, class_table)
    if receiver is not None:
        signature = _resolve_method_on_type(
            receiver.type_name,
            method_name,
            class_table,
            active_param,
            require_static=receiver.direct_type_reference,
        )
        if signature is not None:
            return signature
        if receiver.direct_type_reference and receiver.type_name in class_table:
            return None

    receiver_name = _simple_receiver_name(tokens, receiver_end_idx)
    if receiver_name is None or receiver_name in class_table:
        return None
    params = get_stdlib_signature(receiver_name, method_name)
    if params is None:
        return None
    return _signature_from_param_list(
        f"{receiver_name}.{method_name}",
        "",
        params,
        active_param,
        context=f"Static method of {receiver_name}",
    )


def _simple_receiver_name(tokens: list[Token], index: int) -> str | None:
    if index < 0 or index >= len(tokens) or tokens[index].value == ")":
        return None
    if index >= 2 and tokens[index - 1].value in _ACCESS_VALUES:
        return None
    return tokens[index].value


def _resolve_method_on_type(
    type_name: str,
    method_name: str,
    class_table: dict[str, ClassInfo],
    active_param: int,
    *,
    require_static: bool = False,
) -> lsp.SignatureHelp | None:
    current = type_name
    while current and current in class_table:
        info = class_table[current]
        method = info.methods.get(method_name)
        if isinstance(method, MethodDecl):
            if (method.access == "class") != require_static:
                return None
            return _signature_from_method_decl(current, method, active_param)
        current = info.parent

    if not require_static:
        params = get_signature_params(type_name, method_name)
        if params is not None:
            return _signature_from_param_list(
                f"{type_name}.{method_name}",
                "",
                params,
                active_param,
                context=f"Built-in {type_name} method",
            )
    return None
