"""WGSL emitter: translates btrc AST expressions/statements to WGSL text.

Used by gpu.py to generate the body of WGSL compute shaders from @gpu
function AST nodes. Only handles the GPU-compatible subset of btrc.
"""

from __future__ import annotations

from ...ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BoolLiteral,
    BreakStmt,
    CallExpr,
    CastExpr,
    CForStmt,
    ContinueStmt,
    ExprStmt,
    FloatLiteral,
    ForInitExpr,
    ForInitVar,
    Identifier,
    IfStmt,
    IndexExpr,
    IntLiteral,
    NullLiteral,
    ReturnStmt,
    TernaryExpr,
    TypeExpr,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)

# btrc type → WGSL type
_TYPE_MAP = {
    "int": "i32",
    "float": "f32",
    "bool": "bool",
}

# btrc operator → WGSL operator (most are 1:1)
_OP_MAP = {
    "+": "+", "-": "-", "*": "*", "/": "/", "%": "%",
    "==": "==", "!=": "!=", "<": "<", ">": ">",
    "<=": "<=", ">=": ">=",
    "&&": "&&", "||": "||",
    "&": "&", "|": "|", "^": "^",
    "<<": "<<", ">>": ">>",
    "!": "!",
    "++": "++", "--": "--",
}


def btrc_type_to_wgsl(type_expr: TypeExpr) -> str:
    """Convert a btrc TypeExpr to its WGSL equivalent."""
    if type_expr is None:
        return "void"
    base = type_expr.base
    if type_expr.is_array:
        elem = _TYPE_MAP.get(base, base)
        return f"array<{elem}>"
    return _TYPE_MAP.get(base, base)


def btrc_type_to_wgsl_elem(type_expr: TypeExpr) -> str:
    """Get the WGSL element type for a btrc type (for storage buffers)."""
    return _TYPE_MAP.get(type_expr.base, type_expr.base)


class WgslEmitter:
    """Emits WGSL text from btrc AST nodes (GPU-compatible subset)."""

    def __init__(self, array_params: list[str], has_output: bool = True):
        self._indent = 1  # function body starts at indent 1
        self._lines: list[str] = []
        self._array_params = set(array_params)
        self._has_output = has_output

    def emit_block(self, block) -> str:
        """Emit a block of statements, return WGSL text."""
        if block is None:
            return ""
        for stmt in block.statements:
            self._emit_stmt(stmt)
        return "\n".join(self._lines)

    def _line(self, text: str):
        self._lines.append("    " * self._indent + text)

    def _emit_stmt(self, stmt):
        if isinstance(stmt, VarDeclStmt):
            wgsl_type = _TYPE_MAP.get(stmt.type.base, "i32") if stmt.type else "i32"
            if stmt.initializer:
                init = self._expr(stmt.initializer)
                self._line(f"var {stmt.name}: {wgsl_type} = {init};")
            else:
                self._line(f"var {stmt.name}: {wgsl_type};")

        elif isinstance(stmt, ReturnStmt):
            if stmt.value and self._has_output:
                val = self._expr(stmt.value)
                self._line(f"_output[gid.x] = {val};")
                self._line("return;")
            else:
                self._line("return;")

        elif isinstance(stmt, IfStmt):
            cond = self._expr(stmt.condition)
            self._line(f"if ({cond}) {{")
            self._indent += 1
            if stmt.then_block:
                for s in stmt.then_block.statements:
                    self._emit_stmt(s)
            self._indent -= 1
            if stmt.else_block:
                if hasattr(stmt.else_block, 'body'):
                    self._line("} else {")
                    self._indent += 1
                    for s in stmt.else_block.body.statements:
                        self._emit_stmt(s)
                    self._indent -= 1
                    self._line("}")
                elif hasattr(stmt.else_block, 'if_stmt'):
                    self._lines[-1] = self._lines[-1]  # keep last line
                    inner = stmt.else_block.if_stmt
                    self._line(f"}} else if ({self._expr(inner.condition)}) {{")
                    self._indent += 1
                    if inner.then_block:
                        for s in inner.then_block.statements:
                            self._emit_stmt(s)
                    self._indent -= 1
                    self._line("}")
            else:
                self._line("}")

        elif isinstance(stmt, WhileStmt):
            cond = self._expr(stmt.condition)
            self._line(f"while ({cond}) {{")
            self._indent += 1
            if stmt.body:
                for s in stmt.body.statements:
                    self._emit_stmt(s)
            self._indent -= 1
            self._line("}")

        elif isinstance(stmt, CForStmt):
            init_text = ""
            if stmt.init:
                if isinstance(stmt.init, ForInitVar):
                    vd = stmt.init.var_decl
                    wt = _TYPE_MAP.get(vd.type.base, "i32") if vd.type else "i32"
                    init_val = self._expr(vd.initializer) if vd.initializer else "0"
                    init_text = f"var {vd.name}: {wt} = {init_val}"
                elif isinstance(stmt.init, ForInitExpr):
                    init_text = self._expr(stmt.init.expression)
            cond_text = self._expr(stmt.condition) if stmt.condition else "true"
            update_text = self._expr(stmt.update) if stmt.update else ""
            self._line(f"for ({init_text}; {cond_text}; {update_text}) {{")
            self._indent += 1
            if stmt.body:
                for s in stmt.body.statements:
                    self._emit_stmt(s)
            self._indent -= 1
            self._line("}")

        elif isinstance(stmt, ExprStmt):
            self._line(f"{self._expr(stmt.expr)};")

        elif isinstance(stmt, BreakStmt):
            self._line("break;")

        elif isinstance(stmt, ContinueStmt):
            self._line("continue;")

    def _expr(self, expr) -> str:
        if expr is None:
            return "0"

        if isinstance(expr, IntLiteral):
            return str(expr.value)

        if isinstance(expr, FloatLiteral):
            raw = expr.raw or str(expr.value)
            if '.' not in raw and 'e' not in raw.lower():
                raw += ".0"
            return raw

        if isinstance(expr, BoolLiteral):
            return "true" if expr.value else "false"

        if isinstance(expr, NullLiteral):
            return "0"

        if isinstance(expr, Identifier):
            name = expr.name
            return name

        if isinstance(expr, BinaryExpr):
            left = self._expr(expr.left)
            right = self._expr(expr.right)
            op = _OP_MAP.get(expr.op, expr.op)
            return f"({left} {op} {right})"

        if isinstance(expr, UnaryExpr):
            operand = self._expr(expr.operand)
            op = _OP_MAP.get(expr.op, expr.op)
            if expr.prefix:
                return f"({op}{operand})"
            return f"({operand}{op})"

        if isinstance(expr, CallExpr):
            if isinstance(expr.callee, Identifier):
                name = expr.callee.name
                if name == "gpu_id":
                    return "gid.x"
                # Map btrc math functions to WGSL builtins
                wgsl_builtins = {
                    "abs": "abs", "min": "min", "max": "max",
                    "sqrt": "sqrt", "floor": "floor", "ceil": "ceil",
                    "round": "round", "clamp": "clamp",
                    "sin": "sin", "cos": "cos", "tan": "tan",
                    "exp": "exp", "log": "log", "pow": "pow",
                }
                if name in wgsl_builtins:
                    args = ", ".join(self._expr(a) for a in expr.args)
                    return f"{wgsl_builtins[name]}({args})"
                args = ", ".join(self._expr(a) for a in expr.args)
                return f"{name}({args})"
            args = ", ".join(self._expr(a) for a in expr.args)
            return f"/* unsupported call */({args})"

        if isinstance(expr, IndexExpr):
            obj = self._expr(expr.obj)
            idx = self._expr(expr.index)
            return f"{obj}[{idx}]"

        if isinstance(expr, AssignExpr):
            target = self._expr(expr.target)
            value = self._expr(expr.value)
            if expr.op == "=":
                return f"{target} = {value}"
            # Compound assignment: +=, -=, etc.
            base_op = expr.op[:-1]  # remove '='
            return f"{target} = ({target} {base_op} {value})"

        if isinstance(expr, TernaryExpr):
            cond = self._expr(expr.condition)
            t = self._expr(expr.true_expr)
            f = self._expr(expr.false_expr)
            return f"select({f}, {t}, {cond})"

        if isinstance(expr, CastExpr):
            target = _TYPE_MAP.get(expr.target_type.base, expr.target_type.base)
            inner = self._expr(expr.expr)
            return f"{target}({inner})"

        return f"/* unhandled: {type(expr).__name__} */"
