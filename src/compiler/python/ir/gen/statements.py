"""Statement lowering: AST stmt → IRStmt.

Main dispatch (lower_block, lower_stmt), variable declarations, and the
_quick_text utility.  Control-flow lowering lives in control_flow.py.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import (
    Block, BreakStmt, CForStmt, ContinueStmt, DeleteStmt, DoWhileStmt,
    ExprStmt, ForInStmt, ForInitExpr, ForInitVar, IfStmt, ElseBlock,
    ElseIf, KeepStmt, ParallelForStmt, ReleaseStmt, ReturnStmt,
    SwitchStmt, ThrowStmt, TryCatchStmt, VarDeclStmt, WhileStmt,
    TypeExpr, CallExpr, Identifier, NewExpr,
)
from ..nodes import (
    CType, IRAssign, IRBlock, IRBreak, IRCase, IRContinue, IRDoWhile,
    IRExprStmt, IRFor, IRIf, IRRawC, IRRawExpr, IRReturn, IRStmt,
    IRSwitch, IRUnaryOp, IRVarDecl, IRVar, IRWhile, IRCall, IRLiteral,
    IRBinOp, IRFieldAccess, IRIndex,
)
from .types import type_to_c
from .expressions import lower_expr

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_block(gen: IRGenerator, block: Block | None) -> IRBlock:
    """Lower a btrc Block to an IRBlock."""
    if block is None:
        return IRBlock()
    gen.push_managed_scope()
    stmts = []
    for s in block.statements:
        ir_stmts = lower_stmt(gen, s)
        stmts.extend(ir_stmts)
    # ARC: scope-exit release for managed vars (only if not already handled
    # by return/break/continue inside this block)
    managed = gen.pop_managed_scope()
    stmts.extend(_emit_scope_release(managed, gen))
    return IRBlock(stmts=stmts)


def lower_stmt(gen: IRGenerator, node) -> list[IRStmt]:
    """Lower a single AST statement to one or more IRStmts."""
    from .control_flow import (
        _lower_if, _lower_for_in, _lower_c_for, _lower_switch,
        _lower_delete, _lower_try_catch, _lower_throw,
    )

    if isinstance(node, VarDeclStmt):
        return _lower_var_decl(gen, node)

    if isinstance(node, ReturnStmt):
        val = lower_expr(gen, node.value) if node.value else None
        # ARC: release all managed vars before return, EXCEPT the returned var
        returned_var = None
        if node.value and isinstance(node.value, Identifier):
            returned_var = node.value.name
        release_stmts = _emit_return_release(gen, returned_var)
        return release_stmts + [IRReturn(value=val)]

    if isinstance(node, IfStmt):
        return [_lower_if(gen, node)]

    if isinstance(node, WhileStmt):
        return [IRWhile(
            condition=lower_expr(gen, node.condition),
            body=lower_block(gen, node.body),
        )]

    if isinstance(node, DoWhileStmt):
        return [IRDoWhile(
            body=lower_block(gen, node.body),
            condition=lower_expr(gen, node.condition),
        )]

    if isinstance(node, ForInStmt):
        return _lower_for_in(gen, node)

    if isinstance(node, CForStmt):
        return [_lower_c_for(gen, node)]

    if isinstance(node, ParallelForStmt):
        # Parallel for → regular for (no GPU support yet)
        return _lower_for_in(gen, node)

    if isinstance(node, SwitchStmt):
        return [_lower_switch(gen, node)]

    if isinstance(node, BreakStmt):
        return [IRBreak()]

    if isinstance(node, ContinueStmt):
        return [IRContinue()]

    if isinstance(node, ExprStmt):
        from ...ast_nodes import AssignExpr
        # ARC: field assignment implicit keep
        if isinstance(node.expr, AssignExpr):
            from .fields import get_field_assign_arc_stmts
            pre, post = get_field_assign_arc_stmts(gen, node.expr)
            if pre or post:
                return pre + [IRExprStmt(expr=lower_expr(gen, node.expr))] + post
        # ARC: emit rc++ for keep params before the call
        pre_stmts = _emit_keep_for_call(gen, node.expr)
        return pre_stmts + [IRExprStmt(expr=lower_expr(gen, node.expr))]

    if isinstance(node, DeleteStmt):
        return _lower_delete(gen, node)

    if isinstance(node, TryCatchStmt):
        return _lower_try_catch(gen, node)

    if isinstance(node, ThrowStmt):
        return _lower_throw(gen, node)

    if isinstance(node, Block):
        # Bare block statement: { ... }
        blk = lower_block(gen, node)
        return blk.stmts

    if isinstance(node, KeepStmt):
        # keep expr → expr->__rc++
        expr = lower_expr(gen, node.expr)
        return [IRExprStmt(expr=IRUnaryOp(
            op="++", operand=IRFieldAccess(obj=expr, field="__rc", arrow=True),
            prefix=False))]

    if isinstance(node, ReleaseStmt):
        # release expr → if (--expr->__rc <= 0) destroy(expr); expr = NULL;
        return _lower_release(gen, node)

    return [IRRawC(text=f"/* unhandled stmt: {type(node).__name__} */")]


def _lower_var_decl(gen: IRGenerator, node: VarDeclStmt) -> list[IRStmt]:
    from ...ast_nodes import BraceInitializer, CallExpr, Identifier, TypeExpr as TE
    from .types import is_generic_class_type, mangle_generic_type

    # Handle array types: int arr[5] or int nums[]
    if node.type and node.type.is_array:
        base_type = TE(base=node.type.base,
                       generic_args=node.type.generic_args,
                       pointer_depth=node.type.pointer_depth)
        base_c = type_to_c(base_type)
        if node.type.array_size:
            size_text = _quick_text(lower_expr(gen, node.type.array_size))
            var_name = f"{node.name}[{size_text}]"
        else:
            var_name = f"{node.name}[]"
        init = lower_expr(gen, node.initializer) if node.initializer else None
        return [IRVarDecl(c_type=CType(text=base_c), name=var_name, init=init)]

    c_type = type_to_c(node.type) if node.type else "int"
    init = None
    if node.initializer:
        from ...ast_nodes import ListLiteral, MapLiteral
        ct = gen.analyzed.class_table
        # Empty brace initializer on generic class types → TYPE_new()
        if (isinstance(node.initializer, BraceInitializer)
                and not node.initializer.elements
                and node.type and is_generic_class_type(node.type, ct)):
            mangled = mangle_generic_type(node.type.base, node.type.generic_args)
            init = IRCall(callee=f"{mangled}_new", args=[])
        # Empty [] on generic-typed variable → TYPE_new()
        elif (isinstance(node.initializer, ListLiteral)
              and not node.initializer.elements
              and node.type and is_generic_class_type(node.type, ct)):
            mangled = mangle_generic_type(node.type.base, node.type.generic_args)
            init = IRCall(callee=f"{mangled}_new", args=[])
        # Empty {} on generic-typed variable → TYPE_new()
        elif (isinstance(node.initializer, MapLiteral)
              and not node.initializer.entries
              and node.type and is_generic_class_type(node.type, ct)):
            mangled = mangle_generic_type(node.type.base, node.type.generic_args)
            init = IRCall(callee=f"{mangled}_new", args=[])
        else:
            init = lower_expr(gen, node.initializer)
            # Fix generic constructor calls: Box(42) → btrc_Box_int_new(42)
            if (isinstance(init, IRCall) and node.type
                    and node.type.generic_args
                    and isinstance(node.initializer, CallExpr)
                    and isinstance(node.initializer.callee, Identifier)):
                ctor_name = node.initializer.callee.name
                cls_info = gen.analyzed.class_table.get(ctor_name)
                if cls_info and cls_info.generic_params:
                    mangled = mangle_generic_type(ctor_name, node.type.generic_args)
                    init = IRCall(callee=f"{mangled}_new", args=init.args)
    # ARC: emit rc++ for keep params if initializer is a call
    pre_stmts = _emit_keep_for_call(gen, node.initializer)
    result = pre_stmts + [IRVarDecl(c_type=CType(text=c_type), name=node.name, init=init)]

    # ARC: track potentially-managed variables for later keep operations.
    # Variables are only auto-managed at scope exit when `keep` has been
    # applied (keep param, field assign, explicit keep). This is the
    # "zero-cost when no keeps" optimization that ensures backwards compat.
    # Registration happens in calls.py (keep params), fields.py (field assigns),
    # and the KeepStmt handler above.

    return result


def _emit_keep_for_call(gen: IRGenerator, expr) -> list[IRStmt]:
    """If expr is a CallExpr with `keep` params, emit rc++ for those args."""
    from ...ast_nodes import CallExpr as CE, FieldAccessExpr as FAE
    if not isinstance(expr, CE):
        return []
    from .calls import emit_keep_rc_increments
    # We need the lowered args to emit rc++ on. Lower args separately.
    ir_args = [lower_expr(gen, a) for a in expr.args]
    # For method calls, the args in the IR don't include 'self' — that's
    # prepended by the method call lowering. keep indices refer to the
    # method's declared params (excluding self).
    return emit_keep_rc_increments(gen, expr, ir_args)


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


def _emit_scope_release(managed: list[tuple[str, str]],
                        gen: IRGenerator | None = None) -> list[IRStmt]:
    """Emit rc-- cleanup for all managed vars in a scope.

    For cyclable types (when gen is provided), rc > 0 after decrement
    triggers the suspect buffer for cycle detection.
    """
    stmts = []
    has_suspects = False
    for var_name, cls_name in reversed(managed):
        cls_info = gen.analyzed.class_table.get(cls_name) if gen else None
        is_cyclable = cls_info and cls_info.is_cyclable if cls_info else False

        if is_cyclable and gen:
            # Cyclable: if rc <= 0, destroy. If rc > 0, suspect.
            gen.use_helper("__btrc_suspect_buf")
            gen.use_helper("__btrc_collect_cycles")
            has_suspects = True
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
                        expr=IRCall(callee=f"{cls_name}_destroy",
                                    args=[IRVar(name=var_name)]))]),
                    else_block=IRBlock(stmts=[IRExprStmt(
                        expr=IRCall(
                            callee="__btrc_suspect",
                            args=[
                                IRVar(name=var_name),
                                IRRawExpr(text=f"(__btrc_visit_fn){cls_name}_visit"),
                                IRRawExpr(text=f"(__btrc_destroy_fn){cls_name}_destroy"),
                            ]))]),
                )]),
            ))
        else:
            # Non-cyclable: simple rc-- and destroy at zero
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
                        expr=IRCall(callee=f"{cls_name}_destroy",
                                    args=[IRVar(name=var_name)]))]),
                )]),
            ))

    # After all releases, collect cycles if any suspects
    if has_suspects and gen:
        stmts.append(IRIf(
            condition=IRBinOp(
                left=IRVar(name="__btrc_suspect_count"), op=">",
                right=IRLiteral(text="0")),
            then_block=IRBlock(stmts=[IRExprStmt(
                expr=IRCall(callee="__btrc_collect_cycles", args=[]))]),
        ))

    return stmts


def _emit_return_release(gen: IRGenerator, returned_var: str | None) -> list[IRStmt]:
    """Emit rc-- for all managed vars across all scopes, except the returned var."""
    stmts = []
    all_managed = gen.get_all_managed_vars()
    for var_name, cls_name in reversed(all_managed):
        if var_name == returned_var:
            continue  # Skip the returned variable — ownership transfers to caller
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
                    expr=IRCall(callee=f"{cls_name}_destroy",
                                args=[IRVar(name=var_name)]))]),
            )]),
        ))
    return stmts


def _lower_release(gen: IRGenerator, node: ReleaseStmt) -> list[IRStmt]:
    """Lower release expr → rc--; destroy at zero; expr = NULL."""
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


def _quick_text(expr) -> str:
    """Render an IR expression as inline C text for use in for-loop headers."""
    from ..nodes import (
        IRLiteral, IRVar, IRRawExpr, IRRawC, IRBinOp, IRUnaryOp,
        IRCall, IRFieldAccess, IRIndex, IRCast, IRTernary,
        IRAddressOf, IRDeref, IRSizeof,
    )
    if expr is None:
        return ""
    if isinstance(expr, IRLiteral):
        return expr.text
    if isinstance(expr, IRVar):
        return expr.name
    if isinstance(expr, IRRawExpr):
        return expr.text
    if isinstance(expr, IRRawC):
        return expr.text
    if isinstance(expr, IRBinOp):
        return f"({_quick_text(expr.left)} {expr.op} {_quick_text(expr.right)})"
    if isinstance(expr, IRUnaryOp):
        if expr.prefix:
            return f"({expr.op}{_quick_text(expr.operand)})"
        return f"({_quick_text(expr.operand)}{expr.op})"
    if isinstance(expr, IRCall):
        args = ", ".join(_quick_text(a) for a in expr.args)
        return f"{expr.callee}({args})"
    if isinstance(expr, IRFieldAccess):
        op = "->" if expr.arrow else "."
        return f"{_quick_text(expr.obj)}{op}{expr.field}"
    if isinstance(expr, IRIndex):
        return f"{_quick_text(expr.obj)}[{_quick_text(expr.index)}]"
    if isinstance(expr, IRCast):
        return f"(({expr.target_type}){_quick_text(expr.expr)})"
    if isinstance(expr, IRTernary):
        return f"({_quick_text(expr.condition)} ? {_quick_text(expr.true_expr)} : {_quick_text(expr.false_expr)})"
    if isinstance(expr, IRAddressOf):
        return f"(&{_quick_text(expr.expr)})"
    if isinstance(expr, IRDeref):
        return f"(*{_quick_text(expr.expr)})"
    if isinstance(expr, IRSizeof):
        return f"sizeof({expr.operand})"
    return f"/* unknown: {type(expr).__name__} */"
