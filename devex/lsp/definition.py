"""Go-to-definition provider for btrc.

Supports jumping to definitions for:
- Class names (in declarations, constructor calls, type annotations, extends clauses)
- Method calls (obj.method() -> method definition in the class)
- Function calls (myFunction() -> function declaration)
- Field access (obj.field -> field declaration in the class)
- Local variables (x -> its VarDeclStmt or for-loop header)
- Function/method parameters (param -> its Param node)
- Enum names, struct names, typedef aliases
- Properties on classes
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from lsprotocol import types as lsp

from src.compiler.python.tokens import Token, TokenType
from src.compiler.python.analyzer import ClassInfo
from src.compiler.python.ast_nodes import (
    Block,
    ClassDecl,
    FunctionDecl,
    FieldDecl,
    MethodDecl,
    PropertyDecl,
    StructDecl,
    EnumDecl,
    TypedefDecl,
    Param,
    CallExpr,
    Identifier,
    NewExpr,
    VarDeclStmt,
    ForInStmt,
    CForStmt,
    ParallelForStmt,
    TryCatchStmt,
    IfStmt,
    WhileStmt,
    DoWhileStmt,
    SwitchStmt,
    CaseClause,
    Program,
)

from devex.lsp.diagnostics import AnalysisResult


# ---------------------------------------------------------------------------
# Variable definition entry (scope-aware)
# ---------------------------------------------------------------------------

@dataclass
class VarDef:
    """A single variable-like definition with its scope context."""
    name: str
    line: int
    col: int
    # Scope boundaries: the line range of the enclosing function/method.
    # For top-level variables this would be (0, inf).
    scope_start: int  # 1-based line
    scope_end: int    # 1-based line (inclusive)


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
    - property_defs: (class_name, property_name) -> (line, col)
    - enum_defs: enum_name -> (line, col)
    - struct_defs: struct_name -> (line, col)
    - typedef_defs: alias_name -> (line, col)
    - var_defs: list of VarDef (local variables, parameters, loop vars, catch vars)
    """

    def __init__(self):
        self.class_defs: dict[str, tuple[int, int]] = {}
        self.function_defs: dict[str, tuple[int, int]] = {}
        self.method_defs: dict[tuple[str, str], tuple[int, int]] = {}
        self.field_defs: dict[tuple[str, str], tuple[int, int]] = {}
        self.property_defs: dict[tuple[str, str], tuple[int, int]] = {}
        self.enum_defs: dict[str, tuple[int, int]] = {}
        self.struct_defs: dict[str, tuple[int, int]] = {}
        self.typedef_defs: dict[str, tuple[int, int]] = {}
        self.var_defs: list[VarDef] = []

    @classmethod
    def from_ast(cls, ast: Program) -> DefinitionMap:
        """Walk the AST to build a definition map."""
        dmap = cls()
        for decl in ast.declarations:
            if isinstance(decl, ClassDecl):
                dmap.class_defs[decl.name] = (decl.line, decl.col)
                _collect_class_members(dmap, decl)
            elif isinstance(decl, FunctionDecl):
                dmap.function_defs[decl.name] = (decl.line, decl.col)
                scope_start, scope_end = _body_range(decl.body, decl.line)
                _collect_params(dmap, decl.params, scope_start, scope_end)
                if decl.body:
                    _collect_vars_in_block(dmap, decl.body, scope_start, scope_end)
            elif isinstance(decl, EnumDecl):
                dmap.enum_defs[decl.name] = (decl.line, decl.col)
            elif isinstance(decl, StructDecl):
                dmap.struct_defs[decl.name] = (decl.line, decl.col)
            elif isinstance(decl, TypedefDecl):
                dmap.typedef_defs[decl.alias] = (decl.line, decl.col)
        return dmap

    def find_var(self, name: str, cursor_line: int) -> Optional[tuple[int, int]]:
        """Find the closest variable definition for *name* visible at *cursor_line*.

        Returns the definition that:
        1. Has the same name
        2. Its scope encloses cursor_line
        3. Was declared at or before cursor_line
        4. Is the closest preceding declaration (innermost scope wins)
        """
        best: Optional[VarDef] = None
        for vd in self.var_defs:
            if vd.name != name:
                continue
            if not (vd.scope_start <= cursor_line <= vd.scope_end):
                continue
            if vd.line > cursor_line:
                continue
            # Prefer the declaration closest to the cursor
            if best is None or vd.line > best.line:
                best = vd
        if best:
            return (best.line, best.col)
        return None


def _body_range(body: Optional[Block], fallback_start: int) -> tuple[int, int]:
    """Compute the line range [start, end] of a Block node."""
    if not body or not body.statements:
        return (fallback_start, fallback_start + 1000)
    start = body.line if body.line else fallback_start
    end = start
    for stmt in body.statements:
        line = _deepest_line(stmt)
        if line > end:
            end = line
    return (start, end + 50)  # generous padding to include closing brace


def _deepest_line(node) -> int:
    """Find the deepest (highest line number) reachable from a node."""
    best = getattr(node, 'line', 0)
    # Check common block-carrying attributes
    for attr in ('body', 'then_block', 'else_block', 'try_block',
                 'catch_block', 'getter_body', 'setter_body'):
        child = getattr(node, attr, None)
        if child is not None:
            child_line = _deepest_line(child)
            if child_line > best:
                best = child_line
    if isinstance(node, Block):
        for stmt in node.statements:
            child_line = _deepest_line(stmt)
            if child_line > best:
                best = child_line
    if isinstance(node, SwitchStmt):
        for case in node.cases:
            for stmt in case.body:
                child_line = _deepest_line(stmt)
                if child_line > best:
                    best = child_line
    return best


def _collect_class_members(dmap: DefinitionMap, cls: ClassDecl):
    """Collect all member definitions from a class declaration."""
    for member in cls.members:
        if isinstance(member, FieldDecl):
            dmap.field_defs[(cls.name, member.name)] = (member.line, member.col)
        elif isinstance(member, MethodDecl):
            dmap.method_defs[(cls.name, member.name)] = (member.line, member.col)
            scope_start, scope_end = _body_range(member.body, member.line)
            _collect_params(dmap, member.params, scope_start, scope_end)
            if member.body:
                _collect_vars_in_block(dmap, member.body, scope_start, scope_end)
        elif isinstance(member, PropertyDecl):
            dmap.property_defs[(cls.name, member.name)] = (member.line, member.col)


def _collect_params(dmap: DefinitionMap, params: list[Param],
                    scope_start: int, scope_end: int):
    """Register function/method parameters as variable definitions."""
    for p in params:
        if p.name and p.line:
            dmap.var_defs.append(VarDef(
                name=p.name, line=p.line, col=p.col,
                scope_start=scope_start, scope_end=scope_end,
            ))


def _collect_vars_in_block(dmap: DefinitionMap, block: Block,
                           scope_start: int, scope_end: int):
    """Recursively collect variable declarations within a block."""
    for stmt in block.statements:
        _collect_vars_in_stmt(dmap, stmt, scope_start, scope_end)


def _collect_vars_in_stmt(dmap: DefinitionMap, stmt, scope_start: int, scope_end: int):
    """Collect variable definitions from a single statement, recursing into sub-blocks."""
    if isinstance(stmt, VarDeclStmt):
        if stmt.name and stmt.line:
            dmap.var_defs.append(VarDef(
                name=stmt.name, line=stmt.line, col=stmt.col,
                scope_start=scope_start, scope_end=scope_end,
            ))
    elif isinstance(stmt, ForInStmt):
        if stmt.var_name and stmt.line:
            dmap.var_defs.append(VarDef(
                name=stmt.var_name, line=stmt.line, col=stmt.col,
                scope_start=scope_start, scope_end=scope_end,
            ))
        if stmt.var_name2 and stmt.line:
            dmap.var_defs.append(VarDef(
                name=stmt.var_name2, line=stmt.line, col=stmt.col,
                scope_start=scope_start, scope_end=scope_end,
            ))
        if stmt.body:
            _collect_vars_in_block(dmap, stmt.body, scope_start, scope_end)
    elif isinstance(stmt, ParallelForStmt):
        if stmt.var_name and stmt.line:
            dmap.var_defs.append(VarDef(
                name=stmt.var_name, line=stmt.line, col=stmt.col,
                scope_start=scope_start, scope_end=scope_end,
            ))
        if stmt.body:
            _collect_vars_in_block(dmap, stmt.body, scope_start, scope_end)
    elif isinstance(stmt, CForStmt):
        # The init might be a VarDeclStmt
        if isinstance(stmt.init, VarDeclStmt) and stmt.init.name and stmt.init.line:
            dmap.var_defs.append(VarDef(
                name=stmt.init.name, line=stmt.init.line, col=stmt.init.col,
                scope_start=scope_start, scope_end=scope_end,
            ))
        if stmt.body:
            _collect_vars_in_block(dmap, stmt.body, scope_start, scope_end)
    elif isinstance(stmt, TryCatchStmt):
        if stmt.catch_var and stmt.line:
            dmap.var_defs.append(VarDef(
                name=stmt.catch_var, line=stmt.line, col=stmt.col,
                scope_start=scope_start, scope_end=scope_end,
            ))
        if stmt.try_block:
            _collect_vars_in_block(dmap, stmt.try_block, scope_start, scope_end)
        if stmt.catch_block:
            _collect_vars_in_block(dmap, stmt.catch_block, scope_start, scope_end)
    elif isinstance(stmt, IfStmt):
        if stmt.then_block:
            _collect_vars_in_block(dmap, stmt.then_block, scope_start, scope_end)
        if isinstance(stmt.else_block, Block):
            _collect_vars_in_block(dmap, stmt.else_block, scope_start, scope_end)
        elif isinstance(stmt.else_block, IfStmt):
            _collect_vars_in_stmt(dmap, stmt.else_block, scope_start, scope_end)
    elif isinstance(stmt, (WhileStmt, DoWhileStmt)):
        if stmt.body:
            _collect_vars_in_block(dmap, stmt.body, scope_start, scope_end)
    elif isinstance(stmt, SwitchStmt):
        for case in stmt.cases:
            if isinstance(case, CaseClause):
                for s in case.body:
                    _collect_vars_in_stmt(dmap, s, scope_start, scope_end)


# ---------------------------------------------------------------------------
# Token lookup
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
        # Exclusive end: col occupies [tok.col, tok.col + len(tok.value))
        tok_end_col = tok.col + len(tok.value)
        if tok.col <= target_col < tok_end_col:
            return tok
    return None


def _find_token_index(tokens: list[Token], token: Token) -> Optional[int]:
    """Find the index of a token in the token list (by identity)."""
    for i, t in enumerate(tokens):
        if t is token:
            return i
    return None


# ---------------------------------------------------------------------------
# Variable type resolution (for member access chains)
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
    for decl in ast.declarations:
        result = _scan_for_var_type(name, decl, class_table)
        if result:
            return result
    return None


_BUILTIN_TYPES = frozenset({
    "string", "int", "float", "double", "long", "short", "char",
    "bool", "void", "unsigned", "List", "Map", "Set", "Array",
})


def _scan_for_var_type(
    var_name: str,
    node,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Recursively scan AST nodes for a VarDeclStmt that declares var_name."""
    if isinstance(node, VarDeclStmt):
        if node.name == var_name:
            # Check explicit type annotation (user-defined or built-in)
            if node.type and (node.type.base in class_table
                              or node.type.base in _BUILTIN_TYPES):
                return node.type.base
            # Check initializer for constructor call: ClassName(...)
            if isinstance(node.initializer, CallExpr):
                callee = node.initializer.callee
                if isinstance(callee, Identifier) and callee.name in class_table:
                    return callee.name
            # Check initializer for new ClassName(...)
            if isinstance(node.initializer, NewExpr):
                if node.initializer.type and (node.initializer.type.base in class_table
                                              or node.initializer.type.base in _BUILTIN_TYPES):
                    return node.initializer.type.base
        return None

    # Recurse into container nodes that hold statements/members
    if isinstance(node, ClassDecl):
        for member in node.members:
            result = _scan_for_var_type(var_name, member, class_table)
            if result:
                return result
    elif isinstance(node, FunctionDecl):
        for p in node.params:
            if p.name == var_name and p.type:
                if p.type.base in class_table or p.type.base in _BUILTIN_TYPES:
                    return p.type.base
        if node.body:
            for stmt in node.body.statements:
                result = _scan_for_var_type(var_name, stmt, class_table)
                if result:
                    return result
    elif isinstance(node, MethodDecl):
        for p in node.params:
            if p.name == var_name and p.type:
                if p.type.base in class_table or p.type.base in _BUILTIN_TYPES:
                    return p.type.base
        if node.body:
            for stmt in node.body.statements:
                result = _scan_for_var_type(var_name, stmt, class_table)
                if result:
                    return result
    elif hasattr(node, 'then_block') or hasattr(node, 'body'):
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
    if token is None or token.type != TokenType.IDENT:
        return None

    class_table = result.analyzed.class_table if result.analyzed else {}
    dmap = DefinitionMap.from_ast(result.ast)
    cursor_line = token.line  # 1-based

    # 1. Member access: obj.member / obj->member / obj?.member
    loc = _try_member_definition(result, token, class_table, dmap)
    if loc:
        return loc

    # 2. Class name reference
    if token.value in dmap.class_defs:
        def_line, def_col = dmap.class_defs[token.value]
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col, len(token.value))

    # 3. Function name reference
    if token.value in dmap.function_defs:
        def_line, def_col = dmap.function_defs[token.value]
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col, len(token.value))

    # 4. Enum name reference
    if token.value in dmap.enum_defs:
        def_line, def_col = dmap.enum_defs[token.value]
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col, len(token.value))

    # 5. Struct name reference
    if token.value in dmap.struct_defs:
        def_line, def_col = dmap.struct_defs[token.value]
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col, len(token.value))

    # 6. Typedef alias reference
    if token.value in dmap.typedef_defs:
        def_line, def_col = dmap.typedef_defs[token.value]
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col, len(token.value))

    # 7. Local variable / parameter / loop variable / catch variable
    var_loc = dmap.find_var(token.value, cursor_line)
    if var_loc:
        def_line, def_col = var_loc
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col, len(token.value))

    return None


def _make_location(uri: str, line: int, col: int, length: int = 0) -> lsp.Location:
    """Create an LSP Location from a btrc 1-based line/col.

    When *length* > 0 the range spans the symbol so VS Code highlights it.
    """
    start = _btrc_to_lsp_position(line, col)
    end = lsp.Position(line=start.line, character=start.character + length) if length else start
    return lsp.Location(
        uri=uri,
        range=lsp.Range(start=start, end=end),
    )


def _resolve_chain_type(
    result: AnalysisResult,
    tokens: list[Token],
    end_idx: int,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Walk backwards through a chained access (a.b.c) and resolve the base type.

    Given tokens ending at *end_idx* (the token before the final dot), resolves
    the type of the full chain.  Returns a base type string like "List", "string",
    "ClassInfo", etc.
    """
    idx = end_idx
    chain: list[str] = [tokens[idx].value]

    while idx >= 2:
        prev = tokens[idx - 1]
        if prev.value not in ('.', '->', '?.'):
            break
        idx -= 2
        chain.append(tokens[idx].value)

    chain.reverse()  # now chain is [root, member1, member2, ...]

    # Resolve the root to a type
    root = chain[0]
    current_type: Optional[str] = None

    if root in class_table:
        current_type = root
    elif root == "self" and result.ast:
        current_type = _find_enclosing_class(result.ast, tokens[idx].line)
    elif result.ast:
        current_type = _resolve_variable_type(root, result.ast, class_table)

    if current_type is None:
        return None

    # Walk through the rest of the chain resolving field/method return types
    for member in chain[1:]:
        resolved = _resolve_member_type(current_type, member, class_table)
        if resolved is None:
            return None
        current_type = resolved

    return current_type


def _resolve_member_type(
    owner_type: str,
    member_name: str,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
    """Resolve the base type of a member access on a given type."""
    cname = owner_type
    while cname and cname in class_table:
        cinfo = class_table[cname]
        if member_name in cinfo.fields:
            fdecl = cinfo.fields[member_name]
            if isinstance(fdecl, FieldDecl) and fdecl.type:
                return fdecl.type.base
        if member_name in cinfo.methods:
            mdecl = cinfo.methods[member_name]
            if isinstance(mdecl, MethodDecl) and mdecl.return_type:
                return mdecl.return_type.base
        cname = cinfo.parent

    # Built-in type fields
    if owner_type in ("string", "List", "Map", "Set"):
        if member_name == "len":
            return "int"
    return None


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

    member_name = token.value

    # Resolve the object type via chain resolution (handles a.b.c patterns)
    target_class = _resolve_chain_type(
        result, result.tokens, token_idx - 2, class_table
    )

    if target_class is None:
        # Fallback: search all classes for a class that has this member
        for cname, cinfo in class_table.items():
            if member_name in cinfo.methods or member_name in cinfo.fields:
                target_class = cname
                break

    if target_class is None:
        return None

    name_len = len(member_name)

    # Walk the class hierarchy: target_class and all parents
    current_class = target_class
    while current_class:
        # Check methods
        key = (current_class, member_name)
        if key in dmap.method_defs:
            def_line, def_col = dmap.method_defs[key]
            return _make_location(result.uri, def_line, def_col, name_len)

        # Check fields
        if key in dmap.field_defs:
            def_line, def_col = dmap.field_defs[key]
            return _make_location(result.uri, def_line, def_col, name_len)

        # Check properties
        if key in dmap.property_defs:
            def_line, def_col = dmap.property_defs[key]
            return _make_location(result.uri, def_line, def_col, name_len)

        # Move to parent class
        cinfo = class_table.get(current_class)
        if cinfo and cinfo.parent and cinfo.parent in class_table:
            current_class = cinfo.parent
        else:
            break

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
            if decl.line <= line:
                max_line = decl.line
                for member in decl.members:
                    if hasattr(member, 'line') and member.line > max_line:
                        max_line = member.line
                    if isinstance(member, MethodDecl) and member.body:
                        for stmt in member.body.statements:
                            if hasattr(stmt, 'line') and stmt.line > max_line:
                                max_line = stmt.line
                if line <= max_line:
                    return decl.name
    return None
