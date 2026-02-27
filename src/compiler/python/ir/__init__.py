"""IR package: nodes, optimizer, emitter, and runtime helpers."""

from .nodes import (
    CType, IRModule, IRHelperDecl, IRStructDef, IRStructField,
    IRFunctionDef, IRParam, IRBlock, IRStmt, IRVarDecl, IRAssign,
    IRReturn, IRIf, IRWhile, IRDoWhile, IRFor, IRSwitch, IRCase,
    IRExprStmt, IRRawC, IRBreak, IRContinue, IRExpr, IRLiteral,
    IRVar, IRBinOp, IRUnaryOp, IRCall, IRFieldAccess, IRCast,
    IRTernary, IRSizeof, IRIndex, IRAddressOf, IRDeref, IRRawExpr,
)
from .optimizer import optimize
from .emitter import CEmitter
