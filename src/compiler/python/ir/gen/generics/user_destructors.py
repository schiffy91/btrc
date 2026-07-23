"""Destructor lowering for monomorphized user-generic classes."""

from ...nodes import (
    CType,
    IRAssign,
    IRBlock,
    IRExprStmt,
    IRFieldAccess,
    IRLiteral,
    IRVar,
    IRVarDecl,
)
from ..destructor_hooks import build_destructor_hook
from ..types import CTypeRenderer
from .core import _resolve_type


def build_generic_destructor_hook(
    cls_info,
    type_map,
    mangled,
    gen,
    type_renderer: CTypeRenderer,
    default_arguments,
):
    """Lower one source ``__del__`` into an isolated hidden function."""
    destructor = cls_info.methods.get("__del__")
    if destructor is None or destructor.body is None:
        return None
    from .user_emitter import _UserGenericEmitter

    emitter = _UserGenericEmitter(
        type_map,
        mangled,
        type_renderer,
        gen=gen,
        cls_info=cls_info,
        default_arguments=default_arguments,
    )
    emitter.reset_var_types()
    return build_destructor_hook(
        mangled,
        IRBlock(stmts=emitter.emit_stmts(destructor.body.statements)),
    )


def build_generic_field_release_stmts(
    cls_info,
    type_map,
    gen,
    type_renderer: CTypeRenderer,
):
    """Build compiler-owned field detachment for one concrete instance."""
    stmts = []

    for field_name, field in cls_info.instance_storage:
        resolved = (
            _resolve_type(
                field.type,
                type_map,
                gen.analyzed.typedef_table,
                gen.type_identity,
            )
            if field.type
            else None
        )
        if resolved is None:
            continue

        if gen.managed_values.is_managed(resolved):
            stmts.append(_field_release(gen, field_name, resolved, type_renderer))
    return stmts


def _field_release(
    gen,
    field_name: str,
    field_type,
    type_renderer: CTypeRenderer,
) -> IRBlock:
    field = IRFieldAccess(obj=IRVar(name="self"), field=field_name, arrow=True)
    if gen.managed_values.is_arc(field_type):
        return IRBlock(
            stmts=[
                IRExprStmt(
                    expr=gen.lifetime.replace_edge_value(
                        field,
                        IRLiteral(text="NULL"),
                        field_type,
                        IRVar(name="self"),
                        adopt=False,
                    )
                )
            ]
        )
    old_name = gen.fresh_temp("__btrc_destroy_field")
    return IRBlock(
        stmts=[
            IRVarDecl(
                c_type=CType(text=type_renderer.render(field_type)),
                name=old_name,
                init=field,
            ),
            IRExprStmt(
                expr=gen.lifetime.unlink_edge_value(
                    IRVar(name=old_name),
                    field_type,
                    IRVar(name="self"),
                )
            ),
            IRAssign(target=field, value=IRLiteral(text="NULL")),
            IRExprStmt(expr=gen.lifetime.release_edge_value(IRVar(name=old_name), field_type)),
        ]
    )


__all__ = [
    "build_generic_destructor_hook",
    "build_generic_field_release_stmts",
]
