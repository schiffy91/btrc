"""Storage-correct locals in monomorphized generic method bodies."""

from __future__ import annotations

from ...nodes import (
    CType,
    IRExprStmt,
    IRInitializerList,
    IRLiteral,
    IRVar,
    IRVarDecl,
)


def generic_local_storage(declaration, emitter, resolved=None) -> dict[str, bool]:
    from ....qualifier_provenance import effective_outer_volatile

    type_expr = declaration.type
    represented_type = resolved or type_expr
    return {
        "is_static": bool(type_expr and type_expr.is_static),
        "is_extern": bool(type_expr and type_expr.is_extern),
        "is_volatile": bool(type_expr and type_expr.is_volatile),
        "effective_is_volatile": effective_outer_volatile(
            represented_type,
            emitter._gen.analyzed.typedef_table,
        ),
    }


def lower_generic_array_var_decl(emitter, declaration):
    """Lower a source array declarator without flattening it into a pointer."""

    from ....ast_nodes import BraceInitializer, CallExpr, ListLiteral
    from ....type_composition import strip_outer_storage
    from ..callable_boundaries import reject_aggregate_callable_initializer
    from ..gpu_dispatch import lower_gpu_output_declaration, output_gpu_call_name
    from ..gpu_outputs import safe_array_size
    from .user_callable_provenance import (
        generic_callable_return_abi,
    )
    from .user_emitter_bindings import next_source_binding_c_name
    from .user_gpu_dispatch import (
        generic_gpu_host,
        is_direct_generic_gpu_call,
    )

    resolved = emitter._resolve(declaration.type)
    reject_aggregate_callable_initializer(
        emitter._gen,
        resolved,
        declaration.initializer,
        callable_abi=lambda value: generic_callable_return_abi(emitter, value),
    )
    element_type = strip_outer_storage(declaration.type, array=True)
    element_c = emitter.resolve_c(element_type)
    binding_c_name = next_source_binding_c_name(emitter, declaration.name)
    size = emitter._expr(declaration.type.array_size) if declaration.type.array_size is not None else None
    initializer = declaration.initializer
    if isinstance(initializer, (BraceInitializer, ListLiteral)):
        from ..aggregate_ownership import reject_owned_elements

        reject_owned_elements(
            emitter._gen,
            initializer.elements,
            "a shallow C array",
        )
        init = IRInitializerList(elements=[emitter._expr(item) for item in initializer.elements])
        return [
            _track_array(
                emitter,
                declaration,
                resolved,
                binding_c_name,
                _array_declaration(
                    element_c,
                    binding_c_name,
                    size,
                    declaration,
                    init,
                    emitter=emitter,
                    resolved=resolved,
                ),
            )
        ]

    if size is None and initializer is None:
        if declaration.type.is_extern:
            ir_declaration = _array_declaration(
                element_c,
                binding_c_name,
                None,
                declaration,
                None,
                emitter=emitter,
                resolved=resolved,
            )
        else:
            ir_declaration = IRVarDecl(
                c_type=CType(text=f"{element_c}*"),
                name=binding_c_name,
                init=IRLiteral(text="NULL"),
                **generic_local_storage(declaration, emitter, resolved),
            )
        return [
            _track_array(
                emitter,
                declaration,
                resolved,
                binding_c_name,
                ir_declaration,
                has_capacity=False,
            )
        ]

    if (
        isinstance(initializer, CallExpr)
        and is_direct_generic_gpu_call(
            emitter,
            initializer,
        )
        and output_gpu_call_name(
            emitter._gen,
            initializer,
        )
        is not None
    ):
        plan = lower_gpu_output_declaration(
            emitter._gen,
            initializer,
            IRVar(name=binding_c_name),
            host=generic_gpu_host(emitter),
        )
        if size is None and plan.array_length is None:
            from ..errors import CodegenError

            raise CodegenError(f"GPU result array '{declaration.name}' has no dispatch length")
        logical_size = size or plan.array_length
        size_setup = []
        if size is not None:
            size_name = emitter._fresh_temp("__gpu_output_size")
            size_setup.append(
                IRVarDecl(
                    c_type=CType(text="int"),
                    name=size_name,
                    init=size,
                )
            )
            logical_size = IRVar(name=size_name)
        ir_declaration = _track_array(
            emitter,
            declaration,
            resolved,
            binding_c_name,
            _array_declaration(
                element_c,
                binding_c_name,
                safe_array_size(logical_size),
                declaration,
                None,
                emitter=emitter,
                resolved=resolved,
            ),
            logical_length=plan.array_length,
        )
        ordered_setup = [*size_setup, *plan.setup] if size is not None else [*plan.setup, *size_setup]
        return [
            *ordered_setup,
            ir_declaration,
            IRExprStmt(expr=plan.call),
        ]

    init = emitter._expr(initializer) if initializer is not None else None
    return [
        _track_array(
            emitter,
            declaration,
            resolved,
            binding_c_name,
            _array_declaration(
                element_c,
                binding_c_name,
                size,
                declaration,
                init,
                emitter=emitter,
                resolved=resolved,
            ),
        )
    ]


def _array_declaration(
    element_c,
    binding_c_name,
    size,
    source_declaration,
    initializer,
    *,
    emitter,
    resolved,
):
    return IRVarDecl(
        c_type=CType(text=element_c),
        name=binding_c_name,
        init=initializer,
        array_size=size,
        is_unsized_array=size is None,
        **generic_local_storage(
            source_declaration,
            emitter,
            resolved,
        ),
    )


def _track_array(
    emitter,
    declaration,
    resolved,
    binding_c_name,
    ir_declaration,
    *,
    has_capacity=True,
    logical_length=None,
):
    from ..c_array_scopes import declare_c_binding
    from .user_callable_provenance import bind_generic_local_callable
    from .user_emitter_scopes import declare_local

    declare_local(
        emitter,
        declaration.name,
        c_name=binding_c_name,
    )
    declare_c_binding(
        emitter,
        declaration.name,
        is_array=has_capacity,
        logical_length=logical_length,
    )
    emitter._var_types[declaration.name] = resolved
    bind_generic_local_callable(
        emitter,
        declaration.name,
        resolved,
        declaration.initializer,
    )
    emitter._func_var_decls.append(ir_declaration)
    return ir_declaration


__all__ = ["generic_local_storage", "lower_generic_array_var_decl"]
