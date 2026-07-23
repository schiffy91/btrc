"""Expression and target dispatch at ordinary call sites."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..nodes import CType, IRCall, IRSizeof

if TYPE_CHECKING:
    from ...ast_nodes import CallExpr
    from .lowerer import IRLowerer
    from .types import CTypeRenderer


class CallDispatchLowerer:
    """Own call-target dispatch that crosses expression-lowering domains.

    Calls are recursively embedded expressions, so this owner is the single
    intentional bridge back into the main expression visitor.  Operand,
    hosted-result, ordering, and ownership policy live in their own owners.

    The next IR migration slice must turn expression/method/GPU dispatch into
    injected owners and remove this owner's ``lowerer`` reach-through.
    """

    def __init__(
        self,
        lowerer: IRLowerer,
        type_renderer: CTypeRenderer,
    ) -> None:
        self.lowerer = lowerer
        self.type_renderer = type_renderer

    def lower_expression(self, node):
        from .expressions import lower_expr

        return lower_expr(self.lowerer, node, self.type_renderer)

    def validate_arguments(self, node: CallExpr, params) -> None:
        from .aggregate_ownership import reject_rich_enum_owned_args
        from .callable_boundaries import reject_unsafe_managed_callback_arguments

        reject_rich_enum_owned_args(self.lowerer, node)
        reject_unsafe_managed_callback_arguments(
            self.lowerer,
            node,
            params=params,
        )

    def lower_direct_gpu_call(self, node: CallExpr):
        from .gpu import lower_direct_gpu_call

        return lower_direct_gpu_call(
            self.lowerer,
            node,
            self.type_renderer,
        )

    def lower_immediate_lambda_call(self, node: CallExpr):
        from .arguments import arg_names_for
        from .lambdas import lower_immediate_lambda_call

        return lower_immediate_lambda_call(
            self.lowerer,
            node.callee,
            node.args,
            arg_names_for(node, len(node.args)),
            self.type_renderer,
        )

    def lower_method_call(self, node: CallExpr):
        from .methods import lower_method_call

        return lower_method_call(
            self.lowerer,
            node,
            self.type_renderer,
        )

    def lower_special_identifier_call(
        self,
        node: CallExpr,
        args,
        *,
        source_call: bool,
    ):
        """Lower builtins and generated dispatch targets not in declarations."""
        name = node.callee.name
        from .gpu_cpu_builtins import lower_gpu_cpu_builtin

        gpu_builtin = (
            None
            if source_call
            else lower_gpu_cpu_builtin(
                self.lowerer,
                name,
                node.args,
                args,
            )
        )
        if gpu_builtin is not None:
            return gpu_builtin

        context = self.lowerer.context
        from .generic_intrinsics import lower_generic_intrinsic
        from .typed_operators import operator_context

        intrinsic = lower_generic_intrinsic(
            name,
            args,
            [context.type_of(arg) for arg in node.args],
            operator_context(self.lowerer, self.type_renderer),
        )
        if intrinsic is not None:
            return intrinsic

        from .gpu import is_gpu_function, lower_gpu_call

        if is_gpu_function(self.lowerer, name):
            from .arguments import arg_names_for

            return lower_gpu_call(
                self.lowerer,
                name,
                node.args,
                arg_names_for(node, len(node.args)),
                args,
                self.type_renderer,
                call=node,
            )
        if name == "Mutex" and not source_call:
            from .call_builtins import lower_mutex_constructor

            return lower_mutex_constructor(
                self.lowerer,
                node.args,
                args,
                self.type_renderer,
            )
        if name in context.analyzed.function_table:
            return None

        from .call_builtins import lower_len, lower_print

        if name == "print":
            return lower_print(
                self.lowerer,
                node.args,
                args,
                self.type_renderer,
            )
        if name == "printf":
            return IRCall(callee="printf", args=args)
        if name == "sizeof":
            return IRSizeof(operand=args[0] if node.args else CType(text="void"))
        if name == "len" and node.args:
            return lower_len(
                self.lowerer,
                args[0],
                context.type_of(node.args[0]),
            )
        return None


__all__ = ["CallDispatchLowerer"]
