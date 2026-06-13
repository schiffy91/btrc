"""F-string lowering: FStringLiteral → snprintf measuring + allocation + formatting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    CallExpr,
    FieldAccessExpr,
    FStringExpr,
    FStringLiteral,
    FStringText,
    StringLiteral,
)
from ..nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCast,
    IRExpr,
    IRExprStmt,
    IRLiteral,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from .stringable import has_to_string, to_string_call
from .types import format_spec_for_type, type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_fstring(gen: IRGenerator, node: FStringLiteral) -> IRExpr:
    """Lower an f-string to snprintf-based string building.

    Each interpolated expression is evaluated EXACTLY ONCE into a temporary,
    and that temporary is reused by both the measure (snprintf NULL/0 sizing)
    and the write pass. Evaluating the expression in both passes would
    double-run any side effects (counters, RNG, pop(), I/O).

    Pattern:
        <T0> __arg0 = <expr0>;
        ...
        int __len = snprintf(NULL, 0, "fmt", __arg0, ...);
        char* __buf = __btrc_str_track((char*)malloc(__len + 1));
        snprintf(__buf, __len + 1, "fmt", __arg0, ...);
    """
    gen.use_helper("__btrc_str_track")

    tmp = gen.fresh_temp("__fstr")

    # Build the format string, hoist each interpolation into a temp, and
    # collect the temp references used by both snprintf passes.
    fmt_parts = []
    arg_decls = []  # IRVarDecl for each interpolation (evaluated once)
    args = []       # IRExpr referencing the temp (used by both passes)

    for part in node.parts:
        if isinstance(part, FStringText):
            # part.text holds escape sequences in source form (e.g. "\n", "\t",
            # "\\", "\"") exactly as written, plus literal characters. These are
            # passed through verbatim into the C format-string literal so the C
            # compiler unescapes them — the same treatment regular string
            # literals receive. Only '%' must be doubled so printf reads it as a
            # literal percent.
            text = part.text.replace("%", "%%")
            fmt_parts.append(text)
        elif isinstance(part, FStringExpr):
            fmt, arg = _lower_interpolation(gen, part, tmp, len(args), arg_decls)
            fmt_parts.append(fmt)
            args.append(arg)

    fmt_str = "".join(fmt_parts)

    # For simple cases with no args, just return a string literal
    if not args:
        return IRLiteral(text=f'"{fmt_str}"')

    # Build the snprintf expression sequence as a structured IRStmtExpr.
    len_var = f"{tmp}_len"
    buf_var = f"{tmp}_buf"

    fmt_literal = IRLiteral(text=f'"{fmt_str}"')
    snprintf_measure_args = [IRLiteral(text="NULL"), IRLiteral(text="0"),
                             fmt_literal] + args
    len_plus_1 = IRBinOp(left=IRVar(name=len_var), op="+",
                         right=IRLiteral(text="1"))

    stmts = arg_decls + [
        # int __len = snprintf(NULL, 0, "fmt", __arg0, ...);
        IRVarDecl(
            c_type=CType(text="int"), name=len_var,
            init=IRCall(callee="snprintf", args=snprintf_measure_args),
        ),
        # char* __buf = __btrc_str_track((char*)malloc(__len + 1));
        IRVarDecl(
            c_type=CType(text="char*"), name=buf_var,
            init=IRCall(callee="__btrc_str_track", args=[
                IRCast(target_type=CType(text="char*"),
                       expr=IRCall(callee="malloc", args=[len_plus_1])),
            ]),
        ),
        # snprintf(__buf, __len + 1, "fmt", __arg0, ...);
        IRExprStmt(expr=IRCall(
            callee="snprintf",
            args=[IRVar(name=buf_var), len_plus_1, fmt_literal] + args,
        )),
    ]

    return IRStmtExpr(stmts=stmts, result=IRVar(name=buf_var))


def _lower_interpolation(gen, part, tmp, index, arg_decls):
    """Lower one f-string interpolation.

    Returns (format_spec, ir_arg) where ir_arg is reused by both snprintf
    passes. A temp of the value's C type is appended to arg_decls so the
    expression evaluates exactly once.
    """
    from .expressions import lower_expr
    ir_value = lower_expr(gen, part.expression)
    arg_type = gen.analyzed.node_types.get(id(part.expression))
    fmt = format_spec_for_type(arg_type)
    # C type for the hoisting temp, kept in lockstep with the final fmt below.
    c_type = type_to_c(arg_type) if arg_type is not None else None

    if has_to_string(gen.analyzed, arg_type):
        ir_value = to_string_call(gen, arg_type, ir_value)
        fmt = "%s"
        c_type = "char*"

    # Force %s for string-producing expressions when type untracked
    if arg_type is None:
        expr = part.expression
        if isinstance(expr, (FStringLiteral, StringLiteral)):
            fmt = "%s"
        elif isinstance(expr, CallExpr):
            callee = expr.callee
            if isinstance(callee, FieldAccessExpr):
                if callee.field in ("toString", "str", "trim",
                                    "toUpper", "toLower", "substring",
                                    "replace", "repeat", "reverse",
                                    "capitalize", "join", "split"):
                    fmt = "%s"
        # Untracked: %s ⇒ a char* string, otherwise %d ⇒ an int.
        c_type = "char*" if fmt == "%s" else "int"

    if arg_type is not None and arg_type.base == "bool":
        # Evaluate the bool once into a bool temp, then format the (pure)
        # ternary `val ? "true" : "false"` from that temp in both passes.
        c_type = "bool"
        fmt = "%s"

    # Hoist the value into a temp so it is evaluated exactly once.
    arg_var = f"{tmp}_arg{index}"
    arg_decls.append(IRVarDecl(
        c_type=CType(text=c_type), name=arg_var, init=ir_value,
    ))
    ir_arg: IRExpr = IRVar(name=arg_var)

    if c_type == "bool":
        from ..nodes import IRTernary
        ir_arg = IRTernary(
            condition=ir_arg,
            true_expr=IRLiteral(text='"true"'),
            false_expr=IRLiteral(text='"false"'),
        )

    return fmt, ir_arg
