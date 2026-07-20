"""Call-target resolution for conservative opaque-borrow effect proofs."""

from ..ast_nodes import FieldAccessExpr, Identifier, SelfExpr
from ..hosted_abi import (
    hosted_parameter_is_read_only_borrow,
)
from .opaque_borrow_effect_walk import raw_expression_mentions_parameter


class OpaqueBorrowEffectCallsMixin:
    def _raw_parameter_call_is_safe(self, call, name, owner, local_names) -> bool:
        if raw_expression_mentions_parameter(call.callee, name):
            return False
        declaration, unresolved = self._raw_borrow_call_target(
            call,
            owner,
            local_names,
        )
        for argument_index, argument in enumerate(call.args):
            if not self._raw_expression_carries_parameter(argument, name):
                continue
            if isinstance(call.callee, Identifier) and self._is_raw_lifetime_call(call) and argument_index == 0:
                return False
            if unresolved and self._raw_unresolved_call_is_borrow_only(
                call,
                argument_index,
            ):
                continue
            if unresolved or declaration is None:
                return False
            parameter_index = self._raw_bound_parameter_index(
                declaration,
                call,
                argument_index,
            )
            if parameter_index < 0 or not self._raw_parameter_is_borrow_only(
                declaration,
                parameter_index,
            ):
                return False
        return True

    @staticmethod
    def _raw_unresolved_call_is_borrow_only(call, argument_index):
        callee = call.callee
        return bool(
            isinstance(callee, Identifier)
            and hosted_parameter_is_read_only_borrow(
                callee.name,
                argument_index,
            )
        )

    def _raw_borrow_call_target(self, call, owner, local_names):
        callee = call.callee
        if isinstance(callee, Identifier):
            if callee.name in local_names:
                return None, False
            if self._hosted_call_uses_owned_symbol(
                call,
                local_names=local_names,
            ):
                return None, True
            declaration = self.function_table.get(callee.name)
            return declaration, declaration is None or declaration.body is None
        if not isinstance(callee, FieldAccessExpr):
            return None, False
        if isinstance(callee.obj, SelfExpr) and owner is not None:
            return owner.methods.get(callee.field), False
        if isinstance(callee.obj, Identifier):
            class_info = self.class_table.get(callee.obj.name)
            if class_info is not None:
                return class_info.methods.get(callee.field), False
        return None, False

    @staticmethod
    def _raw_bound_parameter_index(declaration, call, argument_index):
        if argument_index < len(call.arg_names) and call.arg_names[argument_index]:
            name = call.arg_names[argument_index]
            return next(
                (index for index, parameter in enumerate(declaration.params) if parameter.name == name),
                -1,
            )
        return argument_index


__all__ = ["OpaqueBorrowEffectCallsMixin"]
