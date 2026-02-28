"""Statement lowering: AST stmt -> IRStmt.

Main dispatch (lower_block, lower_stmt) and the _quick_text utility.
Variable declarations live in variables.py; ARC scope-release logic
lives in arc.py; control-flow lowering lives in control_flow.py.
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
from .variables import _lower_var_decl, _emit_keep_for_call
from .arc import _emit_scope_release, _emit_return_release, _lower_release

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
        # Parallel for -> regular for (no GPU support yet)
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
        # keep expr -> expr->__rc++
        expr = lower_expr(gen, node.expr)
        return [IRExprStmt(expr=IRUnaryOp(
            op="++", operand=IRFieldAccess(obj=expr, field="__rc", arrow=True),
            prefix=False))]

    if isinstance(node, ReleaseStmt):
        # release expr -> if (--expr->__rc <= 0) destroy(expr); expr = NULL;
        return _lower_release(gen, node)

    return [IRRawC(text=f"/* unhandled stmt: {type(node).__name__} */")]


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
