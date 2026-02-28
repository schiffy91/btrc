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
from typing import Optional

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import (
    FunctionDecl,
    MethodDecl,
)

from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.builtins import (
    get_signature_params,
    get_stdlib_signature,
    BUILTIN_FUNCTION_SIGNATURES,
)
from src.devex.lsp.utils import (
    type_repr,
    find_enclosing_class_from_source,
    resolve_variable_type,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_active_parameter(source: str, position: lsp.Position) -> int:
    """Count commas at the current nesting level before the cursor."""
    lines = source.split("\n")
    if position.line < 0 or position.line >= len(lines):
        return 0

    full_text_before = (
        "\n".join(lines[: position.line])
        + "\n"
        + lines[position.line][: position.character]
    )

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


def _find_call_context(source: str, position: lsp.Position) -> Optional[str]:
    """Find the function/method name for the call surrounding the cursor."""
    lines = source.split("\n")
    if position.line < 0 or position.line >= len(lines):
        return None

    full_text_before = (
        "\n".join(lines[: position.line])
        + "\n"
        + lines[position.line][: position.character]
    )

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
                m = re.search(
                    r"((?:new\s+)?[\w]+(?:(?:\.|->|\?\.)[\w]+)?)\s*$", text_before_paren
                )
                if m:
                    return m.group(1).strip()
                return None
            depth -= 1
        i -= 1

    return None


def _make_param_info(ptype: str, pname: str) -> lsp.ParameterInformation:
    return lsp.ParameterInformation(label=f"{ptype} {pname}", documentation=None)


def _make_signature(
    label: str,
    params: list[lsp.ParameterInformation],
    active_param: int,
    documentation: Optional[str] = None,
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
    context: Optional[str] = None,
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
    context = (
        f"Method of {class_name}"
        if not is_constructor
        else f"Constructor of {class_name}"
    )
    return _signature_from_param_list(
        label_name, ret, param_list, active_param, context=context
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def get_signature_help(
    result: AnalysisResult,
    position: lsp.Position,
) -> Optional[lsp.SignatureHelp]:
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

    # Handle "obj.method", "obj?.method", "obj->method"
    member_match = re.match(r"^(\w+)(?:\.|->|\?\.)(\w+)$", call_context_clean)
    if member_match:
        obj_name = member_match.group(1)
        method_name = member_match.group(2)
        return _resolve_member_call(
            result, obj_name, method_name, position, class_table, active_param
        )

    # Handle plain function or constructor call
    func_name = call_context_clean.strip()

    if func_name in class_table:
        return _resolve_constructor(func_name, class_table, active_param)

    if func_name in function_table:
        return _signature_from_function_decl(function_table[func_name], active_param)

    if func_name in BUILTIN_FUNCTION_SIGNATURES:
        ret, params = BUILTIN_FUNCTION_SIGNATURES[func_name]
        return _signature_from_param_list(
            func_name, ret, params, active_param, context="Built-in function"
        )

    return None


def _resolve_constructor(
    class_name: str,
    class_table: dict[str, ClassInfo],
    active_param: int,
) -> Optional[lsp.SignatureHelp]:
    if class_name not in class_table:
        return None
    info = class_table[class_name]
    if info.constructor and isinstance(info.constructor, MethodDecl):
        return _signature_from_method_decl(
            class_name, info.constructor, active_param, is_constructor=True
        )
    return _signature_from_param_list(
        class_name, class_name, [], active_param, context=f"Constructor of {class_name}"
    )


def _resolve_member_call(
    result: AnalysisResult,
    obj_name: str,
    method_name: str,
    position: lsp.Position,
    class_table: dict[str, ClassInfo],
    active_param: int,
) -> Optional[lsp.SignatureHelp]:
    """Resolve signature for a member method call."""

    # 1. Check if obj_name is a class name (static method)
    if obj_name in class_table:
        info = class_table[obj_name]
        if method_name in info.methods:
            mdecl = info.methods[method_name]
            if isinstance(mdecl, MethodDecl):
                return _signature_from_method_decl(obj_name, mdecl, active_param)

    # 2. Check stdlib static methods
    stdlib_params = get_stdlib_signature(obj_name, method_name)
    if stdlib_params is not None:
        return _signature_from_param_list(
            f"{obj_name}.{method_name}",
            "",
            stdlib_params,
            active_param,
            context=f"Static method of {obj_name}",
        )

    # 3. Resolve the variable type and look up methods on that type
    var_type = _resolve_var_type(result, obj_name, position.line)
    if var_type is not None:
        sig = _resolve_method_on_type(var_type, method_name, class_table, active_param)
        if sig:
            return sig

    # 4. Fallback: search all classes for a method with this name
    for cname, cinfo in class_table.items():
        if method_name in cinfo.methods:
            mdecl = cinfo.methods[method_name]
            if isinstance(mdecl, MethodDecl):
                return _signature_from_method_decl(cname, mdecl, active_param)

    return None


def _resolve_var_type(
    result: AnalysisResult,
    var_name: str,
    cursor_line: int,
) -> Optional[str]:
    """Resolve variable type, handling 'self' specially."""
    if not result.ast:
        return None
    if var_name == "self":
        return find_enclosing_class_from_source(result.ast, result.source, cursor_line)
    class_table = result.analyzed.class_table if result.analyzed else {}
    return resolve_variable_type(var_name, result.ast, class_table)


def _resolve_method_on_type(
    type_base: str,
    method_name: str,
    class_table: dict[str, ClassInfo],
    active_param: int,
) -> Optional[lsp.SignatureHelp]:
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
                    return _signature_from_method_decl(
                        cinfo.parent, mdecl, active_param
                    )
            cinfo = parent

    return None
