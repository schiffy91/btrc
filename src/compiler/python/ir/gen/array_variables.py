"""Lower fixed and inferred-size C array variable declarations."""

from __future__ import annotations

from dataclasses import replace
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
    from .generator import IRGenerator


def lower_array_var_decl(gen: IRGenerator, node: VarDeclStmt, storage: dict[str, bool]) -> list[IRStmt]:
    """Lower an array declaration, including direct GPU-result readback."""
    base_type = replace(node.type, is_array=False, array_size=None)
    base_c = type_to_c(base_type)
    explicit_size = lower_expr(gen, node.type.array_size) if node.type.array_size else None

    if isinstance(node.initializer, (BraceInitializer, ListLiteral)):
        from .aggregate_ownership import reject_owned_elements

        reject_owned_elements(
            gen,
            node.initializer.elements,
            "a shallow C array",
        )
        elements = [lower_expr(gen, item) for item in node.initializer.elements]
        declaration = _declaration(
            base_c,
            node.name,
            explicit_size,
            storage,
            IRInitializerList(elements=elements),
        )
        return [_track(gen, declaration)]

    if explicit_size is None and node.initializer is None:
        declaration = IRVarDecl(
            c_type=CType(text=f"{base_c}*"),
            name=node.name,
            init=IRLiteral(text="NULL"),
            **storage,
        )
        gen._func_var_decls.append(declaration)
        return [declaration]

    from .gpu_dispatch import (
        lower_gpu_output_declaration,
        output_gpu_call_name,
    )

    if isinstance(node.initializer, CallExpr) and output_gpu_call_name(gen, node.initializer) is not None:
        plan = lower_gpu_output_declaration(
            gen,
            node.initializer,
            IRVar(name=node.name),
        )
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
                node.name,
                safe_array_size(logical_size),
                storage,
                None,
            ),
        )
        return [
            *plan.setup,
            *size_setup,
            declaration,
            IRExprStmt(expr=plan.call),
        ]

    initializer = lower_expr(gen, node.initializer) if node.initializer else None

    return [
        _track(
            gen,
            _declaration(
                base_c,
                node.name,
                explicit_size,
                storage,
                initializer,
            ),
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


def _track(gen: IRGenerator, declaration: IRVarDecl) -> IRVarDecl:
    gen._func_var_decls.append(declaration)
    if gen._c_array_scopes:
        gen._c_array_scopes[-1].add(declaration.name)
    return declaration
