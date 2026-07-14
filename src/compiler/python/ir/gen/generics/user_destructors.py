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
from ..types import type_to_c
from .core import _resolve_type


def build_generic_destructor_stmts(cls_info, type_map, mangled, gen):
    """Lower ``__del__`` and owned fields for one concrete instance."""
    stmts = []
    destructor = cls_info.methods.get("__del__")
    if destructor and destructor.body:
        from .user_emitter import _UserGenericEmitter

        emitter = _UserGenericEmitter(
            type_map,
            mangled,
            lambda type_expr: type_to_c(_resolve_type(type_expr, type_map)),
            gen=gen,
            cls_info=cls_info,
        )
        stmts.extend(emitter.emit_stmts(destructor.body.statements))

    for field_name, field in cls_info.instance_storage:
        resolved = _resolve_type(field.type, type_map) if field.type else None
        # Explicit pointer layers are borrowed/raw storage. Class values gain
        # their normal representation pointer elsewhere in the pipeline.
        if resolved is None or resolved.pointer_depth > 1:
            continue
        from ..managed_values import is_managed_type

        if is_managed_type(gen, resolved):
            stmts.append(_field_release(gen, field_name, resolved))
    return stmts


def _field_release(gen, field_name: str, field_type) -> IRBlock:
    from ..managed_values import (
        is_class_type,
        release_edge_value,
        replace_edge_value,
        unlink_edge_value,
    )
    from ..types import type_to_c

    field = IRFieldAccess(obj=IRVar(name="self"), field=field_name, arrow=True)
    if is_class_type(gen, field_type):
        return IRBlock(
            stmts=[
                IRExprStmt(
                    expr=replace_edge_value(
                        gen,
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
                c_type=CType(text=type_to_c(field_type)),
                name=old_name,
                init=field,
            ),
            IRExprStmt(
                expr=unlink_edge_value(
                    gen,
                    IRVar(name=old_name),
                    field_type,
                    IRVar(name="self"),
                )
            ),
            IRAssign(target=field, value=IRLiteral(text="NULL")),
            IRExprStmt(expr=release_edge_value(gen, IRVar(name=old_name), field_type)),
        ]
    )
