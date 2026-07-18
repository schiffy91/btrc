"""Ownership classification for expressions in generic specializations."""

from __future__ import annotations


class _UserGenericOwnershipMixin:
    def _owns_expr(self, expression):
        from ....ast_nodes import (
            AssignExpr,
            BinaryExpr,
            BraceInitializer,
            CallExpr,
            CastExpr,
            FieldAccessExpr,
            FStringExpr,
            FStringLiteral,
            IndexExpr,
            ListLiteral,
            MapLiteral,
            NewExpr,
            NullLiteral,
            TernaryExpr,
            UnaryExpr,
        )

        if expression is None or not self._gen:
            return False
        result_type = self._resolve_expr_type(expression)
        if not self._is_managed_type(result_type):
            return False
        if isinstance(
            expression,
            (NewExpr, BraceInitializer, ListLiteral, MapLiteral),
        ):
            return True
        if isinstance(expression, FStringLiteral):
            return any(isinstance(part, FStringExpr) for part in expression.parts)
        if isinstance(expression, CastExpr):
            return self._owns_expr(expression.expr)
        if isinstance(expression, CallExpr):
            if self._is_string_type(result_type):
                return self._string_call_owns_result(expression)
            return self._known_language_call(expression)
        if isinstance(expression, AssignExpr):
            from ..assignment_result_ownership import virtual_assignment_rhs_owns_result

            rhs_owned = virtual_assignment_rhs_owns_result(
                self._gen,
                expression.target,
                expression.value,
                type_of=self._resolve_expr_type,
                owns=self._owns_expr,
            )

            return bool(
                (
                    isinstance(expression.target, (FieldAccessExpr, IndexExpr))
                    and (
                        self._owns_expr(expression.target.obj)
                        or self._assignment_pins_borrowed_target(expression.target)
                    )
                )
                or (expression.op == "=" and rhs_owned)
            )
        if isinstance(expression, (FieldAccessExpr, IndexExpr)):
            custom_getter = False
            if isinstance(expression, FieldAccessExpr):
                from ....class_storage import custom_property_getter

                custom_getter = custom_property_getter(
                    self._gen.analyzed.class_table,
                    self._resolve_expr_type(expression.obj),
                    expression.field,
                )
            return self._projection_is_call(expression) or custom_getter or self._owns_expr(expression.obj)
        branches = None
        if isinstance(expression, TernaryExpr):
            branches = (expression.true_expr, expression.false_expr)
        elif isinstance(expression, BinaryExpr) and expression.op == "??":
            branches = (expression.left, expression.right)
        if branches is not None:
            return any(self._owns_expr(branch) for branch in branches) and all(
                isinstance(branch, NullLiteral) or self._is_managed_type(self._resolve_expr_type(branch))
                for branch in branches
            )
        if isinstance(expression, BinaryExpr):
            if (
                expression.op == "+"
                and self._is_string_type(result_type)
                and self._is_string_type(self._resolve_expr_type(expression.left))
                and self._is_string_type(self._resolve_expr_type(expression.right))
            ):
                return True
            return self._overloaded_result_is_owned(
                expression.left,
                expression.op,
            )
        if isinstance(expression, UnaryExpr):
            return self._overloaded_result_is_owned(
                expression.operand,
                expression.op,
                unary=True,
            )
        return False

    def _assignment_pins_borrowed_target(self, target):
        from ..assignment_ownership import (
            assignment_target_operands,
            kept_target_operands,
            property_projection,
        )

        type_of = self._resolve_expr_type
        operands = assignment_target_operands(
            target,
            stabilize_receiver=lambda receiver: bool(
                self._owns_expr(receiver)
                or self._is_managed_type(type_of(receiver))
                or property_projection(
                    receiver,
                    type_of=type_of,
                    class_table=self._gen.analyzed.class_table,
                )
            ),
        )
        return bool(
            kept_target_operands(
                target,
                operands,
                type_of=type_of,
                is_managed=self._is_managed_type,
                owns=self._owns_expr,
            )
        )

    def _known_language_call(self, expression):
        from ....ast_nodes import FieldAccessExpr, Identifier, SelfExpr

        callee = expression.callee
        if isinstance(callee, Identifier):
            return bool(
                callee.name == "Mutex"
                or callee.name in self._gen.analyzed.class_table
                or callee.name in self._gen.analyzed.function_table
            )
        if not isinstance(callee, FieldAccessExpr):
            return False
        if isinstance(callee.obj, SelfExpr):
            return bool(self._cls_info and callee.field in self._cls_info.methods)
        receiver_type = self._resolve_expr_type(callee.obj)
        if receiver_type is not None and receiver_type.base == "Mutex":
            return callee.field == "get"
        class_info = self._gen.analyzed.class_table.get(receiver_type.base) if receiver_type is not None else None
        return bool(class_info and callee.field in class_info.methods)

    def _string_call_owns_result(self, expression):
        from ....ast_nodes import FieldAccessExpr, Identifier

        if self._known_language_call(expression):
            return True
        callee = expression.callee
        if isinstance(callee, Identifier):
            return callee.name in {
                "__btrc_string_alloc",
                "__btrc_string_adopt",
                "__btrc_str_track",
            }
        if not isinstance(callee, FieldAccessExpr):
            return False
        receiver_type = self._resolve_expr_type(callee.obj)
        if self._is_string_type(receiver_type):
            from ....string_methods import STRING_METHODS

            method = STRING_METHODS.get(callee.field)
            return bool(method and method.tracked)
        if callee.field != "toString" or receiver_type is None:
            return False
        return bool(receiver_type.base != "bool" and receiver_type.base not in self._gen.analyzed.enum_table)

    def _overloaded_result_is_owned(
        self,
        operand,
        operator: str,
        *,
        unary: bool = False,
    ) -> bool:
        operand_type = self._resolve_expr_type(operand)
        class_info = self._gen.analyzed.class_table.get(operand_type.base) if operand_type is not None else None
        magic = {
            "+": "__add__",
            "-": "__sub__",
            "*": "__mul__",
            "/": "__div__",
            "%": "__mod__",
        }.get(operator)
        if unary:
            magic = "__neg__" if operator == "-" else None
        return bool(class_info and magic in class_info.methods)

    def _projection_is_call(self, expression):
        from ....ast_nodes import IndexExpr
        from ....index_protocol import indexed_protocol_info

        receiver_type = self._resolve_expr_type(expression.obj)
        if receiver_type is None:
            return False
        if isinstance(expression, IndexExpr):
            return (
                indexed_protocol_info(
                    receiver_type,
                    self._gen.analyzed.class_table,
                    method="get",
                )
                is not None
            )
        return False

    def _is_managed_type(self, type_expr):
        if not self._gen:
            return False
        from ..managed_values import is_managed_type

        return is_managed_type(self._gen, type_expr)

    def _is_string_type(self, type_expr):
        if not self._gen:
            return False
        from ..managed_values import is_string_type

        return is_string_type(self._gen, type_expr)

    @staticmethod
    def _require_operand_type(type_expr):
        if type_expr is not None:
            return
        from ..errors import CodegenError

        raise CodegenError("generic managed sequencing requires concrete operand types")


def normalize_owned_branch(emitter, expression, lowered):
    """Retain a borrowed conditional branch when the result owns +1."""
    from ....ast_nodes import NullLiteral

    if isinstance(expression, NullLiteral) or emitter._owns_expr(expression):
        return lowered
    type_expr = emitter._resolve_expr_type(expression)
    if not emitter._is_managed_type(type_expr):
        return lowered
    from ...nodes import CType, IRBinOp, IRCommaExpr, IRStmtExpr, IRVar, IRVarDecl
    from ..managed_values import retain_value

    declaration = IRVarDecl(
        c_type=CType(text=emitter.iter_value_c(type_expr)),
        name=emitter._fresh_temp("__btrc_promoted_branch"),
    )
    emitter._func_var_decls.append(declaration)
    value = IRVar(name=declaration.name)
    return IRStmtExpr(
        stmts=[declaration],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(left=value, op="=", right=lowered),
                retain_value(emitter._gen, value, type_expr),
                value,
            ]
        ),
    )


__all__ = ["_UserGenericOwnershipMixin", "normalize_owned_branch"]
