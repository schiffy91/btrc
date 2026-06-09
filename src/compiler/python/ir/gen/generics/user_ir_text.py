"""Text rendering helpers for generic-method compatibility checks."""

from __future__ import annotations

from ...nodes import (
    IRAssign,
    IRBinOp,
    IRBreak,
    IRCall,
    IRCast,
    IRContinue,
    IRDoWhile,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRIf,
    IRIndex,
    IRLiteral,
    IRReturn,
    IRSizeof,
    IRStmt,
    IRStmtExpr,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
)


def _ir_expr_to_text(expr: IRExpr) -> str:
    """Convert an IRExpr node to a rough C text string."""
    if expr is None:
        return ""
    if isinstance(expr, IRLiteral):
        return expr.text
    if isinstance(expr, IRVar):
        return expr.name
    if isinstance(expr, IRBinOp):
        return f"({_ir_expr_to_text(expr.left)} {expr.op} {_ir_expr_to_text(expr.right)})"
    if isinstance(expr, IRUnaryOp):
        inner = _ir_expr_to_text(expr.operand)
        if expr.prefix:
            return f"({expr.op}{inner})"
        return f"({inner}{expr.op})"
    if isinstance(expr, IRCall):
        args = ", ".join(_ir_expr_to_text(a) for a in expr.args)
        return f"{expr.callee}({args})"
    if isinstance(expr, IRFieldAccess):
        op = "->" if expr.arrow else "."
        return f"{_ir_expr_to_text(expr.obj)}{op}{expr.field}"
    if isinstance(expr, IRCast):
        return f"({expr.target_type.text}){_ir_expr_to_text(expr.expr)}"
    if isinstance(expr, IRTernary):
        return (f"({_ir_expr_to_text(expr.condition)} ? "
                f"{_ir_expr_to_text(expr.true_expr)} : "
                f"{_ir_expr_to_text(expr.false_expr)})")
    if isinstance(expr, IRSizeof):
        return f"sizeof({expr.operand})"
    if isinstance(expr, IRIndex):
        return f"{_ir_expr_to_text(expr.obj)}[{_ir_expr_to_text(expr.index)}]"
    if isinstance(expr, IRStmtExpr):
        return _ir_expr_to_text(expr.result)
    return "0"


def _ir_stmt_to_text(stmt: IRStmt) -> str:
    """Convert an IRStmt node to rough C text for compatibility checks."""
    if isinstance(stmt, IRVarDecl):
        if stmt.init:
            return f" {stmt.c_type.text} {stmt.name} = {_ir_expr_to_text(stmt.init)};"
        return f" {stmt.c_type.text} {stmt.name};"
    if isinstance(stmt, IRExprStmt):
        return f" {_ir_expr_to_text(stmt.expr)};"
    if isinstance(stmt, IRReturn):
        if stmt.value:
            return f" return {_ir_expr_to_text(stmt.value)};"
        return " return;"
    if isinstance(stmt, IRAssign):
        return f" {_ir_expr_to_text(stmt.target)} = {_ir_expr_to_text(stmt.value)};"
    if isinstance(stmt, IRIf):
        txt = f" if ({_ir_expr_to_text(stmt.condition)}) {{"
        if stmt.then_block:
            for s in stmt.then_block.stmts:
                txt += _ir_stmt_to_text(s)
            txt += " }"
        if stmt.else_block and stmt.else_block.stmts:
            txt += " else {"
            for s in stmt.else_block.stmts:
                txt += _ir_stmt_to_text(s)
            txt += " }"
        return txt
    if isinstance(stmt, IRFor):
        init_text = ""
        if stmt.init:
            if isinstance(stmt.init, IRVarDecl):
                if stmt.init.init:
                    init_text = f"{stmt.init.c_type.text} {stmt.init.name} = {_ir_expr_to_text(stmt.init.init)}"
                else:
                    init_text = f"{stmt.init.c_type.text} {stmt.init.name}"
            elif isinstance(stmt.init, IRExprStmt):
                init_text = _ir_expr_to_text(stmt.init.expr)
            elif isinstance(stmt.init, IRAssign):
                init_text = f"{_ir_expr_to_text(stmt.init.target)} = {_ir_expr_to_text(stmt.init.value)}"
        cond_text = _ir_expr_to_text(stmt.condition) if stmt.condition else ""
        upd_text = _ir_expr_to_text(stmt.update) if stmt.update else ""
        txt = f" for ({init_text}; {cond_text}; {upd_text}) {{"
        if stmt.body:
            for s in stmt.body.stmts:
                txt += _ir_stmt_to_text(s)
        txt += " }"
        return txt
    if isinstance(stmt, IRWhile):
        txt = f" while ({_ir_expr_to_text(stmt.condition)}) {{"
        if stmt.body:
            for s in stmt.body.stmts:
                txt += _ir_stmt_to_text(s)
        txt += " }"
        return txt
    if isinstance(stmt, IRDoWhile):
        txt = " do {"
        if stmt.body:
            for s in stmt.body.stmts:
                txt += _ir_stmt_to_text(s)
        txt += f" }} while ({_ir_expr_to_text(stmt.condition)});"
        return txt
    if isinstance(stmt, IRBreak):
        return " break;"
    if isinstance(stmt, IRContinue):
        return " continue;"
    return ""


def _ir_stmts_to_text(stmts: list[IRStmt]) -> str:
    """Convert a list of IRStmt nodes to rough C text."""
    return "".join(_ir_stmt_to_text(s) for s in stmts)
