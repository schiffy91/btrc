"""ARC (automatic reference counting) scope-release and destroy helpers.

Handles scope-exit cleanup, phased release for cyclable types, return-path
release, and explicit ``release`` statement lowering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..c_types import qualify_volatile_object
from ..nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRCall,
    IRDeref,
    IRExprStmt,
    IRLiteral,
    IRStmt,
    IRVar,
    IRVarDecl,
)
from .expressions import lower_expr
from .managed_local import ManagedLocal

if TYPE_CHECKING:
    from ...ast_nodes import ReleaseStmt
    from .generator import IRGenerator


def _get_destroy_name(gen: IRGenerator, type_expr, cls_name: str) -> str:
    """Get the terminal destroy function name for a managed class value."""
    from .types import is_generic_class_type, mangle_generic_type

    ct = gen.analyzed.class_table
    if type_expr.generic_args and is_generic_class_type(type_expr, ct):
        mangled = mangle_generic_type(type_expr.base, type_expr.generic_args)
        return f"{mangled}_destroy"
    return f"{cls_name}_destroy"


def _destroy_fn_for_managed(gen: IRGenerator, cls_name: str) -> str:
    """Get the terminal destructor name for a managed class type.

    Always returns ``{cls_name}_destroy``. Lifecycle behavior is explicit in a
    source ``__del__`` hook; an ordinary method named ``free`` is never selected
    by compiler lowering. Scope, return-path, and loop-exit releases therefore
    share the same terminal entry point.
    """
    return f"{cls_name}_destroy"


def _emit_scope_release(
    managed: list[ManagedLocal],
    gen: IRGenerator | None = None,
    *,
    force: bool = True,
) -> list[IRStmt]:
    """Release a batch, then poll or force-drain if it can enqueue."""
    if not gen:
        raise RuntimeError("typed scope release requires an IR generator")
    from .arc_ops import (
        flush_release_batch,
        poll_release_batch,
    )
    from .managed_values import STRING_RUNTIME_NAME, release_emitted_value

    stmts: list[IRStmt] = []
    for local in reversed(managed):
        local_c_name = local.c_name or local.name
        if local.cleanup_kind == "thread":
            from .thread_values import consume_thread_handle

            gen.use_helper("__btrc_thread_free")
            stmts.append(
                IRExprStmt(
                    expr=IRCall(
                        callee="__btrc_thread_free",
                        args=[
                            consume_thread_handle(
                                gen,
                                IRVar(name=local_c_name),
                            )
                        ],
                        helper_ref="__btrc_thread_free",
                    )
                )
            )
            continue
        value_decl = IRVarDecl(
            c_type=CType(text=_emitted_value_c_type(local.type_name)),
            name=gen.fresh_temp("__btrc_scope_released"),
            init=IRVar(name=local_c_name),
        )
        gen._func_var_decls.append(value_decl)
        stmts.extend(
            [
                value_decl,
                IRAssign(
                    target=IRVar(name=local_c_name),
                    value=IRLiteral(text="NULL"),
                ),
                IRExprStmt(
                    expr=release_emitted_value(
                        gen,
                        IRVar(name=value_decl.name),
                        local.type_name,
                    )
                ),
            ]
        )
    boundary = flush_release_batch if force else poll_release_batch
    flush = boundary(
        gen,
        emitted_names=[
            local.type_name
            for local in managed
            if local.cleanup_kind == "arc" and local.type_name != STRING_RUNTIME_NAME
        ],
    )
    if flush is not None:
        stmts.append(IRExprStmt(expr=flush))
    return stmts


def _emitted_value_c_type(type_name: str) -> str:
    from .managed_values import MUTEX_RUNTIME_NAME, STRING_RUNTIME_NAME

    # A local may shadow the class typedef (``Box Box``); C struct tags live in
    # a separate namespace and therefore remain usable by generated cleanup.
    if type_name == STRING_RUNTIME_NAME:
        return "const char*"
    if type_name == MUTEX_RUNTIME_NAME:
        return "__btrc_mutex_val_t*"
    return f"struct {type_name}*"


def _emit_return_release(gen: IRGenerator, returned_var: str | None) -> list[IRStmt]:
    """Emit rc-- for all managed vars across all scopes, except the returned var."""
    returned_c_name = gen.source_binding_c_name(returned_var) if returned_var is not None else None
    managed = [local for local in gen.get_all_managed_vars() if (local.c_name or local.name) != returned_c_name]
    return _emit_scope_release(managed, gen)


def _emit_control_exit_release(gen: IRGenerator, targets: set[str]) -> list[IRStmt]:
    """Release managed locals exited by the nearest matching target."""
    return _emit_scope_release(gen.get_control_managed_vars(targets), gen, force=True)


def _lower_release(gen: IRGenerator, node: ReleaseStmt) -> list[IRStmt]:
    """Lower an explicit typed ownership release and flush boundary."""
    return lower_release_expression(gen, node.expr)


def lower_release_expression(gen: IRGenerator, expression) -> list[IRStmt]:
    """Clear and release one analyzed physical managed slot."""
    expr = lower_expr(gen, expression)
    expr_type = gen.analyzed.node_types.get(id(expression))
    from .managed_values import is_managed_type

    if not is_managed_type(gen, expr_type):
        return [IRExprStmt(expr=IRCall(callee="free", args=[expr]))]
    from .managed_values import (
        flush_released_values,
        is_arc_type,
        release_edge_value,
        release_value,
        replace_edge_value,
        unlink_edge_value,
    )
    from .persistent_slots import stabilize_persistent_slot
    from .types import type_to_c

    expr, edge_owner, owner_decls = stabilize_persistent_slot(
        gen,
        expression,
        expr,
        prefix="__btrc_release_owner",
    )

    value_c = type_to_c(expr_type)
    slot_name = gen.fresh_temp("__btrc_release_slot")
    slot_decl = IRVarDecl(
        c_type=CType(text=f"{qualify_volatile_object(value_c, True)}*"),
        name=slot_name,
        init=IRAddressOf(expr=expr),
    )
    slot = IRDeref(expr=IRVar(name=slot_name))
    gen._func_var_decls.append(slot_decl)
    stmts = [*owner_decls, slot_decl]
    if edge_owner is not None and is_arc_type(gen, expr_type):
        stmts.append(
            IRExprStmt(
                expr=replace_edge_value(
                    gen,
                    slot,
                    IRLiteral(text="NULL"),
                    expr_type,
                    edge_owner,
                    adopt=False,
                )
            )
        )
    else:
        value_name = gen.fresh_temp("__btrc_release_value")
        value_decl = IRVarDecl(
            c_type=CType(text=value_c),
            name=value_name,
            init=slot,
        )
        gen._func_var_decls.append(value_decl)
        release = release_edge_value if edge_owner is not None else release_value
        stmts.extend(
            [
                value_decl,
                *(
                    [
                        IRExprStmt(
                            expr=unlink_edge_value(
                                gen,
                                IRVar(name=value_name),
                                expr_type,
                                edge_owner,
                            )
                        )
                    ]
                    if edge_owner is not None
                    else []
                ),
                IRAssign(target=slot, value=IRLiteral(text="NULL")),
                IRExprStmt(expr=release(gen, IRVar(name=value_name), expr_type)),
            ]
        )
    flush = flush_released_values(gen, expr_type)
    if flush is not None:
        stmts.append(IRExprStmt(expr=flush))
    return stmts
