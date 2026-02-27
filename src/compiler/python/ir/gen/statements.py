"""Statement lowering: AST stmt → IRStmt.

Main dispatch (lower_block, lower_stmt), variable declarations, and the
_quick_text utility.  Control-flow lowering lives in control_flow.py.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import (
    Block, BreakStmt, CForStmt, ContinueStmt, DeleteStmt, DoWhileStmt,
    ExprStmt, ForInStmt, ForInitExpr, ForInitVar, IfStmt, ElseBlock,
    ElseIf, ParallelForStmt, ReturnStmt, SwitchStmt, ThrowStmt,
    TryCatchStmt, VarDeclStmt, WhileStmt, TypeExpr, CallExpr, Identifier,
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
    stmts = []
    for s in block.statements:
        ir_stmts = lower_stmt(gen, s)
        stmts.extend(ir_stmts)
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
        return [IRReturn(value=val)]

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
        return [IRExprStmt(expr=lower_expr(gen, node.expr))]

    if isinstance(node, DeleteStmt):
        return _lower_delete(gen, node)

    if isinstance(node, TryCatchStmt):
        return _lower_try_catch(gen, node)

    if isinstance(node, ThrowStmt):
        return _lower_throw(gen, node)

    return [IRRawC(text=f"/* unhandled stmt: {type(node).__name__} */")]


def _lower_var_decl(gen: IRGenerator, node: VarDeclStmt) -> list[IRStmt]:
    from ...ast_nodes import BraceInitializer, CallExpr, Identifier, TypeExpr as TE
    from .types import is_collection_type, mangle_generic_type

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
        # Empty brace initializer on collection types → _new() call
        if (isinstance(node.initializer, BraceInitializer)
                and not node.initializer.elements
                and node.type and is_collection_type(node.type)):
            mangled = mangle_generic_type(node.type.base, node.type.generic_args)
            init = IRCall(callee=f"{mangled}_new", args=[])
        # Empty [] on List-typed variable → correct List_T_new()
        elif (isinstance(node.initializer, ListLiteral)
              and not node.initializer.elements
              and node.type and node.type.base == "List" and node.type.generic_args):
            mangled = mangle_generic_type("List", node.type.generic_args)
            init = IRCall(callee=f"{mangled}_new", args=[])
        # Empty {} on Map-typed variable → correct Map_K_V_new()
        elif (isinstance(node.initializer, MapLiteral)
              and not node.initializer.entries
              and node.type and node.type.base == "Map" and node.type.generic_args):
            mangled = mangle_generic_type("Map", node.type.generic_args)
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
    return [IRVarDecl(c_type=CType(text=c_type), name=node.name, init=init)]


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
