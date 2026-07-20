"""Resolved parameter contracts for every callable source shape."""

from __future__ import annotations

from dataclasses import replace

from ...ast_nodes import FieldAccessExpr, Identifier, LambdaExpr, Param, TypeExpr
from ...string_methods import STRING_METHODS
from .call_parameter_contract import resolved_parameter
from .type_resolution import (
    canonical_type,
    function_pointer_signature,
    substitute_concrete_type,
)


def resolved_params_for_call(
    gen,
    node,
    *,
    type_of=None,
    resolve_type=None,
    identifier_is_local=None,
):
    """Return concrete params for declarations, lambdas, builtins, or fnptrs."""
    type_of = type_of or (lambda value: gen.analyzed.node_types.get(id(value)))
    resolve_type = resolve_type or (lambda value: value)
    identifier_is_local = identifier_is_local or gen.local_ownership_declared
    callee = node.callee

    if isinstance(callee, LambdaExpr):
        return [_resolved_param(param, resolve_type) for param in callee.params]
    if isinstance(callee, Identifier) and identifier_is_local(callee.name):
        signature = _callable_signature(gen, callee, type_of)
        if signature is None:
            return []
        return [Param(type=resolve_type(param_type), name=str(index)) for index, param_type in enumerate(signature[1:])]

    from .rich_enum_calls import rich_enum_variant_target

    variant = rich_enum_variant_target(
        gen,
        node,
        identifier_is_local=identifier_is_local,
    )
    if variant is not None:
        return [_resolved_param(param, resolve_type) for param in variant[1].params]

    builtin = _builtin_params(gen, node, type_of, resolve_type)
    if builtin is not None:
        return builtin

    hosted = _hosted_params(gen, node, resolve_type)
    if hosted is not None:
        return hosted

    declaration = _declaration_for_call(gen, node, type_of)
    if declaration is not None:
        return _resolve_declared_params(gen, node, declaration.params, type_of, resolve_type)

    signature = _callable_signature(gen, callee, type_of)
    if signature is not None:
        return [Param(type=resolve_type(param_type), name=str(index)) for index, param_type in enumerate(signature[1:])]
    return []


def _hosted_params(gen, node, resolve_type):
    """Materialize exact header ABI parameters for lifetime planning."""
    callee = node.callee
    if not isinstance(callee, Identifier) or id(node) not in gen.analyzed.hosted_call_ids:
        return None
    from ...hosted_abi import hosted_function

    spec = hosted_function(callee.name)
    if spec is None or spec.parameters is None:
        return None
    return [
        Param(type=resolve_type(shape.as_type_expr()), name=str(index)) for index, shape in enumerate(spec.parameters)
    ]


def _declaration_for_call(gen, node, type_of):
    from .call_effects import callable_for_call

    declaration = callable_for_call(gen, node)
    if declaration is not None:
        return declaration
    callee = node.callee
    if not isinstance(callee, FieldAccessExpr):
        return None
    receiver = canonical_type(type_of(callee.obj), gen.analyzed.typedef_table)
    cls = gen.analyzed.class_table.get(receiver.base) if receiver else None
    return cls.methods.get(callee.field) if cls else None


def _resolve_declared_params(gen, node, params, type_of, resolve_type):
    substitutions = {}
    callee = node.callee
    if isinstance(callee, Identifier):
        cls = gen.analyzed.class_table.get(callee.name)
        instance = canonical_type(type_of(node), gen.analyzed.typedef_table)
        if cls and instance and cls.generic_params:
            substitutions.update(zip(cls.generic_params, instance.generic_args))
    elif isinstance(callee, FieldAccessExpr):
        receiver = canonical_type(type_of(callee.obj), gen.analyzed.typedef_table)
        cls = gen.analyzed.class_table.get(receiver.base) if receiver else None
        if cls and receiver and cls.generic_params:
            substitutions.update(zip(cls.generic_params, receiver.generic_args))
        method = cls.methods.get(callee.field) if cls else None
        method_args = gen.analyzed.generic_method_call_args.get(id(node), ())
        if method and method.generic_params:
            substitutions.update(zip(method.generic_params, method_args))

    result = []
    for param in params:
        param_type = (
            substitute_concrete_type(
                param.type,
                substitutions,
                gen.analyzed.typedef_table,
            )
            if substitutions
            else param.type
        )
        result.append(
            resolved_parameter(
                param,
                resolve_type(param_type),
                substitutions,
            )
        )
    return result


def _builtin_params(gen, node, type_of, resolve_type):
    callee = node.callee
    if isinstance(callee, Identifier) and callee.name == "Mutex" and callee.name not in gen.analyzed.function_table:
        result_type = canonical_type(type_of(node), gen.analyzed.typedef_table)
        value_type = (
            result_type.generic_args[0]
            if result_type is not None and result_type.base == "Mutex" and result_type.generic_args
            else type_of(node.args[0])
            if node.args
            else TypeExpr(base="int")
        )
        return [Param(type=resolve_type(value_type), name="value")]
    if isinstance(callee, Identifier) and callee.name == "print" and callee.name not in gen.analyzed.function_table:
        from .stringable import has_to_string

        return [
            Param(
                type=TypeExpr(base="string")
                if has_to_string(gen.analyzed, canonical_type(type_of(arg), gen.analyzed.typedef_table))
                else resolve_type(type_of(arg) or TypeExpr(base="int")),
                name=str(index),
            )
            for index, arg in enumerate(node.args)
        ]
    if not isinstance(callee, FieldAccessExpr):
        return None
    receiver = canonical_type(type_of(callee.obj), gen.analyzed.typedef_table)
    if receiver and receiver.base == "string":
        spec = STRING_METHODS.get(callee.field)
        if spec is not None:
            return [Param(type=TypeExpr(base=name), name=str(index)) for index, name in enumerate(spec.argument_types)]
    if receiver and receiver.base == "Mutex" and callee.field == "set" and receiver.generic_args:
        return [Param(type=resolve_type(receiver.generic_args[0]), name="value")]
    return None


def _callable_signature(gen, callee, type_of):
    if isinstance(callee, FieldAccessExpr):
        from .callable_fields import callable_field_signature

        signature = callable_field_signature(gen, callee)
        if signature is not None:
            return signature
    callee_type = type_of(callee)
    if callee_type is None and isinstance(callee, Identifier):
        callee_type = gen._callable_types.get(callee.name)
    return function_pointer_signature(callee_type, gen.analyzed.typedef_table)


def _resolved_param(param, resolve_type):
    return replace(param, type=resolve_type(param.type))


__all__ = ["resolved_params_for_call"]
