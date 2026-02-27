"""F-string lowering: FStringLiteral → snprintf measuring + allocation + formatting."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import (
    CallExpr, FStringExpr, FStringLiteral, FStringText,
    FieldAccessExpr, StringLiteral, TypeExpr,
)
from ..nodes import IRCall, IRExpr, IRLiteral, IRRawExpr, IRVar
from .types import format_spec_for_type, is_string_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_fstring(gen: IRGenerator, node: FStringLiteral) -> IRExpr:
    """Lower an f-string to snprintf-based string building.

    Pattern:
        int __len = snprintf(NULL, 0, "fmt", args...);
        char* __buf = __btrc_str_track((char*)malloc(__len + 1));
        snprintf(__buf, __len + 1, "fmt", args...);
    """
    gen.use_helper("__btrc_str_track")

    # Build the format string and collect arguments
    fmt_parts = []
    args = []

    for part in node.parts:
        if isinstance(part, FStringText):
            # Escape special chars for printf
            text = part.text.replace("%", "%%").replace("\\", "\\\\")
            text = text.replace('"', '\\"').replace('\n', '\\n')
            fmt_parts.append(text)
        elif isinstance(part, FStringExpr):
            from .expressions import lower_expr
            ir_arg = lower_expr(gen, part.expression)
            arg_type = gen.analyzed.node_types.get(id(part.expression))
            fmt = format_spec_for_type(arg_type)

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

            if arg_type and arg_type.base == "bool":
                # bool → ternary: val ? "true" : "false"
                from ..nodes import IRTernary
                ir_arg = IRTernary(
                    condition=ir_arg,
                    true_expr=IRLiteral(text='"true"'),
                    false_expr=IRLiteral(text='"false"'),
                )
                fmt = "%s"

            fmt_parts.append(fmt)
            args.append(ir_arg)

    fmt_str = "".join(fmt_parts)

    # For simple cases with no args, just return a string literal
    if not args:
        return IRLiteral(text=f'"{fmt_str}"')

    # Build the snprintf expression sequence as a compound statement
    # ({int __len = snprintf(NULL, 0, "fmt", args);
    #   char* __buf = __btrc_str_track((char*)malloc(__len + 1));
    #   snprintf(__buf, __len + 1, "fmt", args); __buf;})
    tmp = gen.fresh_temp("__fstr")
    len_var = f"{tmp}_len"
    buf_var = f"{tmp}_buf"

    from .statements import _quick_text
    args_text = ", ".join(_quick_text(a) for a in args)

    # Emit as a GCC statement expression
    text = (
        f"({{ int {len_var} = snprintf(NULL, 0, \"{fmt_str}\", {args_text}); "
        f"char* {buf_var} = __btrc_str_track((char*)malloc({len_var} + 1)); "
        f"snprintf({buf_var}, {len_var} + 1, \"{fmt_str}\", {args_text}); "
        f"{buf_var}; }})"
    )
    return IRRawExpr(text=text)


def _expr_text(expr: IRExpr) -> str:
    """Get text representation for use in format strings."""
    if isinstance(expr, IRLiteral):
        return expr.text
    if isinstance(expr, IRVar):
        return expr.name
    if isinstance(expr, IRRawExpr):
        return expr.text
    # For complex expressions like ternaries, we need parens
    from ..nodes import IRTernary
    if isinstance(expr, IRTernary):
        c = _expr_text(expr.condition)
        t = _expr_text(expr.true_expr)
        f = _expr_text(expr.false_expr)
        return f"({c} ? {t} : {f})"
    from ..nodes import IRCall
    if isinstance(expr, IRCall):
        args = ", ".join(_expr_text(a) for a in expr.args)
        return f"{expr.callee}({args})"
    return "/* complex */"
