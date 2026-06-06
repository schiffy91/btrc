"""Signature help provider for btrc.

Shows function/method parameter hints when the user types '(' or ','.
Supports:
- Free functions (from the analyzer's function_table)
- Class constructors (ClassName(...))
- Instance methods (obj.method(...))
- Static/class methods (ClassName.method(...))
- Built-in methods on string, List<T>, Map<K,V>, and Set<T>
- Stdlib static methods (Math, Strings, Path)
- Active parameter highlighting based on comma count before cursor
"""

import re

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import (
    FunctionDecl,
    MethodDecl,
)
from src.devex.lsp.builtins import (
    BUILTIN_FUNCTION_SIGNATURES,
    get_signature_params,
    get_stdlib_signature,
)
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.utils import (
    document_position_to_resolved,
    resolve_chain_type,
    type_repr,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_active_parameter(source: str, position: lsp.Position) -> int:
    """Count commas at the current nesting level before the cursor."""
    lines = source.split("\n")
    if position.line < 0 or position.line >= len(lines):
        return 0

    full_text_before = "\n".join(lines[: position.line]) + "\n" + lines[position.line][: position.character]

    depth = 0
    commas = 0
    in_string = False
    string_char = None

    i = len(full_text_before) - 1
    while i >= 0:
        ch = full_text_before[i]
        if in_string:
            if ch == string_char and (i == 0 or full_text_before[i - 1] != "\\"):
                in_string = False
            i -= 1
            continue
        if ch in ('"', "'"):
            in_string = True
            string_char = ch
            i -= 1
            continue
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                return commas
            depth -= 1
        elif ch == "," and depth == 0:
            commas += 1
        i -= 1

    return commas


def _find_call_context(source: str, position: lsp.Position) -> str | None:
    """Find the function/method name for the call surrounding the cursor."""
    lines = source.split("\n")
    if position.line < 0 or position.line >= len(lines):
        return None

    full_text_before = "\n".join(lines[: position.line]) + "\n" + lines[position.line][: position.character]

    depth = 0
    in_string = False
    string_char = None

    i = len(full_text_before) - 1
    while i >= 0:
        ch = full_text_before[i]
        if in_string:
            if ch == string_char and (i == 0 or full_text_before[i - 1] != "\\"):
                in_string = False
            i -= 1
            continue
        if ch in ('"', "'"):
            in_string = True
            string_char = ch
            i -= 1
            continue
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                text_before_paren = full_text_before[:i].rstrip()
                m = re.search(r"((?:new\s+)?[\w]+(?:(?:\.|->|\?\.)[\w]+)?)\s*$", text_before_paren)
                if m:
                    return m.group(1).strip()
                return None
            depth -= 1
        i -= 1

    return None


def _before_or_at(line: int, col: int, position: lsp.Position) -> bool:
    token_line = line - 1
    token_col = col - 1
    if token_line < position.line:
        return True
    return token_line == position.line and token_col < position.character


def _active_call_callee_index(result: AnalysisResult, position: lsp.Position) -> int | None:
    if not result.tokens:
        return None
    resolved = document_position_to_resolved(result, position)
    stack: list[int] = []
    for index, token in enumerate(result.tokens):
        if not _before_or_at(token.line, token.col, resolved):
            break
        if token.value == "(":
            stack.append(index)
        elif token.value == ")" and stack:
            stack.pop()
    if not stack:
        return None
    callee_index = stack[-1] - 1
    return callee_index if callee_index >= 0 else None


def _simple_receiver_name(tokens, end_idx: int) -> str | None:
    if end_idx < 0 or end_idx >= len(tokens):
        return None
    token = tokens[end_idx]
    if token.value == ")":
        return None
    if end_idx >= 2 and tokens[end_idx - 1].value in (".", "->", "?."):
        return None
    return token.value


def _make_param_info(ptype: str, pname: str) -> lsp.ParameterInformation:
    return lsp.ParameterInformation(label=f"{ptype} {pname}", documentation=None)


def _make_signature(
    label: str,
    params: list[lsp.ParameterInformation],
    active_param: int,
    documentation: str | None = None,
) -> lsp.SignatureHelp:
    sig = lsp.SignatureInformation(
        label=label,
        parameters=params,
        documentation=documentation,
        active_parameter=min(active_param, max(0, len(params) - 1)) if params else 0,
    )
    return lsp.SignatureHelp(
        signatures=[sig],
        active_signature=0,
        active_parameter=min(active_param, max(0, len(params) - 1)) if params else 0,
    )


def _signature_from_param_list(
    func_name: str,
    return_type: str,
    param_list: list[tuple[str, str]],
    active_param: int,
    context: str | None = None,
) -> lsp.SignatureHelp:
    params_str = ", ".join(f"{pt} {pn}" for pt, pn in param_list)
    label = f"{func_name}({params_str})"
    if return_type and return_type != "void":
        label = f"{return_type} {label}"
    param_infos = [_make_param_info(pt, pn) for pt, pn in param_list]
    return _make_signature(label, param_infos, active_param, documentation=context)


def _signature_from_function_decl(
    decl: FunctionDecl,
    active_param: int,
) -> lsp.SignatureHelp:
    param_list = [(type_repr(p.type), p.name) for p in decl.params]
    ret = type_repr(decl.return_type)
    return _signature_from_param_list(decl.name, ret, param_list, active_param)


def _signature_from_method_decl(
    class_name: str,
    mdecl: MethodDecl,
    active_param: int,
    is_constructor: bool = False,
) -> lsp.SignatureHelp:
    param_list = [(type_repr(p.type), p.name) for p in mdecl.params]
    if is_constructor:
        ret = class_name
        label_name = class_name
    else:
        ret = type_repr(mdecl.return_type)
        label_name = mdecl.name
    context = f"Method of {class_name}" if not is_constructor else f"Constructor of {class_name}"
    return _signature_from_param_list(label_name, ret, param_list, active_param, context=context)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def get_signature_help(
    result: AnalysisResult,
    position: lsp.Position,
) -> lsp.SignatureHelp | None:
    """Compute signature help for the given cursor position."""
    if not result.source:
        return None

    call_context = _find_call_context(result.source, position)
    if not call_context:
        return None

    active_param = _count_active_parameter(result.source, position)

    class_table = result.analyzed.class_table if result.analyzed else {}
    function_table = result.analyzed.function_table if result.analyzed else {}

    call_context_clean = call_context

    # Handle "new ClassName" -> treat as constructor
    new_match = re.match(r"^new\s+(\w+)$", call_context_clean)
    if new_match:
        class_name = new_match.group(1)
        return _resolve_constructor(class_name, class_table, active_param)

    callee_index = _active_call_callee_index(result, position)
    if callee_index is not None and callee_index >= 2:
        tokens = result.tokens
        method_token = tokens[callee_index]
        access = tokens[callee_index - 1]
        if access.value in (".", "->", "?."):
            return _resolve_member_call(
                result,
                callee_index - 2,
                method_token.value,
                class_table,
                active_param,
            )

    # Handle plain function or constructor call
    func_name = call_context_clean.strip()

    if func_name in class_table:
        return _resolve_constructor(func_name, class_table, active_param)

    if func_name in function_table:
        return _signature_from_function_decl(function_table[func_name], active_param)

    if func_name in BUILTIN_FUNCTION_SIGNATURES:
        ret, params = BUILTIN_FUNCTION_SIGNATURES[func_name]
        return _signature_from_param_list(func_name, ret, params, active_param, context="Built-in function")

    return None


def _resolve_constructor(
    class_name: str,
    class_table: dict[str, ClassInfo],
    active_param: int,
) -> lsp.SignatureHelp | None:
    if class_name not in class_table:
        return None
    info = class_table[class_name]
    if info.constructor and isinstance(info.constructor, MethodDecl):
        return _signature_from_method_decl(class_name, info.constructor, active_param, is_constructor=True)
    return _signature_from_param_list(class_name, class_name, [], active_param, context=f"Constructor of {class_name}")


def _resolve_member_call(
    result: AnalysisResult,
    receiver_end_idx: int,
    method_name: str,
    class_table: dict[str, ClassInfo],
    active_param: int,
) -> lsp.SignatureHelp | None:
    tokens = result.tokens

    receiver_name = _simple_receiver_name(tokens, receiver_end_idx)
    if receiver_name is not None:
        stdlib_params = get_stdlib_signature(receiver_name, method_name)
        if stdlib_params is not None:
            return _signature_from_param_list(
                f"{receiver_name}.{method_name}",
                "",
                stdlib_params,
                active_param,
                context=f"Static method of {receiver_name}",
            )

    receiver_type = resolve_chain_type(result, tokens, receiver_end_idx, class_table)
    if receiver_type is None:
        return None
    return _resolve_method_on_type(receiver_type, method_name, class_table, active_param)


def _resolve_method_on_type(
    type_base: str,
    method_name: str,
    class_table: dict[str, ClassInfo],
    active_param: int,
) -> lsp.SignatureHelp | None:
    """Resolve a method signature given a base type name."""

    # Built-in type methods
    builtin_params = get_signature_params(type_base, method_name)
    if builtin_params is not None:
        return _signature_from_param_list(
            f"{type_base}.{method_name}",
            "",
            builtin_params,
            active_param,
            context=f"Built-in {type_base} method",
        )

    # User-defined class methods (walk inheritance chain)
    if type_base in class_table:
        info = class_table[type_base]
        if method_name in info.methods:
            mdecl = info.methods[method_name]
            if isinstance(mdecl, MethodDecl):
                return _signature_from_method_decl(type_base, mdecl, active_param)

        cinfo = info
        while cinfo and cinfo.parent and cinfo.parent in class_table:
            parent = class_table[cinfo.parent]
            if method_name in parent.methods:
                mdecl = parent.methods[method_name]
                if isinstance(mdecl, MethodDecl):
                    return _signature_from_method_decl(cinfo.parent, mdecl, active_param)
            cinfo = parent

    return None
