"""Control flow statement lowering: if, switch, delete, try/catch, throw."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import (
    DeleteStmt, ElseBlock, ElseIf, IfStmt, SwitchStmt,
    ThrowStmt, TryCatchStmt,
)
from ..nodes import (
    CType, IRBlock, IRCase, IRExprStmt, IRIf, IRRawC, IRRawExpr,
    IRStmt, IRSwitch, IRVarDecl, IRVar, IRCall,
)

if TYPE_CHECKING:
    from .generator import IRGenerator

# Re-export iteration lowering so statements.py can import from one place
from .iterations import _lower_for_in, _lower_range_for, _lower_c_for  # noqa: F401


def _lower_if(gen: IRGenerator, node: IfStmt) -> IRIf:
    from .statements import lower_block
    cond = _lower_expr(gen, node.condition)
    then = lower_block(gen, node.then_block)
    else_block = None
    if node.else_block:
        if isinstance(node.else_block, ElseBlock):
            else_block = lower_block(gen, node.else_block.body)
        elif isinstance(node.else_block, ElseIf):
            # Chain: else if → IRIf inside an else block
            inner = _lower_if(gen, node.else_block.if_stmt)
            else_block = IRBlock(stmts=[inner])
    return IRIf(condition=cond, then_block=then, else_block=else_block)


def _lower_switch(gen: IRGenerator, node: SwitchStmt) -> IRSwitch:
    from .statements import lower_stmt
    val = _lower_expr(gen, node.value)
    cases = []
    for c in node.cases:
        case_val = _lower_expr(gen, c.value) if c.value else None
        case_stmts = []
        for s in c.body:
            case_stmts.extend(lower_stmt(gen, s))
        cases.append(IRCase(value=case_val, body=case_stmts))
    return IRSwitch(value=val, cases=cases)


def _lower_delete(gen: IRGenerator, node: DeleteStmt) -> list[IRStmt]:
    """Lower delete expr → destroy or free (class-table based)."""
    from .types import mangle_generic_type, is_generic_class_type
    obj = _lower_expr(gen, node.expr)
    obj_type = gen.analyzed.node_types.get(id(node.expr))
    if obj_type and obj_type.base in gen.analyzed.class_table:
        cls_info = gen.analyzed.class_table[obj_type.base]
        if obj_type.generic_args and cls_info.generic_params:
            mangled = mangle_generic_type(obj_type.base, obj_type.generic_args)
            # Use free() if the class defines it, otherwise destroy()
            dtor = "free" if "free" in cls_info.methods else "destroy"
            callee = f"{mangled}_{dtor}"
        else:
            callee = f"{obj_type.base}_destroy"
        return [IRExprStmt(expr=IRCall(callee=callee, args=[obj]))]
    # Non-class: just free
    return [IRExprStmt(expr=IRCall(callee="free", args=[obj]))]


def _lower_try_catch(gen: IRGenerator, node: TryCatchStmt) -> list[IRStmt]:
    """Lower try/catch to setjmp/longjmp boilerplate."""
    from .statements import lower_block
    gen.use_helper("__btrc_trycatch_globals")
    gen.use_helper("__btrc_throw")
    stmts: list[IRStmt] = []

    # Emit raw setjmp boilerplate
    stmts.append(IRRawC(text=(
        "if (!__btrc_try_stack) {\n"
        "    __btrc_try_stack = (jmp_buf*)malloc(sizeof(jmp_buf) * __btrc_try_cap);\n"
        "}\n"
        "if (__btrc_try_top + 1 >= __btrc_try_cap) {\n"
        "    __btrc_try_cap *= 2;\n"
        "    __btrc_try_stack = (jmp_buf*)realloc(__btrc_try_stack, sizeof(jmp_buf) * __btrc_try_cap);\n"
        "}\n"
        "__btrc_try_top++;"
    ), helper_refs=["__btrc_trycatch_globals", "__btrc_throw"]))

    # if (setjmp(...) == 0) { try block } else { catch block }
    try_body = lower_block(gen, node.try_block)
    try_body.stmts.append(IRRawC(text="__btrc_try_top--;"))
    catch_body = lower_block(gen, node.catch_block)
    if node.catch_var:
        catch_body.stmts.insert(0, IRVarDecl(
            c_type=CType(text="const char*"), name=node.catch_var,
            init=IRVar(name="__btrc_error_msg")))

    stmts.append(IRIf(
        condition=IRRawExpr(text="setjmp(__btrc_try_stack[__btrc_try_top]) == 0"),
        then_block=try_body,
        else_block=catch_body,
    ))

    if node.finally_block:
        finally_stmts = lower_block(gen, node.finally_block)
        stmts.extend(finally_stmts.stmts)

    return stmts


def _lower_throw(gen: IRGenerator, node: ThrowStmt) -> list[IRStmt]:
    gen.use_helper("__btrc_throw")
    expr = _lower_expr(gen, node.expr)
    return [IRExprStmt(expr=IRCall(callee="__btrc_throw", args=[expr],
                                   helper_ref="__btrc_throw"))]


def _lower_expr(gen, node):
    """Convenience wrapper to avoid circular import at module level."""
    from .expressions import lower_expr
    return lower_expr(gen, node)
