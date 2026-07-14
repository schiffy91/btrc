"""Feature-presence scans used to select runtime dependencies."""

from ...ast_nodes import ClassDecl, FunctionDecl, MethodDecl, PropertyDecl


def uses_trycatch(decl) -> bool:
    """Return whether a declaration contains exception syntax."""

    if isinstance(decl, FunctionDecl):
        return _block_uses_trycatch(getattr(decl, "body", None))
    if isinstance(decl, ClassDecl):
        for member in decl.members:
            if isinstance(member, MethodDecl) and _block_uses_trycatch(member.body):
                return True
            if isinstance(member, PropertyDecl):
                if _block_uses_trycatch(member.getter_body) or _block_uses_trycatch(member.setter_body):
                    return True
    return False


def _block_uses_trycatch(block) -> bool:
    from ...ast_nodes import (
        Block,
        CForStmt,
        DoWhileStmt,
        ElseBlock,
        ElseIf,
        ForInStmt,
        IfStmt,
        SwitchStmt,
        ThrowStmt,
        TryCatchStmt,
        WhileStmt,
    )

    if not isinstance(block, Block):
        return False
    for statement in block.statements:
        if isinstance(statement, (TryCatchStmt, ThrowStmt)):
            return True
        if isinstance(statement, IfStmt):
            if _block_uses_trycatch(statement.then_block):
                return True
            alternate = statement.else_block
            if isinstance(alternate, ElseBlock):
                if _block_uses_trycatch(alternate.body):
                    return True
            elif isinstance(alternate, ElseIf):
                if _stmt_uses_trycatch(alternate.if_stmt):
                    return True
        elif isinstance(statement, (WhileStmt, DoWhileStmt, ForInStmt, CForStmt)):
            if _block_uses_trycatch(statement.body):
                return True
        elif isinstance(statement, SwitchStmt):
            if any(_stmt_uses_trycatch(child) for case in statement.cases for child in case.body):
                return True
    return False


def _stmt_uses_trycatch(statement) -> bool:
    from ...ast_nodes import (
        CForStmt,
        DoWhileStmt,
        ElseBlock,
        ElseIf,
        ForInStmt,
        IfStmt,
        SwitchStmt,
        ThrowStmt,
        TryCatchStmt,
        WhileStmt,
    )

    if isinstance(statement, (TryCatchStmt, ThrowStmt)):
        return True
    if isinstance(statement, IfStmt):
        if _block_uses_trycatch(statement.then_block):
            return True
        alternate = statement.else_block
        if isinstance(alternate, ElseBlock):
            return _block_uses_trycatch(alternate.body)
        if isinstance(alternate, ElseIf):
            return _stmt_uses_trycatch(alternate.if_stmt)
    elif isinstance(statement, (WhileStmt, DoWhileStmt, ForInStmt, CForStmt)):
        return _block_uses_trycatch(statement.body)
    elif isinstance(statement, SwitchStmt):
        return any(_stmt_uses_trycatch(child) for case in statement.cases for child in case.body)
    return False
