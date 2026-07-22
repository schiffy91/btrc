"""Typed operators and structured lvalue updates in generic bodies."""

from __future__ import annotations

from ...nodes import IRBinOp, IRCommaExpr, IRExpr, IRVar
from ..lvalues import LValueContext
from ..operator_context import operator_context
from ..updates import (
    UpdateContext,
    lower_assignment,
)
from .core import _generic_lvalue_c_type


class _UserGenericOperatorMixin:
    """Operator/update lowering shared by monomorphized generic methods."""

    def _binary_expr(self, expression) -> IRExpr:
        from .user_emitter_binary import lower_generic_binary

        return lower_generic_binary(self, expression)

    def _binary_expr_plain(self, expression) -> IRExpr:
        from .user_emitter_binary import lower_generic_binary_plain

        return lower_generic_binary_plain(self, expression)

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
        from .user_emitter_unary import lower_generic_unary_plain

        return lower_generic_unary_plain(self, expression)

    def _assignment_expr(self, expression) -> IRExpr:
        if not self._gen:
            return IRBinOp(
                left=self._expr(expression.target),
                op=expression.op,
                right=self._expr(expression.value),
            )
        from .user_callable_provenance import reject_generic_erasing_callable_assignment

        reject_generic_erasing_callable_assignment(self, expression)
        target_type = self._resolve_expr_type(expression.target)
        if self._is_managed_type(target_type):
            from ..managed_local import mark_borrowed_cycle_seeds

            mark_borrowed_cycle_seeds(self._managed_vars_stack)
        from ..assignment_ownership import (
            assignment_target_operands,
            kept_target_operands,
            property_projection,
        )

        type_of = self._resolve_expr_type
        target_nodes = assignment_target_operands(
            expression.target,
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
        result = None
        if target_nodes:
            from ..assignment_result_ownership import virtual_assignment_rhs_owns_result
            from .user_index_targets import prepared_generic_index_targets

            result_type = self._resolve_expr_type(expression)
            from .user_gpu_dispatch import is_generic_gpu_output_assignment

            gpu_output = is_generic_gpu_output_assignment(self, expression)
            prepared_targets = prepared_generic_index_targets(self, expression)
            rhs_supplies_result = bool(
                expression.op == "="
                and virtual_assignment_rhs_owns_result(
                    self._gen,
                    expression.target,
                    expression.value,
                    type_of=self._resolve_expr_type,
                    owns=self._owns_expr,
                    direct_property=self._direct_property_target,
                )
            )
            sequenced = self._sequence_owned_nodes(
                target_nodes,
                expression,
                lambda: self._assignment_expr_plain(expression),
                keep_nodes=kept_target_operands(
                    expression.target,
                    target_nodes,
                    type_of=type_of,
                    is_managed=self._is_managed_type,
                    owns=self._owns_expr,
                ),
                promote_result=(self._is_managed_type(result_type) and not rhs_supplies_result),
                prepared_values=prepared_targets,
                void_result=gpu_output,
            )
            if sequenced is not None:
                result = sequenced
        if result is None:
            result = self._assignment_expr_plain(expression)
        from .user_callable_provenance import rebind_generic_local_callable

        rebind_generic_local_callable(self, expression)
        return result

    def _assignment_expr_plain(self, expression) -> IRExpr:
        from .user_gpu_dispatch import lower_generic_gpu_output_assignment

        gpu_assignment = lower_generic_gpu_output_assignment(self, expression)
        if gpu_assignment is not None:
            return gpu_assignment

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
        from ..operators import lower_overloaded_values
        from ..upcast import upcast_class_pointer
        from ..virtual_stores import lower_virtual_store_boundary

        analyzed = self._gen.analyzed
        lvalues = LValueContext(
            lower_expr=self._expr,
            type_of=self._resolve_expr_type,
            c_type=self._ttc,
            fresh_temp=self._fresh_temp,
            register_decl=self._func_var_decls.append,
            class_table=analyzed.class_table,
            target_c_type=lambda target, resolved: _generic_lvalue_c_type(self, target, resolved),
            direct_property=self._direct_property_target,
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
            store_boundary=lambda node, plan: lower_virtual_store_boundary(
                self._gen,
                node,
                plan,
                lower_value=self._assignment_value,
                coerce=lambda target_type, source_type, value: upcast_class_pointer(
                    self._gen, target_type, source_type, value
                ),
                render_type=self.iter_value_c,
                fresh_temp=self._fresh_temp,
                cleanup_active=self._exception_cleanup_active(),
                record_decl=self._func_var_decls.append,
                owns_result=self._owns_expr,
                prepare=lambda value, target_type: _prepare_generic_assignment(
                    self,
                    value,
                    target_type,
                ),
                activate_cleanup=self._activate_cleanup_registration,
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


def _prepare_generic_assignment(emitter, value, target_type):
    from ..prepared_values import prepare_generic_value

    return prepare_generic_value(
        emitter,
        value,
        target_type,
        lower_value=lambda expression: emitter._assignment_value(
            target_type,
            expression,
        ),
    )
