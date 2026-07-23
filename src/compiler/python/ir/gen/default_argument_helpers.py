"""Declaration-scoped evaluators for source default arguments."""

from __future__ import annotations

from dataclasses import dataclass

from ...ast_nodes import (
    Block,
    CallExpr,
    FieldAccessExpr,
    Identifier,
    NewExpr,
    ReturnStmt,
    TypeExpr,
)
from ..nodes import CType, IRBlock, IRFunctionDecl, IRFunctionDef, IRParam
from .function_symbols import source_function_c_name
from .parameters import lower_source_param
from .type_resolution import canonical_type
from .types import CTypeRenderer, mangle_generic_type


@dataclass(frozen=True)
class DefaultTarget:
    declaration: object
    c_name: str
    owner_name: str = ""
    class_prefix: str = ""
    self_type: TypeExpr | None = None
    substitutions: dict | None = None


def ensure_default_helper(
    gen,
    call,
    params,
    param_index: int,
    type_renderer: CTypeRenderer,
    default_arguments,
) -> tuple[DefaultTarget, str]:
    """Emit one typed evaluator and return its target metadata and symbol."""

    target = _resolve_target(gen, call, params, param_index)
    symbol = f"__btrc_default_{target.c_name}_{param_index + 1}"
    emitted = getattr(gen, "_default_argument_helpers", None)
    if emitted is None:
        emitted = set()
        gen._default_argument_helpers = emitted
    if symbol in emitted:
        return target, symbol
    emitted.add(symbol)

    param = params[param_index]
    helper_params = _helper_params(
        gen,
        target,
        params,
        param_index,
        type_renderer,
    )
    gen.module.function_decls.append(
        IRFunctionDecl(
            name=symbol,
            return_type=CType(text=type_renderer.render(param.type)),
            params=list(helper_params),
            is_static=True,
        )
    )
    definition = (
        _emit_generic_helper(
            gen,
            target,
            symbol,
            params,
            param_index,
            helper_params,
            type_renderer,
            default_arguments,
        )
        if target.substitutions
        else _emit_ordinary_helper(
            gen,
            target,
            symbol,
            params,
            param_index,
            helper_params,
            type_renderer,
            default_arguments,
        )
    )
    gen.module.function_defs.append(definition)
    return target, symbol


def _resolve_target(gen, call, params, param_index: int) -> DefaultTarget:
    substitutions = dict(getattr(params[param_index], "default_type_map", None) or {})
    if isinstance(call, NewExpr):
        return _constructor_target(gen, call.type.base, substitutions)

    callee = call.callee if isinstance(call, CallExpr) else None
    if isinstance(callee, Identifier):
        class_info = gen.analyzed.class_table.get(callee.name)
        if class_info is not None:
            return _constructor_target(gen, callee.name, substitutions)
        declaration = gen.analyzed.function_table.get(callee.name)
        if declaration is not None:
            return DefaultTarget(
                declaration=declaration,
                c_name=source_function_c_name(gen.analyzed, declaration.name),
                substitutions=substitutions,
            )

    if isinstance(callee, FieldAccessExpr):
        from .rich_enum_calls import rich_enum_variant_target

        variant = rich_enum_variant_target(gen, call)
        if variant is not None:
            enum_name, declaration = variant
            return DefaultTarget(
                declaration=declaration,
                c_name=f"{enum_name}_{declaration.name}",
                substitutions=substitutions,
            )
        class_info = _receiver_class(gen, callee)
        method = class_info.methods.get(callee.field) if class_info else None
        if method is not None:
            owner_name = class_info.method_owners.get(callee.field, class_info.name)
            owner = gen.analyzed.class_table[owner_name]
            class_args = [substitutions[name] for name in owner.generic_params if name in substitutions]
            class_prefix = mangle_generic_type(owner_name, class_args) if class_args else owner_name
            c_name = f"{class_prefix}_{method.name}"
            if method.generic_params:
                from .generics.methods_mono import generic_method_instance_name

                method_args = tuple(substitutions[name] for name in method.generic_params)
                c_name = generic_method_instance_name(
                    owner_name,
                    tuple(class_args),
                    method.name,
                    method_args,
                )
            self_type = None
            if method.access != "class":
                self_type = TypeExpr(
                    base=owner_name,
                    generic_args=class_args,
                    pointer_depth=1,
                )
            return DefaultTarget(
                declaration=method,
                c_name=c_name,
                owner_name=owner_name,
                class_prefix=class_prefix,
                self_type=self_type,
                substitutions=substitutions,
            )
    from .errors import CodegenError

    raise CodegenError("cannot resolve declaration scope for a default argument")


def _constructor_target(gen, class_name: str, substitutions: dict) -> DefaultTarget:
    owner = gen.analyzed.class_table[class_name]
    class_args = [substitutions[name] for name in owner.generic_params if name in substitutions]
    prefix = mangle_generic_type(class_name, class_args) if class_args else class_name
    return DefaultTarget(
        declaration=owner.constructor,
        c_name=f"{prefix}_new",
        owner_name=class_name,
        class_prefix=prefix,
        substitutions=substitutions,
    )


def _receiver_class(gen, callee):
    receiver = callee.obj
    if isinstance(receiver, Identifier) and not gen.local_ownership_declared(receiver.name):
        direct = gen.analyzed.class_table.get(receiver.name)
        if direct is not None:
            return direct
    receiver_type = canonical_type(
        gen.analyzed.node_types.get(id(receiver)),
        gen.analyzed.typedef_table,
    )
    return gen.analyzed.class_table.get(receiver_type.base) if receiver_type else None


def _helper_params(gen, target, params, param_index, type_renderer):
    result = []
    if target.self_type is not None:
        result.append(
            IRParam(
                c_type=CType(text=type_renderer.render(target.self_type)),
                name="self",
            )
        )
    result.extend(
        lower_source_param(
            param,
            type_renderer.render,
            analyzed=gen.analyzed,
        )
        for param in params[:param_index]
    )
    return result


def _default_line_map(gen, target):
    if gen.declaration_line_map is None:
        return None
    source_file = getattr(target.declaration, "source_file", None) or gen.source_file
    return lambda source_line: gen.declaration_line_map(source_file, source_line)


def _emit_ordinary_helper(
    gen,
    target,
    symbol,
    params,
    param_index,
    helper_params,
    type_renderer,
    default_arguments,
):
    from .isolated_context import isolated_function_context
    from .statements import lower_block

    param = params[param_index]
    previous_class = gen.current_class
    previous_class_name = gen.current_class_name
    owner = gen.analyzed.class_table.get(target.owner_name)
    source_file = getattr(target.declaration, "source_file", None) or gen.source_file
    with isolated_function_context(
        gen,
        type_renderer.render(param.type),
        param.type,
    ):
        gen.current_class = owner
        gen.current_class_name = target.owner_name
        try:
            with default_arguments.scope(
                param,
                True,
                function_name=target.c_name,
                source_file=source_file,
                line_map=_default_line_map(gen, target),
            ):
                body = lower_block(
                    gen,
                    Block(statements=[ReturnStmt(value=param.default)]),
                    local_bindings=[
                        *(["self"] if target.self_type is not None else []),
                        *(parameter.name for parameter in params[:param_index]),
                    ],
                    callable_bindings=params[:param_index],
                    type_renderer=type_renderer,
                    default_arguments=default_arguments,
                )
        finally:
            gen.current_class = previous_class
            gen.current_class_name = previous_class_name
    return IRFunctionDef(
        name=symbol,
        return_type=CType(text=type_renderer.render(param.type)),
        params=list(helper_params),
        body=body,
        is_static=True,
    )


def _emit_generic_helper(
    gen,
    target,
    symbol,
    params,
    param_index,
    helper_params,
    type_renderer,
    default_arguments,
):
    from .generics.user_emitter import _UserGenericEmitter

    param = params[param_index]
    owner = gen.analyzed.class_table.get(target.owner_name)
    source_file = getattr(target.declaration, "source_file", None) or gen.source_file
    emitter = _UserGenericEmitter(
        target.substitutions,
        target.class_prefix,
        type_renderer,
        gen=gen,
        cls_info=owner,
        default_arguments=default_arguments,
    )
    emitter.reset_var_types(params[:param_index], param.type)
    if target.self_type is not None:
        emitter._var_types["self"] = target.self_type
    with default_arguments.scope(
        param,
        True,
        function_name=target.c_name,
        source_file=source_file,
        line_map=_default_line_map(gen, target),
    ):
        statements = emitter.emit_stmts([ReturnStmt(value=param.default)])
    return IRFunctionDef(
        name=symbol,
        return_type=CType(text=type_renderer.render(param.type)),
        params=list(helper_params),
        body=IRBlock(stmts=statements),
        is_static=True,
    )


__all__ = ["DefaultTarget", "ensure_default_helper"]
