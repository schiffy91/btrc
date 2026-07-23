"""Lower fixed and inferred-size C array variable declarations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import BraceInitializer, CallExpr, ListLiteral, VarDeclStmt
from ..nodes import (
    CType,
    IRExprStmt,
    IRInitializerList,
    IRLiteral,
    IRStmt,
    IRVar,
    IRVarDecl,
)
from .expressions import lower_expr
from .types import type_to_c

if TYPE_CHECKING:
    from .lowerer import IRLowerer


def lower_array_var_decl(gen: IRLowerer, node: VarDeclStmt, storage: dict[str, bool]) -> list[IRStmt]:
    """Lower an array declaration, including direct GPU-result readback."""
    from ...type_composition import strip_outer_storage

    base_type = strip_outer_storage(node.type, array=True)
    base_c = type_to_c(base_type)
    # Reserve the declaration identity before lowering branch-specific setup,
    # but do not activate it: an array initializer resolves in the enclosing
    # source scope just like an ordinary local initializer.
    binding_c_name = gen.next_source_binding_c_name(node.name)
    explicit_size = lower_expr(gen, node.type.array_size) if node.type.array_size else None

    if isinstance(node.initializer, (BraceInitializer, ListLiteral)):
        from .aggregate_ownership import reject_owned_elements

        reject_owned_elements(
            gen,
            node.initializer.elements,
            "a shallow C array",
        )
        elements = [lower_expr(gen, item) for item in node.initializer.elements]
        gen.declare_local_ownership(node.name, c_name=binding_c_name)
        declaration = _declaration(
            base_c,
            binding_c_name,
            explicit_size,
            storage,
            IRInitializerList(elements=elements),
        )
        return [_track(gen, declaration, node.name)]

    if explicit_size is None and node.initializer is None:
        if storage.get("is_extern"):
            declaration = _declaration(
                base_c,
                binding_c_name,
                None,
                storage,
                None,
            )
            gen.context.function_declarations.append(declaration)
            from .c_array_scopes import declare_c_binding

            # This is a real incomplete C array, but it has no provable capacity.
            declare_c_binding(gen, node.name, is_array=False)
            gen.declare_local_ownership(node.name, c_name=binding_c_name)
            return [declaration]
        gen.declare_local_ownership(node.name, c_name=binding_c_name)
        declaration = IRVarDecl(
            c_type=CType(text=f"{base_c}*"),
            name=binding_c_name,
            init=IRLiteral(text="NULL"),
            **storage,
        )
        gen.context.function_declarations.append(declaration)
        from .c_array_scopes import declare_c_binding

        declare_c_binding(gen, node.name, is_array=False)
        return [declaration]

    from .gpu_dispatch import (
        lower_gpu_output_declaration,
        output_gpu_call_name,
    )

    if isinstance(node.initializer, CallExpr) and output_gpu_call_name(gen, node.initializer) is not None:
        plan = lower_gpu_output_declaration(
            gen,
            node.initializer,
            IRVar(name=binding_c_name),
        )
        gen.declare_local_ownership(node.name, c_name=binding_c_name)
        inferred_size = plan.array_length
        if not explicit_size and not inferred_size:
            from .errors import CodegenError

            raise CodegenError(f"GPU result array '{node.name}' has no dispatch length")
        logical_size = explicit_size or inferred_size
        size_setup = []
        if explicit_size is not None:
            size_name = gen.fresh_temp("__gpu_output_size")
            size_setup.append(
                IRVarDecl(
                    c_type=CType(text="int"),
                    name=size_name,
                    init=explicit_size,
                )
            )
            logical_size = IRVar(name=size_name)
        from .gpu_outputs import safe_array_size

        declaration = _track(
            gen,
            _declaration(
                base_c,
                binding_c_name,
                safe_array_size(logical_size),
                storage,
                None,
            ),
            node.name,
            logical_length=inferred_size,
        )
        ordered_setup = [*size_setup, *plan.setup] if explicit_size is not None else [*plan.setup, *size_setup]
        return [
            *ordered_setup,
            declaration,
            IRExprStmt(expr=plan.call),
        ]

    initializer = lower_expr(gen, node.initializer) if node.initializer else None
    gen.declare_local_ownership(node.name, c_name=binding_c_name)

    return [
        _track(
            gen,
            _declaration(
                base_c,
                binding_c_name,
                explicit_size,
                storage,
                initializer,
            ),
            node.name,
        )
    ]


def _declaration(
    base_c: str,
    name: str,
    size,
    storage: dict[str, bool],
    initializer,
) -> IRVarDecl:
    return IRVarDecl(
        c_type=CType(text=base_c),
        name=name,
        init=initializer,
        array_size=size,
        is_unsized_array=size is None,
        **storage,
    )


def _track(
    gen: IRLowerer,
    declaration: IRVarDecl,
    source_name: str,
    *,
    logical_length=None,
) -> IRVarDecl:
    gen.context.function_declarations.append(declaration)
    from .c_array_scopes import declare_c_binding

    declare_c_binding(
        gen,
        source_name,
        is_array=True,
        logical_length=logical_length,
    )
    return declaration
