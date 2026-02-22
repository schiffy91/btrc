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

from src.compiler.python.analyzer import ClassInfo
from src.compiler.python.ast_nodes import (
    FunctionDecl, MethodDecl, FieldDecl, Param, TypeExpr,
    ClassDecl, VarDeclStmt,
)

from devex.lsp.diagnostics import AnalysisResult


# ---------------------------------------------------------------------------
# Built-in method signatures: (method_name, [(param_type, param_name), ...])
# ---------------------------------------------------------------------------

_STRING_SIGNATURES: dict[str, list[tuple[str, str]]] = {
    "charAt":      [("int", "index")],
    "trim":        [],
    "lstrip":      [],
    "rstrip":      [],
    "toUpper":     [],
    "toLower":     [],
    "contains":    [("string", "sub")],
    "startsWith":  [("string", "prefix")],
    "endsWith":    [("string", "suffix")],
    "indexOf":     [("string", "sub")],
    "lastIndexOf": [("string", "sub")],
    "substring":   [("int", "start"), ("int", "end")],
    "equals":      [("string", "other")],
    "split":       [("string", "delim")],
    "replace":     [("string", "old"), ("string", "replacement")],
    "repeat":      [("int", "count")],
    "count":       [("string", "sub")],
    "find":        [("string", "sub"), ("int", "start")],
    "capitalize":  [],
    "title":       [],
    "swapCase":    [],
    "padLeft":     [("int", "width"), ("char", "fill")],
    "padRight":    [("int", "width"), ("char", "fill")],
    "center":      [("int", "width"), ("char", "fill")],
    "charLen":     [],
    "byteLen":     [],
    "isDigitStr":  [],
    "isAlphaStr":  [],
    "isBlank":     [],
    "isAlnum":     [],
    "isUpper":     [],
    "isLower":     [],
    "reverse":     [],
    "isEmpty":     [],
    "removePrefix": [("string", "prefix")],
    "removeSuffix": [("string", "suffix")],
    "toInt":       [],
    "toFloat":     [],
    "toDouble":    [],
    "toLong":      [],
    "toBool":      [],
    "zfill":       [("int", "width")],
}

_LIST_SIGNATURES: dict[str, list[tuple[str, str]]] = {
    "push":        [("T", "value")],
    "get":         [("int", "index")],
    "set":         [("int", "index"), ("T", "value")],
    "remove":      [("int", "index")],
    "pop":         [],
    "reverse":     [],
    "sort":        [],
    "contains":    [("T", "value")],
    "indexOf":     [("T", "value")],
    "lastIndexOf": [("T", "value")],
    "slice":       [("int", "start"), ("int", "end")],
    "join":        [("string", "separator")],
    "joinToString": [("string", "separator")],
    "forEach":     [("fn", "callback")],
    "filter":      [("fn", "predicate")],
    "any":         [("fn", "predicate")],
    "all":         [("fn", "predicate")],
    "clear":       [],
    "size":        [],
    "isEmpty":     [],
    "map":         [("fn", "transform")],
    "extend":      [("List<T>", "other")],
    "insert":      [("int", "index"), ("T", "value")],
    "first":       [],
    "last":        [],
    "reduce":      [("T", "init"), ("fn", "accumulator")],
    "fill":        [("T", "value")],
    "count":       [("T", "value")],
    "removeAll":   [("T", "value")],
    "swap":        [("int", "i"), ("int", "j")],
    "min":         [],
    "max":         [],
    "sum":         [],
    "sorted":      [],
    "distinct":    [],
    "reversed":    [],
    "addAll":      [("List<T>", "other")],
    "subList":     [("int", "start"), ("int", "end")],
    "findIndex":   [("fn", "predicate")],
    "take":        [("int", "n")],
    "drop":        [("int", "n")],
    "removeAt":    [("int", "index")],
    "free":        [],
}

_MAP_SIGNATURES: dict[str, list[tuple[str, str]]] = {
    "put":      [("K", "key"), ("V", "value")],
    "get":      [("K", "key")],
    "getOrDefault": [("K", "key"), ("V", "fallback")],
    "has":      [("K", "key")],
    "contains": [("K", "key")],
    "keys":     [],
    "values":   [],
    "remove":   [("K", "key")],
    "clear":    [],
    "forEach":  [("fn", "callback")],
    "size":     [],
    "isEmpty":  [],
    "putIfAbsent": [("K", "key"), ("V", "value")],
    "containsValue": [("V", "value")],
    "merge":    [("Map<K,V>", "other")],
    "free":     [],
}

_SET_SIGNATURES: dict[str, list[tuple[str, str]]] = {
    "add":      [("T", "value")],
    "contains": [("T", "value")],
    "has":      [("T", "value")],
    "remove":   [("T", "value")],
    "toList":   [],
    "clear":    [],
    "forEach":  [("fn", "callback")],
    "filter":   [("fn", "predicate")],
    "any":      [("fn", "predicate")],
    "all":      [("fn", "predicate")],
    "size":     [],
    "isEmpty":  [],
    "unite":        [("Set<T>", "other")],
    "intersect":    [("Set<T>", "other")],
    "subtract":     [("Set<T>", "other")],
    "symmetricDifference": [("Set<T>", "other")],
    "isSubsetOf":   [("Set<T>", "other")],
    "isSupersetOf": [("Set<T>", "other")],
    "copy":         [],
    "free":     [],
}


# ---------------------------------------------------------------------------
# Stdlib static method signatures
# ---------------------------------------------------------------------------

_STDLIB_SIGNATURES: dict[str, dict[str, list[tuple[str, str]]]] = {
    "Math": {
        "PI":        [],
        "E":         [],
        "TAU":       [],
        "INF":       [],
        "abs":       [("int", "x")],
        "fabs":      [("float", "x")],
        "max":       [("int", "a"), ("int", "b")],
        "min":       [("int", "a"), ("int", "b")],
        "fmax":      [("float", "a"), ("float", "b")],
        "fmin":      [("float", "a"), ("float", "b")],
        "clamp":     [("int", "x"), ("int", "lo"), ("int", "hi")],
        "power":     [("float", "base"), ("int", "exp")],
        "sqrt":      [("float", "x")],
        "factorial": [("int", "n")],
        "gcd":       [("int", "a"), ("int", "b")],
        "lcm":       [("int", "a"), ("int", "b")],
        "fibonacci": [("int", "n")],
        "isPrime":   [("int", "n")],
        "isEven":    [("int", "n")],
        "isOdd":     [("int", "n")],
        "sum":       [("List<int>", "items")],
        "fsum":      [("List<float>", "items")],
        "sin":       [("float", "x")],
        "cos":       [("float", "x")],
        "tan":       [("float", "x")],
        "asin":      [("float", "x")],
        "acos":      [("float", "x")],
        "atan":      [("float", "x")],
        "atan2":     [("float", "y"), ("float", "x")],
        "ceil":      [("float", "x")],
        "floor":     [("float", "x")],
        "round":     [("float", "x")],
        "truncate":  [("float", "x")],
        "log":       [("float", "x")],
        "log10":     [("float", "x")],
        "log2":      [("float", "x")],
        "exp":       [("float", "x")],
        "toRadians": [("float", "degrees")],
        "toDegrees": [("float", "radians")],
        "fclamp":    [("float", "val"), ("float", "lo"), ("float", "hi")],
        "sign":      [("int", "x")],
        "fsign":     [("float", "x")],
    },
    "Strings": {
        "repeat":     [("string", "s"), ("int", "count")],
        "join":       [("List<string>", "items"), ("string", "sep")],
        "replace":    [("string", "s"), ("string", "old"), ("string", "replacement")],
        "isDigit":    [("char", "c")],
        "isAlpha":    [("char", "c")],
        "isAlnum":    [("char", "c")],
        "isSpace":    [("char", "c")],
        "toInt":      [("string", "s")],
        "toFloat":    [("string", "s")],
        "count":      [("string", "s"), ("string", "sub")],
        "find":       [("string", "s"), ("string", "sub"), ("int", "start")],
        "rfind":      [("string", "s"), ("string", "sub")],
        "capitalize": [("string", "s")],
        "title":      [("string", "s")],
        "swapCase":   [("string", "s")],
        "padLeft":    [("string", "s"), ("int", "width"), ("char", "fill")],
        "padRight":   [("string", "s"), ("int", "width"), ("char", "fill")],
        "center":     [("string", "s"), ("int", "width"), ("char", "fill")],
        "lstrip":     [("string", "s")],
        "rstrip":     [("string", "s")],
        "fromInt":    [("int", "n")],
        "fromFloat":  [("float", "f")],
        "isDigitStr": [("string", "s")],
        "isAlphaStr": [("string", "s")],
        "isBlank":    [("string", "s")],
    },
    "Path": {
        "exists":   [("string", "path")],
        "readAll":  [("string", "path")],
        "writeAll": [("string", "path"), ("string", "content")],
    },
}

# Built-in free functions
_BUILTIN_FUNCTION_SIGNATURES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "println":   ("void", [("string", "message")]),
    "print":     ("void", [("string", "message")]),
    "input":     ("string", [("string", "prompt")]),
    "toString":  ("string", [("int", "value")]),
    "toInt":     ("int", [("string", "value")]),
    "toFloat":   ("float", [("string", "value")]),
    "len":       ("int", [("string", "s")]),
    "range":     ("List<int>", [("int", "n")]),
    "exit":      ("void", [("int", "code")]),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _type_repr(type_expr: Optional[TypeExpr]) -> str:
    """Format a TypeExpr as a string."""
    if type_expr is None:
        return "void"
    return repr(type_expr)


def _get_text_before_cursor(source: str, position: lsp.Position) -> str:
    """Get the text on the current line before the cursor."""
    lines = source.split('\n')
    if 0 <= position.line < len(lines):
        return lines[position.line][:position.character]
    return ""


def _count_active_parameter(source: str, position: lsp.Position) -> int:
    """Count the number of commas at the current nesting level before the cursor.

    This determines which parameter is currently being typed. We scan backwards
    from the cursor to find the matching open parenthesis, counting commas at
    the same nesting depth.
    """
    lines = source.split('\n')
    if position.line < 0 or position.line >= len(lines):
        return 0

    # Build the text from the start of the file up to cursor
    full_text_before = '\n'.join(lines[:position.line]) + '\n' + lines[position.line][:position.character]

    # Walk backward from the cursor to find the matching '('
    depth = 0
    commas = 0
    in_string = False
    string_char = None

    i = len(full_text_before) - 1
    while i >= 0:
        ch = full_text_before[i]

        # Handle string literals (skip their contents)
        if in_string:
            if ch == string_char and (i == 0 or full_text_before[i - 1] != '\\'):
                in_string = False
            i -= 1
            continue

        if ch in ('"', "'"):
            in_string = True
            string_char = ch
            i -= 1
            continue

        if ch == ')':
            depth += 1
        elif ch == '(':
            if depth == 0:
                # Found the matching open paren
                return commas
            depth -= 1
        elif ch == ',' and depth == 0:
            commas += 1

        i -= 1

    return commas


def _find_call_context(source: str, position: lsp.Position) -> Optional[str]:
    """Find the function/method name for the call surrounding the cursor.

    Scans backward from the cursor to find the matching '(' and then reads
    the identifier(s) preceding it (handling patterns like `func(`, `obj.method(`,
    `ClassName(`, `ClassName.method(`).

    Returns the raw text before the '(' (e.g. "obj.method", "func", "ClassName").
    """
    lines = source.split('\n')
    if position.line < 0 or position.line >= len(lines):
        return None

    full_text_before = '\n'.join(lines[:position.line]) + '\n' + lines[position.line][:position.character]

    # Walk backward to find the matching '('
    depth = 0
    in_string = False
    string_char = None

    i = len(full_text_before) - 1
    while i >= 0:
        ch = full_text_before[i]

        if in_string:
            if ch == string_char and (i == 0 or full_text_before[i - 1] != '\\'):
                in_string = False
            i -= 1
            continue

        if ch in ('"', "'"):
            in_string = True
            string_char = ch
            i -= 1
            continue

        if ch == ')':
            depth += 1
        elif ch == '(':
            if depth == 0:
                # Found the matching paren — extract the identifier(s) before it
                text_before_paren = full_text_before[:i].rstrip()
                # Match patterns: ident, ident.ident, new ident, ident?.ident, ident->ident
                m = re.search(r'((?:new\s+)?[\w]+(?:(?:\.|->|\?\.)[\w]+)?)\s*$', text_before_paren)
                if m:
                    return m.group(1).strip()
                return None
            depth -= 1

        i -= 1

    return None


def _make_param_info(ptype: str, pname: str) -> lsp.ParameterInformation:
    """Create an LSP ParameterInformation from a type string and name."""
    return lsp.ParameterInformation(
        label=f"{ptype} {pname}",
        documentation=None,
    )


def _make_signature(
    label: str,
    params: list[lsp.ParameterInformation],
    active_param: int,
    documentation: Optional[str] = None,
) -> lsp.SignatureHelp:
    """Build a SignatureHelp response with a single signature."""
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
    """Build a SignatureHelp from a list of (type, name) tuples."""
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
    """Build a SignatureHelp from a FunctionDecl AST node."""
    param_list = [(_type_repr(p.type), p.name) for p in decl.params]
    ret = _type_repr(decl.return_type)
    return _signature_from_param_list(decl.name, ret, param_list, active_param)


def _signature_from_method_decl(
    class_name: str,
    mdecl: MethodDecl,
    active_param: int,
    is_constructor: bool = False,
) -> lsp.SignatureHelp:
    """Build a SignatureHelp from a MethodDecl AST node."""
    param_list = [(_type_repr(p.type), p.name) for p in mdecl.params]
    if is_constructor:
        ret = class_name
        label_name = class_name
    else:
        ret = _type_repr(mdecl.return_type)
        label_name = mdecl.name
    context = f"Method of {class_name}" if not is_constructor else f"Constructor of {class_name}"
    return _signature_from_param_list(label_name, ret, param_list, active_param, context=context)


# ---------------------------------------------------------------------------
# Variable type resolution (for obj.method() patterns)
# ---------------------------------------------------------------------------

def _resolve_variable_type(
    result: AnalysisResult,
    var_name: str,
    cursor_line: int,
) -> Optional[str]:
    """Try to resolve the base type of a variable by scanning the AST.

    Returns the base type string (e.g. "string", "List", "MyClass") or None.
    """
    if not result.ast:
        return None

    if var_name == "self":
        return _find_enclosing_class(result, cursor_line)

    target_line = cursor_line + 1  # AST uses 1-based lines

    for decl in result.ast.declarations:
        found = _search_for_var_type(decl, var_name, target_line)
        if found is not None:
            return found.base
    return None


def _find_enclosing_class(result: AnalysisResult, cursor_line: int) -> Optional[str]:
    """Find the class enclosing the given 0-based cursor line."""
    if not result.ast:
        return None

    source_lines = result.source.split('\n')
    for decl in result.ast.declarations:
        if isinstance(decl, ClassDecl):
            class_start = decl.line - 1  # to 0-based
            class_end = _find_closing_brace_line(source_lines, class_start)
            if class_end is not None and class_start <= cursor_line <= class_end:
                return decl.name
    return None


def _find_closing_brace_line(source_lines: list[str], start_line: int) -> Optional[int]:
    """Find the line of the closing brace matching the first opening brace."""
    depth = 0
    found_open = False
    for i in range(start_line, len(source_lines)):
        for ch in source_lines[i]:
            if ch == '{':
                depth += 1
                found_open = True
            elif ch == '}':
                depth -= 1
                if found_open and depth == 0:
                    return i
    return None


def _search_for_var_type(node, var_name: str, before_line: int) -> Optional[TypeExpr]:
    """Recursively search for a VarDeclStmt or Param declaring var_name."""
    if isinstance(node, VarDeclStmt):
        if node.name == var_name and node.line <= before_line and node.type is not None:
            return node.type
        return None

    if isinstance(node, Param):
        if node.name == var_name and node.type is not None:
            return node.type
        return None

    if isinstance(node, FunctionDecl):
        for p in node.params:
            if p.name == var_name and p.type is not None:
                return p.type
        if node.body:
            return _search_block(node.body, var_name, before_line)
        return None

    if isinstance(node, MethodDecl):
        for p in node.params:
            if p.name == var_name and p.type is not None:
                return p.type
        if node.body:
            return _search_block(node.body, var_name, before_line)
        return None

    if isinstance(node, ClassDecl):
        for member in node.members:
            if isinstance(member, FieldDecl):
                if member.name == var_name and member.type is not None:
                    return member.type
            elif isinstance(member, MethodDecl):
                result = _search_for_var_type(member, var_name, before_line)
                if result is not None:
                    return result
        return None

    return None


def _search_block(block, var_name: str, before_line: int) -> Optional[TypeExpr]:
    """Search a Block's statements for a VarDeclStmt."""
    if block is None or not hasattr(block, 'statements'):
        return None
    best: Optional[TypeExpr] = None
    for stmt in block.statements:
        if isinstance(stmt, VarDeclStmt):
            if stmt.name == var_name and stmt.line <= before_line and stmt.type is not None:
                best = stmt.type
        for attr in ('body', 'then_block', 'else_block', 'try_block', 'catch_block'):
            child = getattr(stmt, attr, None)
            if child is not None:
                found = _search_block(child, var_name, before_line)
                if found is not None:
                    best = found
    return best


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def get_signature_help(
    result: AnalysisResult,
    position: lsp.Position,
) -> Optional[lsp.SignatureHelp]:
    """Compute signature help for the given cursor position.

    Returns a SignatureHelp response if the cursor is inside a function call,
    or None if no signature information is available.
    """
    if not result.source:
        return None

    # Determine which function/method call the cursor is inside
    call_context = _find_call_context(result.source, position)
    if not call_context:
        return None

    # Count commas to determine the active parameter index
    active_param = _count_active_parameter(result.source, position)

    class_table = result.analyzed.class_table if result.analyzed else {}
    function_table = result.analyzed.function_table if result.analyzed else {}

    # Parse the call context into parts
    # Patterns: "func", "obj.method", "ClassName.method", "new ClassName",
    #           "obj?.method", "obj->method"
    call_context_clean = call_context

    # Handle "new ClassName" -> treat as constructor
    new_match = re.match(r'^new\s+(\w+)$', call_context_clean)
    if new_match:
        class_name = new_match.group(1)
        return _resolve_constructor(class_name, class_table, active_param)

    # Handle "obj.method", "obj?.method", "obj->method"
    member_match = re.match(r'^(\w+)(?:\.|->|\?\.)(\w+)$', call_context_clean)
    if member_match:
        obj_name = member_match.group(1)
        method_name = member_match.group(2)
        return _resolve_member_call(
            result, obj_name, method_name, position, class_table, active_param
        )

    # Handle plain function or constructor call: "func" or "ClassName"
    func_name = call_context_clean.strip()

    # Check if it's a class constructor: ClassName(...)
    if func_name in class_table:
        return _resolve_constructor(func_name, class_table, active_param)

    # Check user-defined free functions
    if func_name in function_table:
        return _signature_from_function_decl(function_table[func_name], active_param)

    # Check built-in functions
    if func_name in _BUILTIN_FUNCTION_SIGNATURES:
        ret, params = _BUILTIN_FUNCTION_SIGNATURES[func_name]
        return _signature_from_param_list(func_name, ret, params, active_param,
                                          context="Built-in function")

    return None


def _resolve_constructor(
    class_name: str,
    class_table: dict[str, ClassInfo],
    active_param: int,
) -> Optional[lsp.SignatureHelp]:
    """Resolve signature for a constructor call."""
    if class_name not in class_table:
        return None
    info = class_table[class_name]
    if info.constructor and isinstance(info.constructor, MethodDecl):
        return _signature_from_method_decl(
            class_name, info.constructor, active_param, is_constructor=True
        )
    # No explicit constructor — show empty params
    return _signature_from_param_list(class_name, class_name, [], active_param,
                                      context=f"Constructor of {class_name}")


def _resolve_member_call(
    result: AnalysisResult,
    obj_name: str,
    method_name: str,
    position: lsp.Position,
    class_table: dict[str, ClassInfo],
    active_param: int,
) -> Optional[lsp.SignatureHelp]:
    """Resolve signature for a member method call (obj.method or Class.method)."""

    # 1. Check if obj_name is a class name (static method or constructor pattern)
    if obj_name in class_table:
        info = class_table[obj_name]
        if method_name in info.methods:
            mdecl = info.methods[method_name]
            if isinstance(mdecl, MethodDecl):
                return _signature_from_method_decl(obj_name, mdecl, active_param)

    # 2. Check stdlib static methods
    if obj_name in _STDLIB_SIGNATURES:
        stdlib_class = _STDLIB_SIGNATURES[obj_name]
        if method_name in stdlib_class:
            param_list = stdlib_class[method_name]
            return _signature_from_param_list(
                f"{obj_name}.{method_name}", "", param_list, active_param,
                context=f"Static method of {obj_name}",
            )

    # 3. Resolve the variable type and look up methods on that type
    var_type = _resolve_variable_type(result, obj_name, position.line)

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


def _resolve_method_on_type(
    type_base: str,
    method_name: str,
    class_table: dict[str, ClassInfo],
    active_param: int,
) -> Optional[lsp.SignatureHelp]:
    """Resolve a method signature given a base type name."""

    # Built-in string methods
    if type_base == "string" and method_name in _STRING_SIGNATURES:
        params = _STRING_SIGNATURES[method_name]
        return _signature_from_param_list(
            f"string.{method_name}", "", params, active_param,
            context="Built-in string method",
        )

    # Built-in List methods
    if type_base == "List" and method_name in _LIST_SIGNATURES:
        params = _LIST_SIGNATURES[method_name]
        return _signature_from_param_list(
            f"List.{method_name}", "", params, active_param,
            context="Built-in List method",
        )

    # Built-in Map methods
    if type_base == "Map" and method_name in _MAP_SIGNATURES:
        params = _MAP_SIGNATURES[method_name]
        return _signature_from_param_list(
            f"Map.{method_name}", "", params, active_param,
            context="Built-in Map method",
        )

    # Built-in Set methods
    if type_base == "Set" and method_name in _SET_SIGNATURES:
        params = _SET_SIGNATURES[method_name]
        return _signature_from_param_list(
            f"Set.{method_name}", "", params, active_param,
            context="Built-in Set method",
        )

    # User-defined class methods
    if type_base in class_table:
        info = class_table[type_base]
        if method_name in info.methods:
            mdecl = info.methods[method_name]
            if isinstance(mdecl, MethodDecl):
                return _signature_from_method_decl(type_base, mdecl, active_param)

        # Check parent chain
        cinfo = info
        while cinfo and cinfo.parent and cinfo.parent in class_table:
            parent = class_table[cinfo.parent]
            if method_name in parent.methods:
                mdecl = parent.methods[method_name]
                if isinstance(mdecl, MethodDecl):
                    return _signature_from_method_decl(cinfo.parent, mdecl, active_param)
            cinfo = parent

    return None
