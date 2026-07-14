"""Typed operators and structured lvalue updates in generic bodies."""

from __future__ import annotations

from ...nodes import IRBinOp, IRCommaExpr, IRExpr, IRUnaryOp, IRVar
from ..lvalues import LValueContext
from ..operator_context import operator_context
from ..updates import (
    UpdateContext,
    lower_assignment,
    lower_incdec,
)


class _UserGenericOperatorMixin:
    """Operator/update lowering shared by monomorphized generic methods."""

    def _binary_expr(self, expression) -> IRExpr:
        if expression.op not in {"??", "&&", "||"}:
            from ..operator_ownership import operator_rhs_keep

            left_type = self._resolve_expr_type(expression.left)
            right_type = self._resolve_expr_type(expression.right)
            keep_nodes = (
                [expression.right]
                if operator_rhs_keep(
                    self._gen,
                    left_type,
                    expression.op,
                    right_type,
                )
                else []
            )
            sequenced = self._sequence_owned_nodes(
                [expression.left, expression.right],
                expression,
                lambda: self._binary_expr_plain(expression),
                keep_nodes=keep_nodes,
            )
            if sequenced is not None:
                return sequenced
        return self._binary_expr_plain(expression)

    def _binary_expr_plain(self, expression) -> IRExpr:
        from ..operators import lower_overloaded_values
        from ..typed_operators import lower_typed_binary

        left = self._expr(expression.left)
        right = self._expr(expression.right)
        if expression.op == "??" and self._owns_expr(expression):
            from .user_emitter_ownership import normalize_owned_branch

            left = normalize_owned_branch(self, expression.left, left)
            right = normalize_owned_branch(self, expression.right, right)
        left_type = self._resolve_expr_type(expression.left)
        right_type = self._resolve_expr_type(expression.right)
        if self._gen:
            overloaded = lower_overloaded_values(
                self._gen,
                left_type,
                right_type,
                expression.op,
                left,
                right,
            )
            if overloaded is not None:
                return overloaded
        lowered = lower_typed_binary(
            expression.op,
            left,
            right,
            left_type,
            right_type,
            operator_context(self._gen, fresh_temp=self._fresh_temp),
        )
        if lowered is not None:
            return lowered
        return IRBinOp(left=left, op=expression.op, right=right)

    def _ternary_expr(self, expression) -> IRExpr:
        from ..typed_operators import lower_typed_ternary

        true_expr = self._expr(expression.true_expr)
        false_expr = self._expr(expression.false_expr)
        if self._owns_expr(expression):
            from .user_emitter_ownership import normalize_owned_branch

            true_expr = normalize_owned_branch(
                self,
                expression.true_expr,
                true_expr,
            )
            false_expr = normalize_owned_branch(
                self,
                expression.false_expr,
                false_expr,
            )
        return lower_typed_ternary(
            self._expr(expression.condition),
            true_expr,
            false_expr,
            self._resolve_expr_type(expression.true_expr),
            self._resolve_expr_type(expression.false_expr),
            operator_context(self._gen, fresh_temp=self._fresh_temp),
        )

    def _unary_expr(self, expression) -> IRExpr:
        from ....ast_nodes import FieldAccessExpr, IndexExpr

        if expression.op in {"++", "--"} and isinstance(
            expression.operand,
            (FieldAccessExpr, IndexExpr),
        ):
            nodes = [expression.operand.obj]
            if isinstance(expression.operand, IndexExpr):
                nodes.append(expression.operand.index)
            result_type = self._resolve_expr_type(expression)
            sequenced = self._sequence_owned_nodes(
                nodes,
                expression,
                lambda: self._unary_expr_plain(expression),
                promote_result=self._is_managed_type(result_type),
            )
            if sequenced is not None:
                return sequenced
        elif expression.op not in {"++", "--", "&", "*"}:
            sequenced = self._sequence_owned_nodes(
                [expression.operand],
                expression,
                lambda: self._unary_expr_plain(expression),
            )
            if sequenced is not None:
                return sequenced
        return self._unary_expr_plain(expression)

    def _unary_expr_plain(self, expression) -> IRExpr:
        if expression.op in {"++", "--"} and self._gen:
            result = lower_incdec(self._update_context(), expression)
            if self._mutates_self_storage(expression.operand):
                from ..arc_ops import invalidate_cycle_proof

                return IRCommaExpr(
                    expressions=[
                        invalidate_cycle_proof(self._gen, IRVar(name="self")),
                        result,
                    ]
                )
            return result
        return IRUnaryOp(
            op=expression.op,
            operand=self._expr(expression.operand),
            prefix=expression.prefix,
        )

    def _assignment_expr(self, expression) -> IRExpr:
        if not self._gen:
            return IRBinOp(
                left=self._expr(expression.target),
                op=expression.op,
                right=self._expr(expression.value),
            )
        target_type = self._resolve_expr_type(expression.target)
        if self._is_managed_type(target_type):
            from ..managed_local import mark_borrowed_cycle_seeds

            mark_borrowed_cycle_seeds(self._managed_vars_stack)
        from ....ast_nodes import FieldAccessExpr, IndexExpr

        target_nodes = []
        if isinstance(expression.target, FieldAccessExpr):
            target_nodes = [expression.target.obj]
        elif isinstance(expression.target, IndexExpr):
            target_nodes = [expression.target.obj, expression.target.index]
        if target_nodes:
            from ..assignment_ownership import virtual_assignment_target
            from ..ownership import owns_result

            result_type = self._resolve_expr_type(expression)
            rhs_supplies_result = bool(
                expression.op == "="
                and virtual_assignment_target(self._gen, expression.target)
                and owns_result(self._gen, expression.value)
            )
            sequenced = self._sequence_owned_nodes(
                target_nodes,
                expression,
                lambda: self._assignment_expr_plain(expression),
                promote_result=(
                    self._is_managed_type(result_type)
                    and not rhs_supplies_result
                ),
            )
            if sequenced is not None:
                return sequenced
        return self._assignment_expr_plain(expression)

    def _assignment_expr_plain(self, expression) -> IRExpr:
        from .user_emitter_local_arc import lower_generic_local_assignment

        local_arc = lower_generic_local_assignment(self, expression)
        if local_arc is not None:
            return local_arc
        from .user_emitter_field_arc import lower_generic_field_assignment

        field_arc = lower_generic_field_assignment(self, expression)
        if field_arc is not None:
            return field_arc
        result = lower_assignment(self._update_context(), expression)
        if self._mutates_self_storage(expression.target):
            from ..arc_ops import invalidate_cycle_proof

            return IRCommaExpr(
                expressions=[
                    invalidate_cycle_proof(self._gen, IRVar(name="self")),
                    result,
                ]
            )
        return result

    @staticmethod
    def _mutates_self_storage(target) -> bool:
        from ....ast_nodes import FieldAccessExpr, IndexExpr, SelfExpr

        if isinstance(target, SelfExpr):
            return True
        if isinstance(target, (FieldAccessExpr, IndexExpr)):
            return _UserGenericOperatorMixin._mutates_self_storage(target.obj)
        return False

    def _update_context(self) -> UpdateContext:
        from ....ast_nodes import FieldAccessExpr, SelfExpr
        from ..operators import lower_overloaded_values
        from ..upcast import upcast_class_pointer
        from ..updates import _lower_virtual_store_boundary

        analyzed = self._gen.analyzed
        lvalues = LValueContext(
            lower_expr=self._expr,
            type_of=self._resolve_expr_type,
            c_type=self._ttc,
            fresh_temp=self._fresh_temp,
            register_decl=self._func_var_decls.append,
            class_table=analyzed.class_table,
            direct_property=lambda target: bool(
                isinstance(target, FieldAccessExpr)
                and isinstance(target.obj, SelfExpr)
                and self._current_property_backing == target.field
            ),
        )
        return UpdateContext(
            lvalues=lvalues,
            operators=operator_context(self._gen, fresh_temp=self._fresh_temp),
            lower_overload=(
                lambda left_type, right_type, operator, left, right: lower_overloaded_values(
                    self._gen,
                    left_type,
                    right_type,
                    operator,
                    left,
                    right,
                )
            ),
            coerce_assignment=(
                lambda target_type, source_type, value: upcast_class_pointer(self._gen, target_type, source_type, value)
            ),
            lower_value=self._assignment_value,
            store_boundary=lambda node, plan: _lower_virtual_store_boundary(
                self._gen,
                node,
                plan,
                lower_value=self._assignment_value,
                coerce=lambda target_type, source_type, value: upcast_class_pointer(
                    self._gen, target_type, source_type, value
                ),
            ),
        )

    def _assignment_value(self, target_type, value) -> IRExpr:
        """Lower collection literals using the assignment target's type."""
        from ....ast_nodes import BraceInitializer, ListLiteral, MapLiteral

        if isinstance(value, (BraceInitializer, ListLiteral, MapLiteral)):
            target = self._mangle_type(target_type)
            if target:
                return self._collection_literal(target, value, target_type)
        return self._expr(value)


__all__ = ["_UserGenericOperatorMixin"]
