"""Expression and statement-expression rendering for the C emitter."""

from __future__ import annotations

from .nodes import (
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRCompoundLiteral,
    IRDeref,
    IRExpr,
    IRFieldAccess,
    IRIndex,
    IRInitializerList,
    IRLiteral,
    IRSizeof,
    IRStmtExpr,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
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
        if result.startswith("(") and result.endswith(")"):
            depth = 0
            quote = None
            escaped = False
            for i, ch in enumerate(result):
                if quote is not None:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == quote:
                        quote = None
                    continue
                if ch in ("'", '"'):
                    quote = ch
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                if depth == 0 and i < len(result) - 1:
                    break
            else:
                result = result[1:-1]
        return result

    def _discarded_expr(self, expr: IRExpr) -> str:
        """Render an expression whose value is intentionally discarded."""
        return f"(void)({self._expr(expr)})"

    def _expr(self, expr: IRExpr) -> str:
        if expr is None:
            raise TypeError("cannot emit a null IR expression")

        if isinstance(expr, IRLiteral):
            return expr.text

        elif isinstance(expr, IRVar):
            return expr.name

        elif isinstance(expr, IRBinOp):
            return f"({self._expr(expr.left)} {expr.op} {self._expr(expr.right)})"

        elif isinstance(expr, IRCommaExpr):
            return "(" + ", ".join(self._expr(item) for item in expr.expressions) + ")"

        elif isinstance(expr, IRUnaryOp):
            if expr.prefix:
                return f"({expr.op}{self._expr(expr.operand)})"
            else:
                return f"({self._expr(expr.operand)}{expr.op})"

        elif isinstance(expr, IRCall):
            args = ", ".join(self._expr(a) for a in expr.args)
            callee = expr.callee if isinstance(expr.callee, str) else self._expr(expr.callee)
            return f"{callee}({args})"

        elif isinstance(expr, IRFieldAccess):
            op = "->" if expr.arrow else "."
            return f"{self._expr(expr.obj)}{op}{expr.field}"

        elif isinstance(expr, IRCast):
            return f"(({expr.target_type}){self._expr(expr.expr)})"

        elif isinstance(expr, IRTernary):
            return f"({self._expr(expr.condition)} ? {self._expr(expr.true_expr)} : {self._expr(expr.false_expr)})"

        elif isinstance(expr, IRSizeof):
            operand = self._expr(expr.operand) if isinstance(expr.operand, IRExpr) else str(expr.operand)
            return f"sizeof({operand})"

        elif isinstance(expr, IRInitializerList):
            values = ", ".join(self._expr(value) for value in expr.elements)
            return "{" + (values or "0") + "}"

        elif isinstance(expr, IRCompoundLiteral):
            fields = ", ".join(f".{name} = {self._expr(value)}" for name, value in expr.fields)
            return f"({expr.c_type})" + "{" + (fields or "0") + "}"

        elif isinstance(expr, IRIndex):
            return f"{self._expr(expr.obj)}[{self._expr(expr.index)}]"

        elif isinstance(expr, IRAddressOf):
            return f"(&{self._expr(expr.expr)})"

        elif isinstance(expr, IRDeref):
            return f"(*{self._expr(expr.expr)})"

        elif isinstance(expr, IRStmtExpr):
            # Only declarations are safe to hoist out of a control-sensitive
            # expression. A literal zero/null initializer is also safe and
            # gives persistent ARC slots a defined value before a repeated
            # condition first evaluates. Runtime work remains in the result.
            for s in expr.stmts:
                safe_init = isinstance(s, IRVarDecl) and (
                    s.init is None or (isinstance(s.init, IRLiteral) and s.init.text in {"0", "NULL", "false"})
                )
                if not safe_init:
                    raise ValueError(
                        "IRStmtExpr setup permits uninitialized variable declarations "
                        "or declarations with a literal zero initializer only"
                    )
                self._emit_stmt(s)
            return self._expr(expr.result)

        raise TypeError(f"unsupported IR expression: {type(expr).__name__}")
