"""F-string lowering for monomorphized generic method bodies."""

from __future__ import annotations

from ...nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRLiteral,
    IRStmtExpr,
    IRTernary,
    IRVar,
    IRVarDecl,
)
from ..stringable import has_to_string, to_string_call
from ..types import format_spec_for_type


class _UserGenericFStringMixin:
    def _fstring(self, node):
        from ....ast_nodes import FStringExpr, FStringText

        self._gen.use_helper("__btrc_str_track")
        self._gen.use_helper("__btrc_string_alloc")
        temp = self._fresh_temp("__fstr")
        format_parts = []
        declarations = []
        assignments = []
        arguments = []

        for part in node.parts:
            if isinstance(part, FStringText):
                format_parts.append(part.text.replace("%", "%%"))
            elif isinstance(part, FStringExpr):
                spec, argument = self._fstring_argument(
                    part.expression, temp, len(arguments), declarations, assignments
                )
                format_parts.append(spec)
                arguments.append(argument)

        format_text = "".join(format_parts)
        if not arguments:
            return IRLiteral(text=f'"{format_text}"')

        length_name = f"{temp}_len"
        buffer_name = f"{temp}_buf"
        format_literal = IRLiteral(text=f'"{format_text}"')
        length_plus_one = IRBinOp(
            left=IRCast(target_type=CType(text="size_t"), expr=IRVar(name=length_name)),
            op="+",
            right=IRLiteral(text="1"),
        )
        declarations.extend(
            [
                IRVarDecl(c_type=CType(text="int"), name=length_name),
                IRVarDecl(c_type=CType(text="char*"), name=buffer_name),
            ]
        )
        sequence = assignments + [
            IRBinOp(
                left=IRVar(name=length_name),
                op="=",
                right=IRCall(
                    callee="snprintf", args=[IRLiteral(text="NULL"), IRLiteral(text="0"), format_literal, *arguments]
                ),
            ),
            IRBinOp(
                left=IRVar(name=buffer_name),
                op="=",
                right=IRCall(
                    callee="__btrc_str_track",
                    args=[
                        IRCall(
                            callee="__btrc_string_alloc",
                            args=[IRVar(name=length_name)],
                            helper_ref="__btrc_string_alloc",
                        )
                    ],
                    helper_ref="__btrc_str_track",
                ),
            ),
            IRCall(callee="snprintf", args=[IRVar(name=buffer_name), length_plus_one, format_literal, *arguments]),
            IRVar(name=buffer_name),
        ]
        return IRStmtExpr(
            stmts=declarations,
            result=IRCommaExpr(expressions=sequence),
        )

    def _fstring_argument(self, expression, temp, index, declarations, assignments):
        from ....ast_nodes import CallExpr, FieldAccessExpr, FStringLiteral, StringLiteral

        value = self._expr(expression)
        value_type = self._resolve_expr_type(expression)
        if value_type is None and self._gen:
            value_type = self._gen.analyzed.node_types.get(id(expression))
            if value_type is not None:
                value_type = self._resolve(value_type)
        spec = format_spec_for_type(value_type)
        c_type = self.iter_value_c(value_type) if value_type is not None else None

        if value_type is not None and has_to_string(self._gen.analyzed, value_type):
            value = to_string_call(self._gen, value_type, value)
            spec = "%s"
            c_type = "char*"

        if value_type is None:
            if isinstance(expression, (FStringLiteral, StringLiteral)):
                spec = "%s"
            elif isinstance(expression, CallExpr):
                callee = expression.callee
                if isinstance(callee, FieldAccessExpr) and callee.field in {
                    "capitalize",
                    "join",
                    "repeat",
                    "replace",
                    "reverse",
                    "split",
                    "str",
                    "substring",
                    "toLower",
                    "toString",
                    "toUpper",
                    "trim",
                }:
                    spec = "%s"
            c_type = "char*" if spec == "%s" else "int"

        argument_name = f"{temp}_arg{index}"
        declarations.append(IRVarDecl(c_type=CType(text=c_type), name=argument_name))
        assignments.append(IRBinOp(left=IRVar(name=argument_name), op="=", right=value))
        argument = IRVar(name=argument_name)
        if value_type is not None and value_type.base == "bool":
            spec = "%s"
            argument = IRTernary(
                condition=argument,
                true_expr=IRLiteral(text='"true"'),
                false_expr=IRLiteral(text='"false"'),
            )
        return spec, argument
