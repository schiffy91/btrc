"""Block-granular variable scope collection for the btrc LSP.

Walks function/method bodies and records every variable-like definition
(local, parameter, loop variable, catch variable) together with the REAL line
range it is visible in. Block ends come from token-space brace matching
(utils.find_matching_brace_line), so scopes never bleed into sibling blocks
or functions. Positions are native to the active document.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.compiler.python.ast_nodes import (
    Block,
    CaseClause,
    CForStmt,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    ForInitVar,
    ForInStmt,
    IfStmt,
    ParallelForStmt,
    SwitchStmt,
    TryCatchStmt,
    VarDeclStmt,
    WhileStmt,
)
from src.compiler.python.tokens import Token
from src.devex.lsp.utils import body_range, find_matching_brace_line


@dataclass
class VarDef:
    """A single variable-like definition with its scope context.

    ``line``/``col`` point at the NAME token. ``scope_start``..``scope_end``
    is the inclusive 1-based line range the definition is visible in.
    """

    name: str
    line: int
    col: int
    scope_start: int
    scope_end: int
    kind: str = "local"  # local|cfor|param|loop|loop_key|parallel|catch
    node: object = None  # VarDeclStmt | Param | None
    owner: str | None = None  # "func" or "Class.method" (params only)


def _name_token_pos(
    tokens: list[Token] | None, name: str, line: int, col: int
) -> tuple[int, int]:
    """Position of the first token spelling *name* at/after (line, col)."""
    if tokens:
        for tok in tokens:
            if tok.line < line or (tok.line == line and tok.col < col):
                continue
            if tok.value == name:
                return (tok.line, tok.col)
    return (line, col)


def _block_end(tokens: list[Token] | None, block: Block | None, fallback: int) -> int:
    """Real end line of *block* via brace matching; *fallback* when unknown."""
    if tokens and block is not None and block.line:
        end = find_matching_brace_line(tokens, block.line, block.col)
        if end is not None:
            return end
    return fallback


def collect_callable_vars(
    var_defs: list[VarDef],
    node,
    tokens: list[Token] | None,
    class_name: str | None = None,
) -> None:
    """Collect params + body variables of a FunctionDecl/MethodDecl."""
    scope_start, scope_end = body_range(node.body, node.line, tokens)
    owner = f"{class_name}.{node.name}" if class_name else node.name
    for p in node.params:
        if p.name and p.line:
            line, col = _name_token_pos(tokens, p.name, p.line, p.col)
            var_defs.append(
                VarDef(p.name, line, col, scope_start, scope_end, "param", p, owner)
            )
    if node.body:
        _collect_block(var_defs, node.body, tokens, scope_end)


def _collect_block(
    var_defs: list[VarDef], block: Block, tokens: list[Token] | None, block_end: int
) -> None:
    """Collect definitions inside *block*; *block_end* is its real end line."""
    for stmt in block.statements:
        _collect_stmt(var_defs, stmt, tokens, block_end)


def _add_var(
    var_defs: list[VarDef],
    tokens: list[Token] | None,
    name: str,
    at,
    scope: tuple[int, int],
    kind: str,
    node=None,
) -> None:
    line, col = _name_token_pos(tokens, name, at.line, at.col)
    var_defs.append(VarDef(name, line, col, scope[0], scope[1], kind, node))


def _collect_stmt(var_defs, stmt, tokens, block_end: int) -> None:
    if isinstance(stmt, VarDeclStmt):
        if stmt.name and stmt.line:
            _add_var(var_defs, tokens, stmt.name, stmt, (stmt.line, block_end), "local", stmt)
    elif isinstance(stmt, Block):
        # a bare nested block, e.g. a `case` body wrapped in `{ ... }`
        _collect_block(var_defs, stmt, tokens, _block_end(tokens, stmt, block_end))
    elif isinstance(stmt, ForInStmt):
        end = _block_end(tokens, stmt.body, block_end)
        if stmt.var_name and stmt.line:
            _add_var(var_defs, tokens, stmt.var_name, stmt, (stmt.line, end), "loop")
        if stmt.var_name2 and stmt.line:
            _add_var(var_defs, tokens, stmt.var_name2, stmt, (stmt.line, end), "loop_key")
        if stmt.body:
            _collect_block(var_defs, stmt.body, tokens, end)
    elif isinstance(stmt, ParallelForStmt):
        end = _block_end(tokens, stmt.body, block_end)
        if stmt.var_name and stmt.line:
            _add_var(var_defs, tokens, stmt.var_name, stmt, (stmt.line, end), "parallel")
        if stmt.body:
            _collect_block(var_defs, stmt.body, tokens, end)
    elif isinstance(stmt, CForStmt):
        end = _block_end(tokens, stmt.body, block_end)
        if isinstance(stmt.init, ForInitVar):
            var_decl = stmt.init.var_decl
            if isinstance(var_decl, VarDeclStmt) and var_decl.name and var_decl.line:
                _add_var(
                    var_defs, tokens, var_decl.name, var_decl,
                    (var_decl.line, end), "cfor", var_decl,
                )
        if stmt.body:
            _collect_block(var_defs, stmt.body, tokens, end)
    elif isinstance(stmt, TryCatchStmt):
        if stmt.try_block:
            _collect_block(
                var_defs, stmt.try_block, tokens, _block_end(tokens, stmt.try_block, block_end)
            )
        catch_end = _block_end(tokens, stmt.catch_block, block_end)
        if stmt.catch_var and stmt.catch_block is not None and stmt.catch_block.line:
            # The catch var is confined to the catch block. Its name token sits
            # in the catch header, between the try block's `}` and the catch
            # block's `{`: take the last spelling in that window.
            try_end = _block_end(tokens, stmt.try_block, stmt.line)
            line, col = _catch_var_pos(tokens, stmt.catch_var, try_end, stmt.catch_block)
            var_defs.append(
                VarDef(
                    stmt.catch_var, line, col,
                    stmt.catch_block.line, catch_end, "catch",
                )
            )
        if stmt.catch_block:
            _collect_block(var_defs, stmt.catch_block, tokens, catch_end)
        if stmt.finally_block:
            _collect_block(
                var_defs, stmt.finally_block, tokens,
                _block_end(tokens, stmt.finally_block, block_end),
            )
    elif isinstance(stmt, IfStmt):
        if stmt.then_block:
            _collect_block(
                var_defs, stmt.then_block, tokens, _block_end(tokens, stmt.then_block, block_end)
            )
        if isinstance(stmt.else_block, ElseBlock) and stmt.else_block.body:
            body = stmt.else_block.body
            _collect_block(var_defs, body, tokens, _block_end(tokens, body, block_end))
        elif isinstance(stmt.else_block, ElseIf) and stmt.else_block.if_stmt:
            _collect_stmt(var_defs, stmt.else_block.if_stmt, tokens, block_end)
    elif isinstance(stmt, (WhileStmt, DoWhileStmt)):
        if stmt.body:
            _collect_block(var_defs, stmt.body, tokens, _block_end(tokens, stmt.body, block_end))
    elif isinstance(stmt, SwitchStmt):
        end = block_end
        if tokens and stmt.line:
            end = find_matching_brace_line(tokens, stmt.line, stmt.col) or block_end
        for case in stmt.cases:
            if isinstance(case, CaseClause):
                for s in case.body:
                    _collect_stmt(var_defs, s, tokens, end)


def _catch_var_pos(
    tokens: list[Token] | None, name: str, after_line: int, catch_block: Block
) -> tuple[int, int]:
    """Name-token position of a catch variable (last *name* in the header)."""
    best = (catch_block.line, catch_block.col)
    if tokens:
        for tok in tokens:
            if (tok.line, tok.col) >= (catch_block.line, catch_block.col):
                break
            if tok.line >= after_line and tok.value == name:
                best = (tok.line, tok.col)
    return best
