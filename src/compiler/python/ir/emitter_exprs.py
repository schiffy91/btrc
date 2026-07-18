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

_INLINE_EXPRESSION_LIMIT = 1000


def _compound(
    opening: str,
    values: list[str],
    closing: str,
    *,
    inline_separator: str = "",
    line_separator: str = "\n",
) -> str:
    """Keep one structured expression group within the inline budget."""
    inline = opening + inline_separator.join(values) + closing
    if "\n" not in inline and len(inline) <= _INLINE_EXPRESSION_LIMIT:
        return inline
    return opening + "\n" + line_separator.join(values) + "\n" + closing


def _delimited(opening: str, values: list[str], closing: str) -> str:
    """Format a structured expression list without oversized C lines."""
    return _compound(
        opening,
        values,
        closing,
        inline_separator=", ",
        line_separator=",\n",
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
        return _compound("(void)(", [self._expr(expr)], ")")

    def _expr(self, expr: IRExpr) -> str:
        if expr is None:
            raise TypeError("cannot emit a null IR expression")

        if isinstance(expr, IRLiteral):
            return expr.text

        elif isinstance(expr, IRVar):
            return expr.name

        elif isinstance(expr, IRBinOp):
            return _compound(
                "(",
                [self._expr(expr.left), expr.op, self._expr(expr.right)],
                ")",
                inline_separator=" ",
            )

        elif isinstance(expr, IRCommaExpr):
            return _delimited(
                "(",
                [self._expr(item) for item in expr.expressions],
                ")",
            )

        elif isinstance(expr, IRUnaryOp):
            if expr.prefix:
                return _compound(f"({expr.op}", [self._expr(expr.operand)], ")")
            return _compound("(", [self._expr(expr.operand)], f"{expr.op})")

        elif isinstance(expr, IRCall):
            args = _delimited("(", [self._expr(arg) for arg in expr.args], ")")
            callee = expr.callee if isinstance(expr.callee, str) else self._expr(expr.callee)
            return _compound("", [callee, args], "")

        elif isinstance(expr, IRFieldAccess):
            op = "->" if expr.arrow else "."
            return _compound("", [self._expr(expr.obj), f"{op}{expr.field}"], "")

        elif isinstance(expr, IRCast):
            return _compound(f"(({expr.target_type})", [self._expr(expr.expr)], ")")

        elif isinstance(expr, IRTernary):
            return _compound(
                "(",
                [
                    self._expr(expr.condition),
                    "?",
                    self._expr(expr.true_expr),
                    ":",
                    self._expr(expr.false_expr),
                ],
                ")",
                inline_separator=" ",
            )

        elif isinstance(expr, IRSizeof):
            operand = self._expr(expr.operand) if isinstance(expr.operand, IRExpr) else str(expr.operand)
            return _compound("sizeof(", [operand], ")")

        elif isinstance(expr, IRInitializerList):
            values = [self._expr(value) for value in expr.elements] or ["0"]
            return _delimited("{", values, "}")

        elif isinstance(expr, IRCompoundLiteral):
            fields = [_compound(f".{name} = ", [self._expr(value)], "") for name, value in expr.fields] or ["0"]
            return _compound(
                f"({expr.c_type})",
                [_delimited("{", fields, "}")],
                "",
            )

        elif isinstance(expr, IRIndex):
            index = _compound("[", [self._expr(expr.index)], "]")
            return _compound("", [self._expr(expr.obj), index], "")

        elif isinstance(expr, IRAddressOf):
            return _compound("(&", [self._expr(expr.expr)], ")")

        elif isinstance(expr, IRDeref):
            return _compound("(*", [self._expr(expr.expr)], ")")

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
