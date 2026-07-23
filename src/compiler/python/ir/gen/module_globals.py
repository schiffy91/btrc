"""File-scope source storage lowering."""

from ...ast_nodes import BraceInitializer, ListLiteral
from ...qualifier_provenance import effective_outer_volatile
from ..nodes import CType, IRGlobalDecl, IRLiteral
from .types import CTypeRenderer


def emit_global_var(
    gen,
    declaration,
    type_renderer: CTypeRenderer,
    *,
    force_external=False,
) -> None:
    if declaration.initializer is not None:
        from .callable_boundaries import reject_persistent_callable_escape

        reject_persistent_callable_escape(
            gen,
            declaration.type,
            declaration.initializer,
            "global storage",
        )
    if _materialized_array(declaration):
        _emit_array_global(
            gen,
            declaration,
            type_renderer,
            force_external,
        )
        return
    from .aggregate_initializers import lower_static_initializer

    type_expr = declaration.type
    is_extern = bool(type_expr and type_expr.is_extern and not force_external)
    gen.module.global_decls.append(
        IRGlobalDecl(
            c_type=CType(text=type_renderer.render(type_expr) if type_expr else "int"),
            name=declaration.name,
            init=(
                lower_static_initializer(
                    gen,
                    declaration.initializer,
                    type_renderer,
                )
                if declaration.initializer and not is_extern
                else None
            ),
            is_static=not (is_extern or force_external),
            is_extern=is_extern,
            is_volatile=bool(type_expr and type_expr.is_volatile),
            effective_is_volatile=effective_outer_volatile(
                type_expr,
                gen.analyzed.typedef_table,
            ),
        )
    )


def _materialized_array(declaration) -> bool:
    type_expr = declaration.type
    return bool(
        type_expr
        and type_expr.is_array
        and (
            type_expr.array_size is not None
            or isinstance(declaration.initializer, (BraceInitializer, ListLiteral))
            or type_expr.is_extern
        )
    )


def _emit_array_global(
    gen,
    declaration,
    type_renderer: CTypeRenderer,
    force_external,
) -> None:
    from ...type_composition import strip_outer_storage
    from .aggregate_initializers import lower_static_initializer
    from .expressions import lower_expr

    type_expr = declaration.type
    element_type = strip_outer_storage(type_expr, array=True)
    is_extern = bool(type_expr.is_extern and not force_external)
    initializer = declaration.initializer
    gen.module.global_decls.append(
        IRGlobalDecl(
            c_type=CType(text=type_renderer.render(element_type)),
            name=declaration.name,
            init=(lower_static_initializer(gen, initializer, type_renderer) if initializer else None),
            array_size=(
                lower_expr(gen, type_expr.array_size, type_renderer)
                if type_expr.array_size is not None
                else IRLiteral(text=str(len(initializer.elements)))
                if initializer is not None
                else None
            ),
            is_unsized_array=type_expr.array_size is None and initializer is None,
            is_static=not (is_extern or force_external),
            is_extern=is_extern,
            is_volatile=bool(type_expr.is_volatile),
            effective_is_volatile=effective_outer_volatile(
                type_expr,
                gen.analyzed.typedef_table,
            ),
        )
    )


__all__ = ["emit_global_var"]
