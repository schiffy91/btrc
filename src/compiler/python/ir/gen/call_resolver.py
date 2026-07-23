"""Call target, signature, and parameter resolution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ...ast_nodes import FieldAccessExpr, Identifier, LambdaExpr, Param, TypeExpr
from ...string_methods import STRING_METHODS
from ..nodes import CType, IRBinOp, IRCall, IRCommaExpr, IRExpr, IRStmtExpr, IRVar, IRVarDecl
from .call_parameter_contract import resolved_parameter
from .type_resolution import (
    canonical_type,
    function_pointer_signature,
    substitute_concrete_type,
)
from .types import CTypeRenderer


class CallResolver:
    """Resolve callable targets and concrete parameter contracts."""

    def __init__(
        self,
        context,
        expressions,
        type_renderer: CTypeRenderer,
    ) -> None:
        self.context = context
        self.expressions = expressions
        self.type_renderer = type_renderer

    def declaration(self, node):
        callee = node.callee
        if isinstance(callee, FieldAccessExpr):
            variant = self.rich_enum_target(node)
            if variant is not None:
                return variant[1]
            receiver_type = self.context.type_of(callee.obj)
            if receiver_type is not None:
                class_info = self.context.analyzed.class_table.get(receiver_type.base)
                if class_info is not None and callee.field in class_info.methods:
                    return class_info.methods[callee.field]
            if isinstance(callee.obj, Identifier) and not self.context.local_is_declared(callee.obj.name):
                class_info = self.context.analyzed.class_table.get(callee.obj.name)
                if class_info is not None:
                    return class_info.methods.get(callee.field)
            return None
        if not isinstance(callee, Identifier):
            return None
        if self.context.local_is_declared(callee.name):
            return None
        if id(node) in self.context.analyzed.hosted_call_ids:
            return None
        class_info = self.context.analyzed.class_table.get(callee.name)
        if class_info is not None:
            return class_info.constructor
        return self.context.analyzed.function_table.get(callee.name)

    def resolved_params(
        self,
        node,
        *,
        type_of=None,
        resolve_type=None,
        identifier_is_local=None,
    ):
        """Return concrete params for declarations, lambdas, builtins, or fnptrs."""
        type_of = type_of or self.context.type_of
        resolve_type = resolve_type or (lambda value: value)
        identifier_is_local = identifier_is_local or self.context.local_is_declared
        callee = node.callee
        if isinstance(callee, LambdaExpr):
            return [self._resolved_param(param, resolve_type) for param in callee.params]
        if isinstance(callee, Identifier) and identifier_is_local(callee.name):
            return self._params_from_signature(callee, type_of, resolve_type)

        variant = self.rich_enum_target(
            node,
            identifier_is_local=identifier_is_local,
        )
        if variant is not None:
            return [self._resolved_param(param, resolve_type) for param in variant[1].params]
        builtin = self._builtin_params(node, type_of, resolve_type)
        if builtin is not None:
            return builtin
        hosted = self._hosted_params(node, resolve_type)
        if hosted is not None:
            return hosted
        declaration = self._declaration_for_call(node, type_of)
        if declaration is not None:
            return self._resolve_declared_params(
                node,
                declaration.params,
                type_of,
                resolve_type,
            )
        return self._params_from_signature(callee, type_of, resolve_type)

    def callable_type(self, callee_node) -> TypeExpr | None:
        callee_type = self.context.type_of(callee_node)
        if callee_type is None and isinstance(callee_node, Identifier):
            callee_type = self.context.callable_type(callee_node.name)
            if callee_type is None:
                callee_type = self.context.analyzed.global_var_types.get(callee_node.name)
        return callee_type

    def callable_signature(self, callee_node) -> list[TypeExpr] | None:
        return function_pointer_signature(
            self.callable_type(callee_node),
            self.context.analyzed.typedef_table,
        )

    def callable_value_signature(self, callee_node) -> list[TypeExpr] | None:
        if not isinstance(callee_node, Identifier):
            return None
        if callee_node.name in self.context.callable_environments:
            return None
        if not (
            self.context.local_is_declared(callee_node.name)
            or callee_node.name in self.context.analyzed.global_var_types
        ):
            return None
        return self.callable_signature(callee_node)

    def rich_enum_target(self, node, *, identifier_is_local=None):
        """Resolve a lexical type-qualified rich-enum variant call."""
        callee = getattr(node, "callee", None)
        if not isinstance(callee, FieldAccessExpr) or not isinstance(
            callee.obj,
            Identifier,
        ):
            return None
        is_local = identifier_is_local or self.context.local_is_declared
        if is_local(callee.obj.name):
            return None
        declaration = self.context.analyzed.rich_enum_table.get(callee.obj.name)
        if declaration is None:
            return None
        variant = next(
            (candidate for candidate in declaration.variants if candidate.name == callee.field),
            None,
        )
        return (callee.obj.name, variant) if variant is not None else None

    def callable_field_signature(self, callee: FieldAccessExpr):
        """Resolve a callable field/property, including generic substitution."""
        analyzed = self.context.analyzed
        signature = function_pointer_signature(
            self.context.type_of(callee),
            analyzed.typedef_table,
        )
        if signature is not None:
            return signature
        if isinstance(callee.obj, Identifier):
            owner = analyzed.class_table.get(callee.obj.name)
            if owner is not None and not self.context.local_is_declared(callee.obj.name):
                member = owner.static_fields.get(callee.field)
                return function_pointer_signature(
                    member.type if member else None,
                    analyzed.typedef_table,
                )
        receiver = canonical_type(
            self.context.type_of(callee.obj),
            analyzed.typedef_table,
        )
        if receiver is None:
            return None
        owner = analyzed.class_table.get(receiver.base)
        if owner is None:
            return None
        member = owner.fields.get(callee.field) or owner.properties.get(callee.field)
        if member is None:
            return None
        member_type = member.type
        if owner.generic_params and receiver.generic_args:
            member_type = substitute_concrete_type(
                member_type,
                dict(zip(owner.generic_params, receiver.generic_args)),
                analyzed.typedef_table,
            )
        return function_pointer_signature(member_type, analyzed.typedef_table)

    def materialize_callee(
        self,
        callee_node,
        callee: IRExpr,
        signature: list[TypeExpr],
        args: list[IRExpr],
        *,
        callee_materialized=False,
        fresh_temp: Callable | None = None,
        record_decl: Callable[[IRVarDecl], None] | None = None,
        overridden: Callable[[object], bool] | None = None,
    ) -> IRExpr:
        is_overridden = overridden or (lambda node: id(node) in self.context.owning_overrides)
        if callee_materialized or not args or is_overridden(callee_node):
            return IRCall(callee=callee, args=args)
        temp = (fresh_temp or self.context.fresh_temp)("__btrc_callable")
        value = IRVar(name=temp)
        callable_type = TypeExpr(base="__fn_ptr", generic_args=signature)
        declaration = IRVarDecl(
            c_type=CType(text=self.type_renderer.render(callable_type)),
            name=temp,
        )
        (record_decl or self.context.record_declaration)(declaration)
        return IRStmtExpr(
            stmts=[declaration],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(left=value, op="=", right=callee),
                    IRCall(callee=value, args=args),
                ]
            ),
        )

    def lower_callee(self, callee_node, args) -> IRExpr:
        callee = self.expressions.lower_expression(callee_node)
        signature = self.callable_signature(callee_node)
        if signature is None:
            return IRCall(callee=callee, args=args)
        return self.materialize_callee(callee_node, callee, signature, args)

    def _hosted_params(self, node, resolve_type):
        callee = node.callee
        if not isinstance(callee, Identifier) or id(node) not in self.context.analyzed.hosted_call_ids:
            return None
        from ...hosted_abi import hosted_function

        spec = hosted_function(callee.name)
        if spec is None or spec.parameters is None:
            return None
        return [
            Param(type=resolve_type(shape.as_type_expr()), name=str(index))
            for index, shape in enumerate(spec.parameters)
        ]

    def _declaration_for_call(self, node, type_of):
        declaration = self.declaration(node)
        if declaration is not None:
            return declaration
        callee = node.callee
        if not isinstance(callee, FieldAccessExpr):
            return None
        receiver = canonical_type(
            type_of(callee.obj),
            self.context.analyzed.typedef_table,
        )
        cls = self.context.analyzed.class_table.get(receiver.base) if receiver else None
        return cls.methods.get(callee.field) if cls else None

    def _resolve_declared_params(self, node, params, type_of, resolve_type):
        substitutions = {}
        callee = node.callee
        if isinstance(callee, Identifier):
            cls = self.context.analyzed.class_table.get(callee.name)
            instance = canonical_type(type_of(node), self.context.analyzed.typedef_table)
            if cls and instance and cls.generic_params:
                substitutions.update(zip(cls.generic_params, instance.generic_args))
        elif isinstance(callee, FieldAccessExpr):
            receiver = canonical_type(
                type_of(callee.obj),
                self.context.analyzed.typedef_table,
            )
            cls = self.context.analyzed.class_table.get(receiver.base) if receiver else None
            if cls and receiver and cls.generic_params:
                substitutions.update(zip(cls.generic_params, receiver.generic_args))
            method = cls.methods.get(callee.field) if cls else None
            method_args = self.context.analyzed.generic_method_call_args.get(id(node), ())
            if method and method.generic_params:
                substitutions.update(zip(method.generic_params, method_args))
        return [
            resolved_parameter(
                param,
                resolve_type(
                    substitute_concrete_type(
                        param.type,
                        substitutions,
                        self.context.analyzed.typedef_table,
                    )
                    if substitutions
                    else param.type
                ),
                substitutions,
            )
            for param in params
        ]

    def _builtin_params(self, node, type_of, resolve_type):
        callee = node.callee
        functions = self.context.analyzed.function_table
        if isinstance(callee, Identifier) and callee.name == "Mutex" and callee.name not in functions:
            result_type = canonical_type(type_of(node), self.context.analyzed.typedef_table)
            value_type = (
                result_type.generic_args[0]
                if result_type is not None and result_type.base == "Mutex" and result_type.generic_args
                else type_of(node.args[0])
                if node.args
                else TypeExpr(base="int")
            )
            return [Param(type=resolve_type(value_type), name="value")]
        if isinstance(callee, Identifier) and callee.name == "print" and callee.name not in functions:
            from .stringable import has_to_string

            return [
                Param(
                    type=TypeExpr(base="string")
                    if has_to_string(
                        self.context.analyzed,
                        canonical_type(
                            type_of(arg),
                            self.context.analyzed.typedef_table,
                        ),
                    )
                    else resolve_type(type_of(arg) or TypeExpr(base="int")),
                    name=str(index),
                )
                for index, arg in enumerate(node.args)
            ]
        if not isinstance(callee, FieldAccessExpr):
            return None
        receiver = canonical_type(
            type_of(callee.obj),
            self.context.analyzed.typedef_table,
        )
        if receiver and receiver.base == "string":
            spec = STRING_METHODS.get(callee.field)
            if spec is not None:
                return [
                    Param(type=TypeExpr(base=name), name=str(index)) for index, name in enumerate(spec.argument_types)
                ]
        if receiver and receiver.base == "Mutex" and callee.field == "set" and receiver.generic_args:
            return [Param(type=resolve_type(receiver.generic_args[0]), name="value")]
        return None

    def _params_from_signature(self, callee, type_of, resolve_type):
        signature = self._callable_signature(callee, type_of)
        if signature is None:
            return []
        return [Param(type=resolve_type(param_type), name=str(index)) for index, param_type in enumerate(signature[1:])]

    def _callable_signature(self, callee, type_of):
        if isinstance(callee, FieldAccessExpr):
            signature = self.callable_field_signature(callee)
            if signature is not None:
                return signature
        callee_type = type_of(callee)
        if callee_type is None and isinstance(callee, Identifier):
            callee_type = self.context.callable_type(callee.name)
        return function_pointer_signature(
            callee_type,
            self.context.analyzed.typedef_table,
        )

    @staticmethod
    def _resolved_param(param, resolve_type):
        return replace(param, type=resolve_type(param.type))


__all__ = ["CallResolver"]
