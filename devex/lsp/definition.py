"""Go-to-definition provider for btrc.

Supports jumping to definitions for:
- Class names (in declarations, constructor calls, type annotations, extends clauses)
- Method calls (obj.method() -> method definition in the class)
- Function calls (myFunction() -> function declaration)
- Field access (obj.field -> field declaration in the class)
"""

from __future__ import annotations
from typing import Optional

from lsprotocol import types as lsp

from src.compiler.python.tokens import Token, TokenType
from src.compiler.python.analyzer import ClassInfo
from src.compiler.python.ast_nodes import (
    ClassDecl, FunctionDecl, FieldDecl, MethodDecl,
    CallExpr, Identifier, NewExpr,
    VarDeclStmt, Program,
)

from devex.lsp.diagnostics import AnalysisResult


# ---------------------------------------------------------------------------
# Definition map building
# ---------------------------------------------------------------------------

class DefinitionMap:
    """Maps symbol names to their definition locations.

    Stores:
    - class_defs: class_name -> (line, col)
    - function_defs: function_name -> (line, col)
    - method_defs: (class_name, method_name) -> (line, col)
    - field_defs: (class_name, field_name) -> (line, col)
    """

    def __init__(self):
        self.class_defs: dict[str, tuple[int, int]] = {}
        self.function_defs: dict[str, tuple[int, int]] = {}
        self.method_defs: dict[tuple[str, str], tuple[int, int]] = {}
        self.field_defs: dict[tuple[str, str], tuple[int, int]] = {}

    @classmethod
    def from_ast(cls, ast: Program) -> DefinitionMap:
        """Walk the AST to build a definition map."""
        dmap = cls()
        for decl in ast.declarations:
            if isinstance(decl, ClassDecl):
                dmap.class_defs[decl.name] = (decl.line, decl.col)
                for member in decl.members:
                    if isinstance(member, FieldDecl):
                        dmap.field_defs[(decl.name, member.name)] = (member.line, member.col)
                    elif isinstance(member, MethodDecl):
                        dmap.method_defs[(decl.name, member.name)] = (member.line, member.col)
            elif isinstance(decl, FunctionDecl):
                dmap.function_defs[decl.name] = (decl.line, decl.col)
        return dmap


# ---------------------------------------------------------------------------
# Token lookup (reused from hover.py pattern)
# ---------------------------------------------------------------------------

def _find_token_at_position(tokens: list[Token], position: lsp.Position) -> Optional[Token]:
    """Find the token that covers the given 0-based LSP position."""
    target_line = position.line + 1   # btrc tokens use 1-based lines
    target_col = position.character + 1  # btrc tokens use 1-based cols

    for tok in tokens:
        if tok.type == TokenType.EOF:
            continue
        if tok.line != target_line:
            continue
        tok_end_col = tok.col + len(tok.value)
        if tok.col <= target_col <= tok_end_col:
            return tok
    return None


def _find_token_index(tokens: list[Token], token: Token) -> Optional[int]:
    """Find the index of a token in the token list (by identity)."""
    for i, t in enumerate(tokens):
        if t is token:
            return i
    return None


# ---------------------------------------------------------------------------
# Variable type resolution
# ---------------------------------------------------------------------------

def _resolve_variable_type(
    name: str,
    ast: Program,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Try to determine the class name for a variable by scanning the AST.

    Looks at VarDeclStmt nodes to find declarations like:
        var x = ClassName(...)          -> ClassName
        var x = new ClassName(...)      -> ClassName
        ClassName x = ...               -> ClassName
    """
    # Walk all statements in all function/method bodies looking for VarDeclStmt
    for decl in ast.declarations:
        result = _scan_for_var_type(name, decl, class_table)
        if result:
            return result
    return None


def _scan_for_var_type(
    var_name: str,
    node,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Recursively scan AST nodes for a VarDeclStmt that declares var_name."""
    if isinstance(node, VarDeclStmt):
        if node.name == var_name:
            # Check explicit type annotation
            if node.type and node.type.base in class_table:
                return node.type.base
            # Check initializer for constructor call: ClassName(...)
            if isinstance(node.initializer, CallExpr):
                callee = node.initializer.callee
                if isinstance(callee, Identifier) and callee.name in class_table:
                    return callee.name
            # Check initializer for new ClassName(...)
            if isinstance(node.initializer, NewExpr):
                if node.initializer.type and node.initializer.type.base in class_table:
                    return node.initializer.type.base
        return None

    # Recurse into container nodes that hold statements/members
    if isinstance(node, ClassDecl):
        for member in node.members:
            result = _scan_for_var_type(var_name, member, class_table)
            if result:
                return result
    elif isinstance(node, FunctionDecl):
        if node.body:
            for stmt in node.body.statements:
                result = _scan_for_var_type(var_name, stmt, class_table)
                if result:
                    return result
    elif isinstance(node, MethodDecl):
        if node.body:
            for stmt in node.body.statements:
                result = _scan_for_var_type(var_name, stmt, class_table)
                if result:
                    return result
    elif hasattr(node, 'then_block') or hasattr(node, 'body'):
        # IfStmt, WhileStmt, ForInStmt, etc.
        for attr_name in ('then_block', 'else_block', 'body', 'try_block', 'catch_block'):
            block = getattr(node, attr_name, None)
            if block and hasattr(block, 'statements'):
                for stmt in block.statements:
                    result = _scan_for_var_type(var_name, stmt, class_table)
                    if result:
                        return result

    return None


# ---------------------------------------------------------------------------
# Main go-to-definition logic
# ---------------------------------------------------------------------------

def _btrc_to_lsp_position(line: int, col: int) -> lsp.Position:
    """Convert 1-based btrc line/col to 0-based LSP position."""
    return lsp.Position(line=max(0, line - 1), character=max(0, col - 1))


def get_definition(
    result: AnalysisResult,
    position: lsp.Position,
) -> Optional[lsp.Location]:
    """Return the definition location for the symbol at the given position."""
    if not result.tokens or not result.ast:
        return None

    token = _find_token_at_position(result.tokens, position)
    if token is None:
        return None

    class_table = result.analyzed.class_table if result.analyzed else {}
    dmap = DefinitionMap.from_ast(result.ast)

    # 1. Check if the token itself is a class name (used as a type, constructor, extends, etc.)
    if token.value in dmap.class_defs:
        # Don't jump to ourselves -- if the cursor is on the class declaration itself, skip
        def_line, def_col = dmap.class_defs[token.value]
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col)

    # 2. Check if this is a member access: obj.field or obj.method
    if token.type == TokenType.IDENT:
        loc = _try_member_definition(result, token, class_table, dmap)
        if loc:
            return loc

    # 3. Check if this is a function call: myFunction(...)
    if token.value in dmap.function_defs:
        def_line, def_col = dmap.function_defs[token.value]
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col)

    return None


def _make_location(uri: str, line: int, col: int) -> lsp.Location:
    """Create an LSP Location from a btrc 1-based line/col."""
    pos = _btrc_to_lsp_position(line, col)
    return lsp.Location(
        uri=uri,
        range=lsp.Range(start=pos, end=pos),
    )


def _try_member_definition(
    result: AnalysisResult,
    token: Token,
    class_table: dict[str, ClassInfo],
    dmap: DefinitionMap,
) -> Optional[lsp.Location]:
    """Try to resolve a go-to-definition for a member access (obj.field / obj.method)."""
    if not result.tokens:
        return None

    token_idx = _find_token_index(result.tokens, token)
    if token_idx is None or token_idx < 2:
        return None

    # Check if preceded by a dot-like accessor
    prev = result.tokens[token_idx - 1]
    if prev.value not in ('.', '->', '?.'):
        return None

    obj_token = result.tokens[token_idx - 2]
    member_name = token.value

    # Determine which class the object belongs to
    target_class = _resolve_object_class(obj_token, result, class_table)

    if target_class is None:
        # Fallback: search all classes for a class that has this member
        for cname, cinfo in class_table.items():
            if member_name in cinfo.methods or member_name in cinfo.fields:
                target_class = cname
                break

    if target_class is None:
        return None

    # Check methods first, then fields
    key_method = (target_class, member_name)
    if key_method in dmap.method_defs:
        def_line, def_col = dmap.method_defs[key_method]
        return _make_location(result.uri, def_line, def_col)

    key_field = (target_class, member_name)
    if key_field in dmap.field_defs:
        def_line, def_col = dmap.field_defs[key_field]
        return _make_location(result.uri, def_line, def_col)

    # Check parent class chain for inherited members
    cinfo = class_table.get(target_class)
    while cinfo and cinfo.parent and cinfo.parent in class_table:
        parent_name = cinfo.parent
        key_method = (parent_name, member_name)
        if key_method in dmap.method_defs:
            def_line, def_col = dmap.method_defs[key_method]
            return _make_location(result.uri, def_line, def_col)
        key_field = (parent_name, member_name)
        if key_field in dmap.field_defs:
            def_line, def_col = dmap.field_defs[key_field]
            return _make_location(result.uri, def_line, def_col)
        cinfo = class_table[parent_name]

    return None


def _resolve_object_class(
    obj_token: Token,
    result: AnalysisResult,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Determine the class name of the object referenced by obj_token."""
    # Direct class name (for static methods: ClassName.method())
    if obj_token.value in class_table:
        return obj_token.value

    # "self" -> current class (find enclosing class from AST)
    if obj_token.value == "self":
        return _find_enclosing_class(result.ast, obj_token.line)

    # Try to resolve through variable declaration analysis
    if result.ast:
        return _resolve_variable_type(obj_token.value, result.ast, class_table)

    return None


def _find_enclosing_class(ast: Program, line: int) -> Optional[str]:
    """Find which class declaration encloses the given line number."""
    if not ast:
        return None
    for decl in ast.declarations:
        if isinstance(decl, ClassDecl):
            # A rough heuristic: if the line falls within the class body,
            # we consider it part of this class. We use the class line
            # as the start and scan members for the furthest line.
            if decl.line <= line:
                max_line = decl.line
                for member in decl.members:
                    if hasattr(member, 'line') and member.line > max_line:
                        max_line = member.line
                    # Also check body statements for methods
                    if isinstance(member, MethodDecl) and member.body:
                        for stmt in member.body.statements:
                            if hasattr(stmt, 'line') and stmt.line > max_line:
                                max_line = stmt.line
                if line <= max_line:
                    return decl.name
    return None
