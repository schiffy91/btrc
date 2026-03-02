"""GPU function validation for @gpu-annotated functions.

Validates that @gpu functions only use the WGSL-compatible subset of btrc:
- Parameters must be scalar primitives or typed arrays
- Return type must be void or typed array
- Body must use only arithmetic, comparisons, if/else, for, while, var decls
- Rejects: strings, classes, collections, print, new/delete, lambdas, try/catch
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..ast_nodes import (
    AssignExpr,
    BinaryExpr,
    Block,
    BoolLiteral,
    BreakStmt,
    CallExpr,
    CastExpr,
    CForStmt,
    ContinueStmt,
    DeleteStmt,
    ExprStmt,
    FieldAccessExpr,
    FloatLiteral,
    ForInStmt,
    FStringLiteral,
    FunctionDecl,
    Identifier,
    IfStmt,
    IndexExpr,
    IntLiteral,
    KeepStmt,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    MethodDecl,
    NewExpr,
    NullLiteral,
    ReleaseStmt,
    ReturnStmt,
    SelfExpr,
    SpawnExpr,
    StringLiteral,
    TernaryExpr,
    ThrowStmt,
    TryCatchStmt,
    TypeExpr,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)

if TYPE_CHECKING:
    from .core import AnalyzerBase

# Types allowed in @gpu functions
_GPU_SCALAR_TYPES = {"int", "float", "bool"}
_GPU_ARRAY_ELEM_TYPES = {"int", "float"}

# Built-in GPU functions
GPU_BUILTINS = {
    "gpu_id": TypeExpr(base="int", generic_args=[], pointer_depth=0,
                       is_array=False, array_size=None, line=0, col=0),
}


def validate_gpu_function(analyzer: AnalyzerBase, func) -> None:
    """Validate that a @gpu function uses only WGSL-compatible constructs."""
    name = func.name
    line, col = func.line, func.col

    # Validate parameters
    for param in func.params:
        _validate_gpu_type(analyzer, param.type, f"parameter '{param.name}'",
                           name, line, col, allow_array=True)

    # Validate return type
    ret = func.return_type
    if ret and ret.base != "void":
        if ret.is_array:
            if ret.base not in _GPU_ARRAY_ELEM_TYPES:
                analyzer._error(
                    f"@gpu function '{name}' return type must be void or a "
                    f"typed array (int[] or float[]), got '{ret.base}[]'",
                    line, col)
        else:
            analyzer._error(
                f"@gpu function '{name}' must return void or a typed array, "
                f"got '{ret.base}'", line, col)

    # Validate body
    if func.body:
        _validate_gpu_block(analyzer, func.body, name)


def _validate_gpu_type(analyzer, type_expr: TypeExpr, context: str,
                       func_name: str, line: int, col: int,
                       allow_array: bool = False) -> None:
    """Validate a type is GPU-compatible."""
    if type_expr is None:
        return

    if type_expr.is_nullable:
        analyzer._error(
            f"@gpu function '{func_name}': nullable types not allowed "
            f"in {context}", line, col)
        return

    if type_expr.pointer_depth > 0:
        analyzer._error(
            f"@gpu function '{func_name}': pointer types not allowed "
            f"in {context}", line, col)
        return

    if type_expr.is_array and allow_array:
        if type_expr.base not in _GPU_ARRAY_ELEM_TYPES:
            analyzer._error(
                f"@gpu function '{func_name}': array element type must be "
                f"int or float in {context}, got '{type_expr.base}'",
                line, col)
        return

    if type_expr.is_array and not allow_array:
        analyzer._error(
            f"@gpu function '{func_name}': array types not allowed "
            f"in {context}", line, col)
        return

    if type_expr.generic_args:
        analyzer._error(
            f"@gpu function '{func_name}': generic types not allowed "
            f"in {context}", line, col)
        return

    if type_expr.base not in _GPU_SCALAR_TYPES:
        analyzer._error(
            f"@gpu function '{func_name}': type '{type_expr.base}' not "
            f"allowed in {context} (use int, float, or bool)", line, col)


def _validate_gpu_block(analyzer, block: Block, func_name: str) -> None:
    """Validate all statements in a block are GPU-compatible."""
    if block is None:
        return
    for stmt in block.statements:
        _validate_gpu_stmt(analyzer, stmt, func_name)


def _validate_gpu_stmt(analyzer, stmt, func_name: str) -> None:
    """Validate a single statement is GPU-compatible."""
    line = getattr(stmt, 'line', 0)
    col = getattr(stmt, 'col', 0)

    if isinstance(stmt, VarDeclStmt):
        if stmt.type:
            _validate_gpu_type(analyzer, stmt.type, f"variable '{stmt.name}'",
                               func_name, line, col, allow_array=True)
        if stmt.initializer:
            _validate_gpu_expr(analyzer, stmt.initializer, func_name)

    elif isinstance(stmt, ReturnStmt):
        if stmt.value:
            _validate_gpu_expr(analyzer, stmt.value, func_name)

    elif isinstance(stmt, IfStmt):
        _validate_gpu_expr(analyzer, stmt.condition, func_name)
        _validate_gpu_block(analyzer, stmt.then_block, func_name)
        if stmt.else_block:
            eb = stmt.else_block
            if hasattr(eb, 'body'):
                _validate_gpu_block(analyzer, eb.body, func_name)
            if hasattr(eb, 'if_stmt'):
                _validate_gpu_stmt(analyzer, eb.if_stmt, func_name)

    elif isinstance(stmt, WhileStmt):
        _validate_gpu_expr(analyzer, stmt.condition, func_name)
        _validate_gpu_block(analyzer, stmt.body, func_name)

    elif isinstance(stmt, CForStmt):
        if stmt.init:
            init = stmt.init
            if hasattr(init, 'var_decl'):
                _validate_gpu_stmt(analyzer, init.var_decl, func_name)
            if hasattr(init, 'expression'):
                _validate_gpu_expr(analyzer, init.expression, func_name)
        if stmt.condition:
            _validate_gpu_expr(analyzer, stmt.condition, func_name)
        if stmt.update:
            _validate_gpu_expr(analyzer, stmt.update, func_name)
        _validate_gpu_block(analyzer, stmt.body, func_name)

    elif isinstance(stmt, ExprStmt):
        _validate_gpu_expr(analyzer, stmt.expr, func_name)

    elif isinstance(stmt, (BreakStmt, ContinueStmt)):
        pass  # allowed

    elif isinstance(stmt, (ForInStmt, TryCatchStmt, ThrowStmt,
                           DeleteStmt, KeepStmt, ReleaseStmt)):
        analyzer._error(
            f"@gpu function '{func_name}': '{type(stmt).__name__}' "
            f"not allowed in GPU functions", line, col)

    else:
        analyzer._error(
            f"@gpu function '{func_name}': unsupported statement "
            f"'{type(stmt).__name__}'", line, col)


def _validate_gpu_expr(analyzer, expr, func_name: str) -> None:
    """Validate an expression is GPU-compatible."""
    if expr is None:
        return

    line = getattr(expr, 'line', 0)
    col = getattr(expr, 'col', 0)

    if isinstance(expr, (IntLiteral, FloatLiteral, BoolLiteral, NullLiteral)):
        pass  # allowed

    elif isinstance(expr, Identifier):
        pass  # allowed

    elif isinstance(expr, BinaryExpr):
        _validate_gpu_expr(analyzer, expr.left, func_name)
        _validate_gpu_expr(analyzer, expr.right, func_name)

    elif isinstance(expr, UnaryExpr):
        _validate_gpu_expr(analyzer, expr.operand, func_name)

    elif isinstance(expr, CallExpr):
        if isinstance(expr.callee, Identifier):
            name = expr.callee.name
            if name == "print":
                analyzer._error(
                    f"@gpu function '{func_name}': print() not allowed "
                    f"in GPU functions", line, col)
                return
            if name in GPU_BUILTINS:
                return  # gpu_id() is allowed
        else:
            _validate_gpu_expr(analyzer, expr.callee, func_name)
        for arg in expr.args:
            _validate_gpu_expr(analyzer, arg, func_name)

    elif isinstance(expr, IndexExpr):
        _validate_gpu_expr(analyzer, expr.obj, func_name)
        _validate_gpu_expr(analyzer, expr.index, func_name)

    elif isinstance(expr, AssignExpr):
        _validate_gpu_expr(analyzer, expr.target, func_name)
        _validate_gpu_expr(analyzer, expr.value, func_name)

    elif isinstance(expr, TernaryExpr):
        _validate_gpu_expr(analyzer, expr.condition, func_name)
        _validate_gpu_expr(analyzer, expr.true_expr, func_name)
        _validate_gpu_expr(analyzer, expr.false_expr, func_name)

    elif isinstance(expr, CastExpr):
        _validate_gpu_expr(analyzer, expr.expr, func_name)

    elif isinstance(expr, (StringLiteral, FStringLiteral)):
        analyzer._error(
            f"@gpu function '{func_name}': strings not allowed "
            f"in GPU functions", line, col)

    elif isinstance(expr, (ListLiteral, MapLiteral)):
        analyzer._error(
            f"@gpu function '{func_name}': collection literals not allowed "
            f"in GPU functions", line, col)

    elif isinstance(expr, (NewExpr, SelfExpr, SpawnExpr, LambdaExpr)):
        analyzer._error(
            f"@gpu function '{func_name}': '{type(expr).__name__}' "
            f"not allowed in GPU functions", line, col)

    elif isinstance(expr, FieldAccessExpr):
        _validate_gpu_expr(analyzer, expr.obj, func_name)

    else:
        pass  # allow unknown exprs through (analyzer will catch type errors)
