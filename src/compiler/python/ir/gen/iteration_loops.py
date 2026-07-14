"""Range and C-style loop lowering."""

from __future__ import annotations

from ...ast_nodes import CForStmt, ForInitExpr, ForInitVar
from ..nodes import (
    CType,
    IRBinOp,
    IRExprStmt,
    IRFor,
    IRLiteral,
    IRStmt,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .types import type_to_c


def _lower_range_for(gen, var_name: str, args: list, body) -> list[IRStmt]:
    """Lower ``for x in range(...)`` to one structured C loop."""
    from .expressions import lower_expr
    from .statements import _lower_loop_body

    body_block = _lower_loop_body(gen, body)
    start = IRLiteral(text="0")
    end = IRLiteral(text="0")
    step = IRLiteral(text="1")
    if args:
        if len(args) == 1:
            end = lower_expr(gen, args[0])
        else:
            start = lower_expr(gen, args[0])
            end = lower_expr(gen, args[1])
        if len(args) >= 3:
            step = lower_expr(gen, args[2])

    condition = IRBinOp(left=IRVar(name=var_name), op="<", right=end)
    update = IRUnaryOp(op="++", operand=IRVar(name=var_name), prefix=False)
    if len(args) >= 3:
        condition = IRTernary(
            condition=IRBinOp(left=step, op=">", right=IRLiteral(text="0")),
            true_expr=condition,
            false_expr=IRBinOp(left=IRVar(name=var_name), op=">", right=end),
        )
        update = IRBinOp(left=IRVar(name=var_name), op="+=", right=step)
    return [
        IRFor(
            init=IRVarDecl(c_type=CType(text="int"), name=var_name, init=start),
            condition=condition,
            update=update,
            body=body_block,
        )
    ]


def _lower_c_for(gen, node: CForStmt) -> IRFor:
    """Lower a C-style for statement."""
    from .expressions import lower_expr
    from .statements import _lower_loop_body

    init_node = None
    if isinstance(node.init, ForInitVar):
        declaration = node.init.var_decl
        c_type = type_to_c(declaration.type) if declaration.type else "int"
        initializer = lower_expr(gen, declaration.initializer) if declaration.initializer else None
        init_node = IRVarDecl(
            c_type=CType(text=c_type),
            name=declaration.name,
            init=initializer,
        )
    elif isinstance(node.init, ForInitExpr):
        init_node = IRExprStmt(expr=lower_expr(gen, node.init.expression))

    condition = lower_expr(gen, node.condition) if node.condition else IRLiteral(text="1")
    update = lower_expr(gen, node.update) if node.update else None
    return IRFor(
        init=init_node,
        condition=condition,
        update=update,
        body=_lower_loop_body(gen, node.body),
    )


__all__ = ["_lower_c_for", "_lower_range_for"]
