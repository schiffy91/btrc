"""Call lowering with explicit target resolution and lifetime boundaries."""

from __future__ import annotations

from ...ast_nodes import CallExpr, FieldAccessExpr, Identifier, LambdaExpr
from ...ownership_effects import owned_transfer_param_indices
from ...source_runtime_symbols import SOURCE_RUNTIME_HELPERS
from ...string_methods import STRING_METHODS
from ..nodes import (
    CType,
    IRAddressOf,
    IRCall,
    IRCast,
    IRExpr,
    IRVar,
)
from .arguments import arg_names_for
from .call_operands import CallOperandPlanner
from .call_resolver import CallResolver
from .errors import CodegenError
from .function_symbols import source_function_c_name
from .lowering_context import LoweringContext
from .type_resolution import canonical_type
from .types import CTypeRenderer


class CallLowerer:
    """Lower source calls while preserving language order and ownership."""

    def __init__(
        self,
        context: LoweringContext,
        ownership,
        hosted_results,
        arguments,
        dispatch,
        type_renderer: CTypeRenderer,
        default_arguments,
    ) -> None:
        self.context = context
        self.ownership = ownership
        self.hosted_results = hosted_results
        self.arguments = arguments
        self.dispatch = dispatch
        self.type_renderer = type_renderer
        self.resolver = CallResolver(context, dispatch, type_renderer)
        self.operands = CallOperandPlanner(
            context,
            ownership,
            self.resolver,
            arguments,
            hosted_results,
            type_renderer,
            default_arguments,
        )

    def lower(self, node: CallExpr) -> IRExpr:
        """Lower a call through a single-evaluation managed boundary."""
        params = self.resolver.resolved_params(node)
        self.dispatch.validate_arguments(node, params)
        if isinstance(node.callee, FieldAccessExpr) and node.callee.optional:
            return self._lower_plain(node, params)
        direct_gpu = self.dispatch.lower_direct_gpu_call(node)
        if direct_gpu is not None:
            return direct_gpu

        declaration = self.resolver.declaration(node)
        result_conversion = self.hosted_results.requested_conversion(node)
        callable_field = bool(
            isinstance(node.callee, FieldAccessExpr) and self.resolver.callable_field_signature(node.callee) is not None
        )
        receiver = None if callable_field else self._instance_receiver(node)
        operands, needs_boundary = self.operands.plan(
            params,
            node.args,
            self._arg_names(node),
            receiver=receiver,
            callee=(node.callee if callable_field else self._evaluated_callee(node)),
            transferred_params=owned_transfer_param_indices(declaration),
            pin_receiver=self.ownership.receiver_pin_required(
                receiver,
                declared_call=declaration is not None,
            ),
            force_order=self._language_ordered_call(node, declaration),
            call=node,
        )
        if not needs_boundary:
            return self._with_result_conversion(
                node,
                self._lower_plain(node, params),
                result_conversion,
            )

        result_type = result_conversion[1] if result_conversion is not None else self.context.type_of(node)

        def build_call(overrides):
            with self.context.operand_scope(overrides):
                return self._with_result_conversion(
                    node,
                    self._lower_plain(node, params),
                    result_conversion,
                )

        return self.ownership.boundaries.sequence(
            operands,
            lower_expr=self.dispatch.lower_expression,
            build_call=build_call,
            result_c_type=(self.type_renderer.render(result_type) if result_type is not None else None),
            result_type=result_type,
            opaque_result=result_type is None,
            opaque_result_site=node,
            promote_result=False,
            result_owned=bool(result_conversion is not None or self.ownership.owns_result(node)),
        )

    def _lower_plain(self, node: CallExpr, params=None) -> IRExpr:
        callee = node.callee
        if isinstance(callee, LambdaExpr):
            return self.dispatch.lower_immediate_lambda_call(node)
        if isinstance(callee, FieldAccessExpr):
            return self.dispatch.lower_method_call(node)
        if not isinstance(callee, Identifier):
            return self.resolver.lower_callee(
                callee,
                [self.dispatch.lower_expression(arg) for arg in node.args],
            )

        name = callee.name
        args = [self.dispatch.lower_expression(arg) for arg in node.args]
        environment = self.context.callable_environment(name)
        if environment:
            function_name, environment_name = environment
            args.append(
                IRCast(
                    target_type=CType(text="void*"),
                    expr=IRAddressOf(expr=IRVar(name=environment_name)),
                )
            )
            return IRCall(callee=function_name, args=args)
        if self.context.local_is_declared(name) or name in self.context.analyzed.global_var_types:
            return self.resolver.lower_callee(callee, args)

        source_call = bool(
            name in self.context.analyzed.function_table and id(node) not in self.context.analyzed.hosted_call_ids
        )
        if name == "gpu_id" and not source_call and self.context.gpu_cpu_index:
            return IRVar(name=self.context.gpu_cpu_index)
        if name in SOURCE_RUNTIME_HELPERS:
            self.context.helpers.use(name)
            return IRCall(callee=name, args=args, helper_ref=name)

        special = self.dispatch.lower_special_identifier_call(
            node,
            args,
            source_call=source_call,
        )
        if special is not None:
            return special
        if name in self.context.analyzed.class_table:
            return self._lower_constructor_call(
                node,
                params if params is not None else self.resolver.resolved_params(node),
                args,
            )
        if source_call:
            declaration = self.context.analyzed.function_table.get(name)
            if declaration and declaration.params:
                args = self.arguments.order(
                    declaration.params,
                    node.args,
                    self._arg_names(node),
                    args,
                )
        return IRCall(
            callee=source_function_c_name(self.context.analyzed, name, node),
            args=args,
        )

    def _lower_constructor_call(
        self,
        node: CallExpr,
        params,
        args: list[IRExpr],
    ) -> IRExpr:
        class_name = node.callee.name
        class_info = self.context.analyzed.class_table[class_name]
        instance_type = self.context.type_of(node)
        callee_prefix = class_name
        if class_info.generic_params:
            if (
                instance_type is None
                or instance_type.base != class_name
                or len(instance_type.generic_args) != len(class_info.generic_params)
            ):
                raise CodegenError(f"generic constructor '{class_name}()' has no concrete analyzed call type")
            callee_prefix = self.type_renderer.type_identity.specialization_symbol(
                class_name,
                instance_type.generic_args,
            )
        if params:
            args = self.arguments.order(
                params,
                node.args,
                self._arg_names(node),
                args,
            )
        return IRCall(callee=f"{callee_prefix}_new", args=args)

    def _instance_receiver(self, node: CallExpr):
        if not isinstance(node.callee, FieldAccessExpr):
            return None
        receiver = node.callee.obj
        if isinstance(receiver, Identifier) and (
            receiver.name in self.context.analyzed.class_table or receiver.name in self.context.analyzed.rich_enum_table
        ):
            return None
        return receiver

    def _evaluated_callee(self, node: CallExpr):
        callee = node.callee
        if isinstance(callee, Identifier):
            return callee if self.resolver.callable_value_signature(callee) is not None else None
        if isinstance(callee, (FieldAccessExpr, LambdaExpr)):
            return None
        return callee

    def _language_ordered_call(self, node: CallExpr, declaration) -> bool:
        if declaration is not None:
            return True
        if id(node) in self.context.analyzed.hosted_call_ids:
            return True
        if isinstance(node.callee, Identifier) and node.callee.name in {
            "print",
            "printf",
            "Mutex",
        }:
            return True
        if isinstance(node.callee, FieldAccessExpr):
            receiver = node.callee.obj
            if isinstance(receiver, Identifier) and receiver.name in self.context.analyzed.rich_enum_table:
                return True
            receiver_type = canonical_type(
                self.context.type_of(receiver),
                self.context.analyzed.typedef_table,
            )
            if self.type_renderer.type_identity.is_scalar_string(receiver_type) and node.callee.field in STRING_METHODS:
                return True
            if self.ownership.types.is_mutex(receiver_type):
                return True
        return self.resolver.callable_signature(node.callee) is not None

    def _with_result_conversion(self, node, value, conversion):
        if conversion is None:
            return value
        return self.hosted_results.lower_conversion(
            value,
            conversion[0],
        )

    @staticmethod
    def _arg_names(node: CallExpr) -> list[str]:
        return arg_names_for(node, len(node.args))


__all__ = ["CallLowerer"]
