"""ARC (automatic reference counting) scope-release and destroy helpers.

Handles scope-exit cleanup, phased release for cyclable types, return-path
release, and explicit ``release`` statement lowering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..nodes import (
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFieldAccess,
    IRIf,
    IRLiteral,
    IRRawExpr,
    IRStmt,
    IRUnaryOp,
    IRVar,
)
from .expressions import lower_expr

if TYPE_CHECKING:
    from ...ast_nodes import ReleaseStmt
    from .generator import IRGenerator


def _get_destroy_name(gen: IRGenerator, type_expr, cls_name: str) -> str:
    """Get the appropriate destroy function name for a class type."""
    from .types import is_generic_class_type, mangle_generic_type
    ct = gen.analyzed.class_table
    if type_expr.generic_args and is_generic_class_type(type_expr, ct):
        mangled = mangle_generic_type(type_expr.base, type_expr.generic_args)
        field_cls = ct.get(type_expr.base)
        dtor = "free" if field_cls and "free" in field_cls.methods else "destroy"
        return f"{mangled}_{dtor}"
    return f"{cls_name}_destroy"


def _destroy_fn_for_managed(gen: IRGenerator, cls_name: str) -> str:
    """Get the correct destroy/free function name for a managed class type."""
    ct = gen.analyzed.class_table
    # If cls_name is already a mangled generic name (e.g., btrc_Box_int),
    # check the base class for 'free' method
    base_name = cls_name
    for cname, cinfo in ct.items():
        from .types import mangle_generic_type
        if cinfo.generic_params:
            # Check all concrete instances of this generic
            instances = gen.analyzed.generic_instances.get(cname, [])
            for args in instances:
                mangled = mangle_generic_type(cname, list(args))
                if mangled == cls_name:
                    base_name = cname
                    break
    cinfo = ct.get(base_name)
    if cinfo and "free" in cinfo.methods:
        return f"{cls_name}_free"
    return f"{cls_name}_destroy"


def _emit_scope_release(managed: list[tuple[str, str]],
                        gen: IRGenerator | None = None) -> list[IRStmt]:
    """Emit rc-- cleanup for all managed vars in a scope.

    Uses a three-phase approach for cyclable types to avoid accessing
    freed memory in the cycle collector:
    1. Decrement rc for ALL managed vars
    2. Destroy any with rc <= 0 (cascade may free others)
    3. Suspect those still alive (rc > 0) for cycle collection
    """
    has_cyclable = False
    if gen:
        for _, cls_name in managed:
            cls_info = _lookup_cls_info(gen, cls_name)
            if cls_info and cls_info.is_cyclable:
                has_cyclable = True
                break

    if has_cyclable and gen:
        return _emit_scope_release_phased(managed, gen)

    # Simple path: no cyclable types, just rc-- and destroy
    stmts = []
    for var_name, cls_name in reversed(managed):
        destroy_fn = _destroy_fn_for_managed(gen, cls_name) if gen else f"{cls_name}_destroy"
        stmts.append(IRIf(
            condition=IRBinOp(
                left=IRVar(name=var_name), op="!=",
                right=IRLiteral(text="NULL")),
            then_block=IRBlock(stmts=[IRIf(
                condition=IRBinOp(
                    left=IRUnaryOp(op="--", operand=IRFieldAccess(
                        obj=IRVar(name=var_name), field="__rc", arrow=True),
                        prefix=True),
                    op="<=", right=IRLiteral(text="0")),
                then_block=IRBlock(stmts=[IRExprStmt(
                    expr=IRCall(callee=destroy_fn,
                                args=[IRVar(name=var_name)]))]),
            )]),
        ))
    return stmts


def _lookup_cls_info(gen: IRGenerator, cls_name: str):
    """Look up ClassInfo by name or mangled name."""
    cls_info = gen.analyzed.class_table.get(cls_name)
    if cls_info:
        return cls_info
    for cname, ci in gen.analyzed.class_table.items():
        if cls_name.startswith("btrc_" + cname):
            return ci
    return None


def _emit_scope_release_phased(managed: list[tuple[str, str]],
                                gen: IRGenerator) -> list[IRStmt]:
    """Three-phase scope release for scopes containing cyclable types.

    Uses destroyed-object tracking to avoid reading freed memory:
    cascade destruction (in Phase 2) may free objects whose local vars
    are still non-NULL.  We gate Phase 2/3 reads with __btrc_is_destroyed()
    which short-circuits before touching freed memory.
    """
    stmts = []
    gen.use_helper("__btrc_suspect_buf")
    gen.use_helper("__btrc_collect_cycles")
    gen.use_helper("__btrc_destroyed_tracking")

    # Enable cascade-destroy tracking
    stmts.append(IRAssign(
        target=IRVar(name="__btrc_tracking"),
        value=IRLiteral(text="1")))
    stmts.append(IRAssign(
        target=IRVar(name="__btrc_destroyed_count"),
        value=IRLiteral(text="0")))

    # Phase 1: Decrement rc for ALL managed vars
    for var_name, _cls_name in reversed(managed):
        stmts.append(IRIf(
            condition=IRBinOp(
                left=IRVar(name=var_name), op="!=",
                right=IRLiteral(text="NULL")),
            then_block=IRBlock(stmts=[IRExprStmt(
                expr=IRUnaryOp(op="--", operand=IRFieldAccess(
                    obj=IRVar(name=var_name), field="__rc", arrow=True),
                    prefix=True))]),
        ))

    # Phase 2: Destroy those at rc == 0
    # Guard with !__btrc_is_destroyed() to skip cascade-freed objects
    # (short-circuit ensures var->__rc is never read on freed memory)
    for var_name, cls_name in reversed(managed):
        destroy_fn = _destroy_fn_for_managed(gen, cls_name)
        stmts.append(IRIf(
            condition=IRBinOp(
                left=IRVar(name=var_name), op="!=",
                right=IRLiteral(text="NULL")),
            then_block=IRBlock(stmts=[IRIf(
                condition=IRBinOp(
                    left=IRCall(callee="__btrc_is_destroyed",
                                args=[IRVar(name=var_name)]),
                    op="==", right=IRLiteral(text="0")),
                then_block=IRBlock(stmts=[IRIf(
                    condition=IRBinOp(
                        left=IRFieldAccess(
                            obj=IRVar(name=var_name), field="__rc",
                            arrow=True),
                        op="<=", right=IRLiteral(text="0")),
                    then_block=IRBlock(stmts=[
                        IRExprStmt(expr=IRCall(
                            callee=destroy_fn,
                            args=[IRVar(name=var_name)])),
                        IRAssign(
                            target=IRVar(name=var_name),
                            value=IRLiteral(text="NULL")),
                    ]),
                )]),
            )]),
        ))

    # Phase 3: Suspect those still alive (rc > 0) for cycle collection
    for var_name, cls_name in reversed(managed):
        cls_info = _lookup_cls_info(gen, cls_name)
        if not cls_info or not cls_info.is_cyclable:
            continue
        destroy_fn = _destroy_fn_for_managed(gen, cls_name)
        stmts.append(IRIf(
            condition=IRBinOp(
                left=IRVar(name=var_name), op="!=",
                right=IRLiteral(text="NULL")),
            then_block=IRBlock(stmts=[IRIf(
                condition=IRBinOp(
                    left=IRCall(callee="__btrc_is_destroyed",
                                args=[IRVar(name=var_name)]),
                    op="==", right=IRLiteral(text="0")),
                then_block=IRBlock(stmts=[IRIf(
                    condition=IRBinOp(
                        left=IRFieldAccess(
                            obj=IRVar(name=var_name), field="__rc",
                            arrow=True),
                        op=">", right=IRLiteral(text="0")),
                    then_block=IRBlock(stmts=[IRExprStmt(
                        expr=IRCall(
                            callee="__btrc_suspect",
                            helper_ref="__btrc_suspect_buf",
                            args=[
                                IRVar(name=var_name),
                                IRRawExpr(
                                    text=f"(__btrc_visit_fn){cls_name}_visit"),
                                IRRawExpr(
                                    text=f"(__btrc_destroy_fn){destroy_fn}"),
                            ]))]),
                )]),
            )]),
        ))

    # Phase 4: Collect cycles if any suspects
    stmts.append(IRIf(
        condition=IRBinOp(
            left=IRVar(name="__btrc_suspect_count"), op=">",
            right=IRLiteral(text="0")),
        then_block=IRBlock(stmts=[IRExprStmt(
            expr=IRCall(callee="__btrc_collect_cycles",
                        helper_ref="__btrc_collect_cycles", args=[]))]),
    ))

    # Disable tracking
    stmts.append(IRAssign(
        target=IRVar(name="__btrc_tracking"),
        value=IRLiteral(text="0")))

    return stmts


def _emit_return_release(gen: IRGenerator, returned_var: str | None) -> list[IRStmt]:
    """Emit rc-- for all managed vars across all scopes, except the returned var."""
    stmts = []
    all_managed = gen.get_all_managed_vars()
    for var_name, cls_name in reversed(all_managed):
        if var_name == returned_var:
            continue  # Skip the returned variable — ownership transfers to caller
        destroy_fn = _destroy_fn_for_managed(gen, cls_name)
        stmts.append(IRIf(
            condition=IRBinOp(
                left=IRVar(name=var_name), op="!=",
                right=IRLiteral(text="NULL")),
            then_block=IRBlock(stmts=[IRIf(
                condition=IRBinOp(
                    left=IRUnaryOp(op="--", operand=IRFieldAccess(
                        obj=IRVar(name=var_name), field="__rc", arrow=True),
                        prefix=True),
                    op="<=", right=IRLiteral(text="0")),
                then_block=IRBlock(stmts=[IRExprStmt(
                    expr=IRCall(callee=destroy_fn,
                                args=[IRVar(name=var_name)]))]),
            )]),
        ))
    return stmts


def _lower_release(gen: IRGenerator, node: ReleaseStmt) -> list[IRStmt]:
    """Lower release expr -> rc--; destroy at zero; expr = NULL."""
    expr = lower_expr(gen, node.expr)
    # Determine the destroy function
    expr_type = gen.analyzed.node_types.get(id(node.expr))
    if expr_type and expr_type.base in gen.analyzed.class_table:
        from .types import is_generic_class_type, mangle_generic_type
        ct = gen.analyzed.class_table
        if expr_type.generic_args and is_generic_class_type(expr_type, ct):
            mangled = mangle_generic_type(expr_type.base, expr_type.generic_args)
            field_cls = ct.get(expr_type.base)
            dtor = "free" if field_cls and "free" in field_cls.methods else "destroy"
            destroy_fn = f"{mangled}_{dtor}"
        else:
            destroy_fn = f"{expr_type.base}_destroy"
    else:
        destroy_fn = "free"
    stmts = [IRIf(
        condition=IRBinOp(left=expr, op="!=", right=IRLiteral(text="NULL")),
        then_block=IRBlock(stmts=[IRIf(
            condition=IRBinOp(
                left=IRUnaryOp(op="--", operand=IRFieldAccess(
                    obj=expr, field="__rc", arrow=True), prefix=True),
                op="<=", right=IRLiteral(text="0")),
            then_block=IRBlock(stmts=[IRExprStmt(
                expr=IRCall(callee=destroy_fn, args=[expr]))]),
        )]),
    )]
    # Set variable to NULL
    stmts.append(IRAssign(target=expr, value=IRLiteral(text="NULL")))
    return stmts
