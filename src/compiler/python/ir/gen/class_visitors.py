"""ARC cycle-visitor emission shared by concrete and generic classes."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ...ast_nodes import TypeExpr
from ..nodes import (
    CType,
    IRBlock,
    IRCast,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDecl,
    IRFunctionDef,
    IRParam,
    IRVar,
    IRVarDecl,
)
from .collection_visitors import ensure_cycle_callback_alias, slot_visit_stmts
from .cycle_metadata import cycle_visitor_symbol, register_cycle_visitor
from .types import CTypeRenderer


def emit_class_visitor(
    gen,
    emitted_name: str,
    storage: Iterable[tuple[str, object]],
    type_renderer: CTypeRenderer,
    resolve_type: Callable[[TypeExpr], TypeExpr] | None = None,
) -> None:
    """Emit ``NAME_visit(object, fn)`` for one cyclable representation."""

    register_cycle_visitor(gen, emitted_name)
    ensure_cycle_callback_alias(gen)
    visitor_name = cycle_visitor_symbol(emitted_name)

    params = [
        IRParam(c_type=CType(text="void*"), name="object"),
        IRParam(c_type=CType(text="__btrc_field_visit_fn"), name="fn"),
        IRParam(c_type=CType(text="void*"), name="context"),
    ]
    gen.module.function_decls.append(
        IRFunctionDecl(
            name=visitor_name,
            return_type=CType(text="void"),
            params=list(params),
            is_static=True,
        )
    )

    body = [
        IRVarDecl(
            c_type=CType(text=f"{emitted_name}*"),
            name="self",
            init=IRCast(
                target_type=CType(text=f"{emitted_name}*"),
                expr=IRVar(name="object"),
            ),
        )
    ]
    visited = False
    for field_name, field_decl in storage:
        field_type = getattr(field_decl, "type", None)
        if field_type is None:
            continue
        resolved = resolve_type(field_type) if resolve_type else field_type
        field = IRFieldAccess(obj=IRVar(name="self"), field=field_name, arrow=True)
        field_visits = slot_visit_stmts(
            gen,
            resolved,
            field,
            type_renderer,
        )
        visited = visited or bool(field_visits)
        body.extend(field_visits)

    if not visited:
        body.extend(
            [
                IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=IRVar(name="self"))),
                IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=IRVar(name="fn"))),
                IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=IRVar(name="context"))),
            ]
        )
    gen.module.function_defs.append(
        IRFunctionDef(
            name=visitor_name,
            return_type=CType(text="void"),
            params=params,
            body=IRBlock(stmts=body),
            is_static=True,
            archive_export=True,
        )
    )


__all__ = ["emit_class_visitor"]
