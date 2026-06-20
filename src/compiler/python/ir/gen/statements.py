"""Statement lowering: AST stmt -> IRStmt.

Main dispatch (lower_block, lower_stmt) and the _quick_text utility.
Variable declarations live in variables.py; ARC scope-release logic
lives in arc.py; control-flow lowering lives in control_flow.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    Block,
    BreakStmt,
    CForStmt,
    ContinueStmt,
    DeleteStmt,
    DoWhileStmt,
    ExprStmt,
    ForInStmt,
    Identifier,
    IfStmt,
    KeepStmt,
    ParallelForStmt,
    ReleaseStmt,
    ReturnStmt,
    SwitchStmt,
    ThrowStmt,
    TryCatchStmt,
    VarDeclStmt,
    WhileStmt,
)
from ..nodes import (
    CType,
    IRBinOp,
    IRBlock,
    IRBreak,
    IRCall,
    IRContinue,
    IRDoWhile,
    IRExprStmt,
    IRFieldAccess,
    IRIndex,
    IRLiteral,
    IRRawExpr,
    IRReturn,
    IRStmt,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
)
from .arc import (
    _emit_loop_exit_release,
    _emit_return_release,
    _emit_return_try_pop,
    _emit_scope_release,
    _lower_release,
    _maybe_launder_return,
)
from .errors import unsupported_node
from .expressions import lower_expr
from .stringable import coerce_value_to_string
from .variables import _keep_call_arc_stmts, _lower_var_decl

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_block(gen: IRGenerator, block: Block | None) -> IRBlock:
    """Lower a btrc Block to an IRBlock."""
    if block is None:
        return IRBlock()
    gen.push_managed_scope()
    stmts = []
    for s in block.statements:
        _emit_line_marker(gen, s, stmts)
        ir_stmts = lower_stmt(gen, s)
        stmts.extend(ir_stmts)
    # ARC: scope-exit release for managed vars (only if not already handled
    # by return/break/continue inside this block)
    managed = gen.pop_managed_scope()
    stmts.extend(_emit_scope_release(managed, gen))
    return IRBlock(stmts=stmts)


def _emit_line_marker(gen: IRGenerator, ast_stmt, out: list) -> None:
    """In --debug mode, prepend a ``#line`` marker mapping this statement back to
    its .btrc source, so the compiled binary's DWARF points at btrc source."""
    if not (gen.debug and gen.line_map):
        return
    line = getattr(ast_stmt, "line", 0)
    if not line:
        return
    mapped = gen.line_map(line)
    if not mapped:
        return
    from ..nodes import IRLineMarker
    out.append(IRLineMarker(file=mapped[0], line=mapped[1]))


def _maybe_unregister_manual_free(gen, expr):
    """If *expr* is `<managed_local>.free()`/`.destroy()`, the user is managing
    that variable manually — drop it from auto scope-release so it isn't
    destroyed a second time (double-free). The variable stays valid (unlike
    delete, which NULLs it), so code like `arr.free(); arr.isEmpty();` keeps
    working."""
    from ...ast_nodes import CallExpr, FieldAccessExpr
    if not isinstance(expr, CallExpr):
        return
    callee = expr.callee
    if not isinstance(callee, FieldAccessExpr) or callee.field not in ("free", "destroy"):
        return
    recv = callee.obj
    if isinstance(recv, Identifier):
        gen.unregister_managed_var(recv.name)


def lower_stmt(gen: IRGenerator, node) -> list[IRStmt]:
    """Lower a single AST statement to one or more IRStmts."""
    from .control_flow import (
        _lower_c_for,
        _lower_delete,
        _lower_for_in,
        _lower_if,
        _lower_switch,
        _lower_throw,
        _lower_try_catch,
    )

    if isinstance(node, VarDeclStmt):
        return _lower_var_decl(gen, node)

    if isinstance(node, ReturnStmt):
        # When the `return` is lexically inside a try block, the try's normal-exit
        # cleanup-discard + try-stack pop would be skipped (they sit after the
        # `return` as dead code). Emit them here, after the managed-local release
        # but before the `return`, so the returned object's cleanup is discarded
        # (it escapes — must stay alive) and the try level is popped.
        try_pop = _emit_return_try_pop(gen)
        if node.value is None:
            return (_emit_return_release(gen, None) + try_pop
                    + [IRReturn(value=None)])
        if isinstance(node.value, Identifier):
            val = lower_expr(gen, node.value)
            value_type = gen.analyzed.node_types.get(id(node.value))
            coerced = coerce_value_to_string(gen, gen.current_return_type,
                                             value_type, val)
            if coerced is not val:
                release_stmts = _emit_return_release(gen, None)
                if not release_stmts and not try_pop:
                    return [IRReturn(value=_maybe_launder_return(gen, coerced))]
                tmp = gen.fresh_temp("__btrc_ret")
                decl = IRVarDecl(c_type=CType(text=gen.current_return_c_type),
                                 name=tmp, init=coerced)
                return ([decl] + release_stmts + try_pop
                        + [IRReturn(value=_maybe_launder_return(
                            gen, IRVar(name=tmp)))])
            # Returning a bare local transfers ownership to the caller, so it is
            # excluded from the scope release rather than being decref'd.
            release_stmts = _emit_return_release(gen, node.value.name)
            return (release_stmts + try_pop
                    + [IRReturn(value=_maybe_launder_return(gen, val))])
        # Returning a non-trivial expression.
        val = lower_expr(gen, node.value)
        value_type = gen.analyzed.node_types.get(id(node.value))
        val = coerce_value_to_string(gen, gen.current_return_type, value_type, val)
        release_stmts = _emit_return_release(gen, None)
        if not release_stmts and not try_pop:
            # Nothing to release: a plain `return expr;` is correct and needs no
            # temp. This is the common case (most functions have no managed
            # locals) and keeps the output minimal.
            return [IRReturn(value=_maybe_launder_return(gen, val))]
        # Managed locals must be released AFTER the value is computed (so the
        # expression may still reference them) but BEFORE returning — otherwise
        # the release frees objects the return expression still uses (a
        # use-after-free, e.g. `return o.field` where `o` is scope-managed). So
        # stash the value in a temp, release, then return the temp. The temp uses
        # the function's concrete C return type (gen.current_return_c_type, set at
        # every body-lowering entry point): never __auto_type (a GNU extension
        # banned by the strict-C11 rule), and never the expression's analyzer type
        # (which drops pointer depth — a method returning `ExecResult` is C type
        # `ExecResult*`, so that would emit `ExecResult t = <ExecResult*>`).
        tmp = gen.fresh_temp("__btrc_ret")
        decl = IRVarDecl(c_type=CType(text=gen.current_return_c_type),
                         name=tmp, init=val)
        return ([decl] + release_stmts + try_pop
                + [IRReturn(value=_maybe_launder_return(gen, IRVar(name=tmp)))])

    if isinstance(node, IfStmt):
        return [_lower_if(gen, node)]

    if isinstance(node, WhileStmt):
        return [IRWhile(
            condition=lower_expr(gen, node.condition),
            body=_lower_loop_body(gen, node.body),
        )]

    if isinstance(node, DoWhileStmt):
        return [IRDoWhile(
            body=_lower_loop_body(gen, node.body),
            condition=lower_expr(gen, node.condition),
        )]

    if isinstance(node, ForInStmt):
        return _lower_for_in(gen, node)

    if isinstance(node, CForStmt):
        return [_lower_c_for(gen, node)]

    if isinstance(node, ParallelForStmt):
        # Parallel for -> regular for (no GPU support yet)
        return _lower_for_in(gen, node)

    if isinstance(node, SwitchStmt):
        return [_lower_switch(gen, node)]

    if isinstance(node, BreakStmt):
        return _emit_loop_exit_release(gen) + [IRBreak()]

    if isinstance(node, ContinueStmt):
        return _emit_loop_exit_release(gen) + [IRContinue()]

    if isinstance(node, ExprStmt):
        from ...ast_nodes import AssignExpr
        # ARC: field assignment implicit keep
        if isinstance(node.expr, AssignExpr):
            from .fields import get_field_assign_arc_stmts
            pre, post = get_field_assign_arc_stmts(gen, node.expr)
            if pre or post:
                return pre + [IRExprStmt(expr=lower_expr(gen, node.expr))] + post
        # ARC: emit rc++ for keep params before the call and release any
        # owning-temporary arguments after it. Overrides registered by
        # _keep_call_arc_stmts must be active while the call is lowered (so the
        # call uses the hoisted temp), then cleared.
        pre_stmts, post_stmts = _keep_call_arc_stmts(gen, node.expr)
        call_stmt = IRExprStmt(expr=lower_expr(gen, node.expr))
        if post_stmts:
            gen._owning_temp_overrides.clear()
        # ARC: an explicit `v.free()`/`v.destroy()` means the user manages this
        # local; drop it from auto scope-release so it isn't destroyed twice.
        _maybe_unregister_manual_free(gen, node.expr)
        return pre_stmts + [call_stmt] + post_stmts

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
        # keep expr -> expr->__rc++
        expr = lower_expr(gen, node.expr)
        return [IRExprStmt(expr=IRUnaryOp(
            op="++", operand=IRFieldAccess(obj=expr, field="__rc", arrow=True),
            prefix=False))]

    if isinstance(node, ReleaseStmt):
        # release expr -> if (--expr->__rc <= 0) destroy(expr); expr = NULL;
        return _lower_release(gen, node)

    raise unsupported_node("statement", node)


def _lower_loop_body(gen: IRGenerator, body: Block | None) -> IRBlock:
    gen.push_loop_scope()
    try:
        return lower_block(gen, body)
    finally:
        gen.pop_loop_scope()


def _quick_text(expr) -> str:
    """Render an IR expression as inline C text for use in for-loop headers."""
    from ..nodes import (
        IRAddressOf,
        IRCast,
        IRDeref,
        IRFieldAccess,
        IRRawC,
        IRSizeof,
        IRTernary,
        IRUnaryOp,
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
    raise unsupported_node("IR expression", expr)
