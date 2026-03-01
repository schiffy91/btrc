"""Expression and statement-expression rendering for the C emitter."""

from __future__ import annotations

from .nodes import (
    IRExpr,
    IRStmt,
    IRVarDecl,
    IRAssign,
    IRExprStmt,
    IRIf,
    IRLiteral,
    IRVar,
    IRBinOp,
    IRUnaryOp,
    IRCall,
    IRFieldAccess,
    IRCast,
    IRTernary,
    IRSizeof,
    IRIndex,
    IRAddressOf,
    IRDeref,
    IRRawExpr,
    IRStmtExpr,
    IRSpawnThread,
)


class _ExprEmitterMixin:
    """Mixin providing expression rendering for CEmitter.

    All methods here assume the class also has _expr() available (which
    is defined here and used recursively).
    """

    def _cond_expr(self, expr: IRExpr) -> str:
        """Emit an expression for use as a condition in if/while/do-while.

        Strips redundant outer parentheses since the caller already wraps
        in parens (e.g. ``if (...)``).  This avoids ``if ((x == 0))``
        which triggers ``-Wparentheses-equality``.
        """
        result = self._expr(expr)
        if result.startswith('(') and result.endswith(')'):
            depth = 0
            for i, ch in enumerate(result):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                if depth == 0 and i < len(result) - 1:
                    break
            else:
                result = result[1:-1]
        return result

    def _expr(self, expr: IRExpr) -> str:
        if expr is None:
            return "/* null expr */"

        if isinstance(expr, IRLiteral):
            return expr.text

        elif isinstance(expr, IRVar):
            return expr.name

        elif isinstance(expr, IRBinOp):
            return f"({self._expr(expr.left)} {expr.op} {self._expr(expr.right)})"

        elif isinstance(expr, IRUnaryOp):
            if expr.prefix:
                return f"({expr.op}{self._expr(expr.operand)})"
            else:
                return f"({self._expr(expr.operand)}{expr.op})"

        elif isinstance(expr, IRCall):
            args = ", ".join(self._expr(a) for a in expr.args)
            return f"{expr.callee}({args})"

        elif isinstance(expr, IRFieldAccess):
            op = "->" if expr.arrow else "."
            return f"{self._expr(expr.obj)}{op}{expr.field}"

        elif isinstance(expr, IRCast):
            return f"(({expr.target_type}){self._expr(expr.expr)})"

        elif isinstance(expr, IRTernary):
            return (f"({self._expr(expr.condition)} ? "
                    f"{self._expr(expr.true_expr)} : "
                    f"{self._expr(expr.false_expr)})")

        elif isinstance(expr, IRSizeof):
            return f"sizeof({expr.operand})"

        elif isinstance(expr, IRIndex):
            return f"{self._expr(expr.obj)}[{self._expr(expr.index)}]"

        elif isinstance(expr, IRAddressOf):
            return f"(&{self._expr(expr.expr)})"

        elif isinstance(expr, IRDeref):
            return f"(*{self._expr(expr.expr)})"

        elif isinstance(expr, IRRawExpr):
            return expr.text

        elif isinstance(expr, IRStmtExpr):
            parts = [self._stmt_text(s) for s in expr.stmts]
            parts.append(f"{self._expr(expr.result)};")
            return "({ " + " ".join(parts) + " })"

        elif isinstance(expr, IRSpawnThread):
            arg = self._expr(expr.capture_arg) if expr.capture_arg else "NULL"
            return f"__btrc_thread_spawn((void*(*)(void*)){expr.fn_ptr}, {arg})"

        return f"/* unknown expr: {type(expr).__name__} */"

    # --- Statement expression helpers ---

    def _stmt_text(self, stmt: IRStmt) -> str:
        """Render a single IRStmt as inline text for use inside statement expressions."""
        if isinstance(stmt, IRVarDecl):
            if stmt.init:
                return f"{stmt.c_type.text} {stmt.name} = {self._expr(stmt.init)};"
            return f"{stmt.c_type.text} {stmt.name};"
        elif isinstance(stmt, IRExprStmt):
            return f"{self._expr(stmt.expr)};"
        elif isinstance(stmt, IRAssign):
            return f"{self._expr(stmt.target)} = {self._expr(stmt.value)};"
        elif isinstance(stmt, IRIf):
            cond = self._expr(stmt.condition)
            body = " ".join(self._stmt_text(s) for s in stmt.then_block.stmts)
            return f"if ({cond}) {{ {body} }}"
        return "/* unknown stmt */;"
