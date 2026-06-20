"""Control flow statement lowering: if, switch, delete, try/catch, throw."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    DeleteStmt,
    ElseBlock,
    ElseIf,
    IfStmt,
    SwitchStmt,
    ThrowStmt,
    TryCatchStmt,
)
from ..nodes import (
    CType,
    IRAssign,
    IRBlock,
    IRCall,
    IRCase,
    IRExprStmt,
    IRIf,
    IRLiteral,
    IRRawC,
    IRRawExpr,
    IRStmt,
    IRSwitch,
    IRVar,
    IRVarDecl,
)

if TYPE_CHECKING:
    from .generator import IRGenerator

# Re-export iteration lowering so statements.py can import from one place
from .iterations import _lower_c_for, _lower_for_in, _lower_range_for  # noqa: F401


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
    """Lower delete expr → destroy or free (class-table based), then set NULL."""
    from .types import mangle_generic_type
    obj = _lower_expr(gen, node.expr)
    obj_type = gen.analyzed.node_types.get(id(node.expr))
    if obj_type and obj_type.base in gen.analyzed.class_table:
        cls_info = gen.analyzed.class_table[obj_type.base]
        if obj_type.generic_args and cls_info.generic_params:
            mangled = mangle_generic_type(obj_type.base, obj_type.generic_args)
            # Always use the terminal destructor: destroy() frees both contents
            # (via free() for collections) and the struct.
            callee = f"{mangled}_destroy"
        else:
            callee = f"{obj_type.base}_destroy"
        stmts = [IRExprStmt(expr=IRCall(callee=callee, args=[obj]))]
    else:
        # Non-class: just free
        stmts = [IRExprStmt(expr=IRCall(callee="free", args=[obj]))]
    # ARC: set variable to NULL after delete so scope-exit cleanup skips it
    stmts.append(IRAssign(target=obj, value=IRLiteral(text="NULL")))
    return stmts


def _require_setjmp(gen: IRGenerator):
    """Ensure <setjmp.h> is included.

    Registered at the lowering site so try/catch/throw anywhere — including
    inside lambda bodies, which the generator's declaration pre-scan does
    not reach — always pulls in the header.
    """
    gen.require_runtime_include("setjmp.h")


def _lower_try_catch(gen: IRGenerator, node: TryCatchStmt) -> list[IRStmt]:
    """Lower try/catch to setjmp/longjmp boilerplate."""
    # Mark that everything lowered for this construct (try body, catch, finally)
    # lives inside a try/catch, so class-pointer returns get laundered against
    # the gcc -O2 setjmp cross-branch miscompilation (see _lower_return).
    gen.in_trycatch_depth += 1
    try:
        return _lower_try_catch_inner(gen, node)
    finally:
        gen.in_trycatch_depth -= 1


def _lower_try_catch_inner(gen: IRGenerator, node: TryCatchStmt) -> list[IRStmt]:
    from .statements import lower_block
    _require_setjmp(gen)
    gen.use_helper("__btrc_trycatch_globals")
    gen.use_helper("__btrc_throw")
    stmts: list[IRStmt] = []
    finally_only = node.catch_block is None and node.finally_block is not None
    pending_name = gen.fresh_temp("__btrc_finally_pending") if finally_only else ""
    error_name = gen.fresh_temp("__btrc_finally_error") if finally_only else ""

    # setjmp/longjmp volatile rule: any local variable declared before this
    # try/catch (at any scope in the current function) has indeterminate
    # value after longjmp unless declared volatile (C11 7.13.2.1)
    for vd in gen._func_var_decls:
        vd.is_volatile = True

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
    gen.in_try_depth += 1
    try_body = lower_block(gen, node.try_block)
    gen.in_try_depth -= 1
    # Normal exit: discard cleanup registrations (scope release already freed them)
    # then decrement try level
    if gen._used_helpers & {"__btrc_register_cleanup"}:
        gen.use_helper("__btrc_discard_cleanups")
        try_body.stmts.append(IRExprStmt(expr=IRCall(
            callee="__btrc_discard_cleanups",
            args=[IRVar(name="__btrc_try_top")],
            helper_ref="__btrc_discard_cleanups")))
    try_body.stmts.append(IRRawC(text="__btrc_try_top--;"))
    if finally_only:
        stmts.append(IRRawC(text=f"bool {pending_name} = false;\nchar {error_name}[1024] = \"\";"))
        catch_body = IRBlock(stmts=[
            IRRawC(text=(
                f"{pending_name} = true;\n"
                f"strncpy({error_name}, __btrc_error_msg, 1023);\n"
                f"{error_name}[1023] = '\\0';"
            ))
        ])
    else:
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
        if finally_only:
            stmts.append(IRIf(
                condition=IRVar(name=pending_name),
                then_block=IRBlock(stmts=[
                    IRExprStmt(expr=IRCall(
                        callee="__btrc_throw",
                        args=[IRVar(name=error_name)],
                        helper_ref="__btrc_throw"))
                ]),
            ))

    return stmts


def _lower_throw(gen: IRGenerator, node: ThrowStmt) -> list[IRStmt]:
    _require_setjmp(gen)
    gen.use_helper("__btrc_throw")
    expr = _lower_expr(gen, node.expr)
    return [IRExprStmt(expr=IRCall(callee="__btrc_throw", args=[expr],
                                   helper_ref="__btrc_throw"))]


def _lower_expr(gen, node):
    """Convenience wrapper to avoid circular import at module level."""
    from .expressions import lower_expr
    return lower_expr(gen, node)
