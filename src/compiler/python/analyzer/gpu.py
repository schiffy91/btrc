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
    Block,
    BreakStmt,
    CForStmt,
    ContinueStmt,
    DeleteStmt,
    ExprStmt,
    ForInStmt,
    Identifier,
    IfStmt,
    KeepStmt,
    ReleaseStmt,
    ReturnStmt,
    ThrowStmt,
    TryCatchStmt,
    TypeExpr,
    VarDeclStmt,
    WhileStmt,
)
from .gpu_exprs import (
    GpuValidationContext,
    is_gpu_expression_statement,
    is_gpu_update_statement,
    validate_gpu_expr,
)

if TYPE_CHECKING:
    from .core import AnalyzerBase

# Types allowed in @gpu functions
_GPU_SCALAR_TYPES = {"int", "float", "bool"}
_GPU_ARRAY_ELEM_TYPES = {"int", "float"}


def validate_gpu_function(analyzer: AnalyzerBase, func) -> None:
    """Validate the analyzed function against the WGSL kernel contract."""
    name = func.name
    line, col = func.line, func.col

    # Validate parameters
    prior_array_params: set[str] = set()
    for param in func.params:
        _validate_gpu_type(analyzer, param.type, f"parameter '{param.name}'", name, line, col, allow_array=True)
        canonical = analyzer._canonical_type(param.type)
        if canonical is not None and canonical.is_array and param.default is not None:
            actual = analyzer._infer_type(param.default)
            inherited_capacity = isinstance(param.default, Identifier) and param.default.name in prior_array_params
            if (
                actual is not None
                and not inherited_capacity
                and not analyzer._array_target_has_capacity(param.default, actual)
            ):
                analyzer.context.error(
                    f"Default for parameter '{param.name}' has no provable readable GPU buffer capacity",
                    getattr(param.default, "line", line),
                    getattr(param.default, "col", col),
                )
        if canonical is not None and canonical.is_array:
            prior_array_params.add(param.name)

    # Validate return type
    ret = func.return_type
    if ret and not analyzer._is_nonpointer_void_object(ret):
        if ret.is_array:
            if ret.base not in _GPU_ARRAY_ELEM_TYPES:
                analyzer.context.error(
                    f"@gpu function '{name}' return type must be void or a "
                    f"typed array (int[] or float[]), got '{ret.base}[]'",
                    line,
                    col,
                )
        else:
            analyzer.context.error(
                f"@gpu function '{name}' must return void or a typed array, got '{ret.base}'", line, col
            )

    scalar_params = frozenset(param.name for param in func.params if not param.type.is_array)
    array_params = frozenset(param.name for param in func.params if param.type.is_array)
    context = GpuValidationContext(
        analyzer=analyzer,
        function_name=name,
        scalar_params=scalar_params,
        array_params=array_params,
        scopes=[],
    )
    if func.body:
        _validate_gpu_block(context, func.body)


def _validate_gpu_type(
    analyzer, type_expr: TypeExpr, context: str, func_name: str, line: int, col: int, allow_array: bool = False
) -> None:
    """Validate a type is GPU-compatible."""
    if type_expr is None:
        return

    if type_expr.is_nullable:
        analyzer.context.error(f"@gpu function '{func_name}': nullable types not allowed in {context}", line, col)
        return

    if type_expr.pointer_depth > 0:
        analyzer.context.error(f"@gpu function '{func_name}': pointer types not allowed in {context}", line, col)
        return

    if type_expr.is_array and allow_array:
        if type_expr.is_const or type_expr.is_volatile:
            analyzer.context.error(
                f"@gpu function '{func_name}': GPU array buffers are read-write "
                f"and cannot be const- or volatile-qualified in {context}",
                line,
                col,
            )
            return
        if type_expr.base not in _GPU_ARRAY_ELEM_TYPES:
            analyzer.context.error(
                f"@gpu function '{func_name}': array element type must be "
                f"int or float in {context}, got '{type_expr.base}'",
                line,
                col,
            )
        return

    if type_expr.is_array and not allow_array:
        analyzer.context.error(f"@gpu function '{func_name}': array types not allowed in {context}", line, col)
        return

    if type_expr.generic_args:
        analyzer.context.error(f"@gpu function '{func_name}': generic types not allowed in {context}", line, col)
        return

    if type_expr.base not in _GPU_SCALAR_TYPES:
        analyzer.context.error(
            f"@gpu function '{func_name}': type '{type_expr.base}' not allowed in {context} (use int, float, or bool)",
            line,
            col,
        )


def _validate_gpu_block(context: GpuValidationContext, block: Block) -> None:
    """Validate all statements in a block are GPU-compatible."""
    if block is None:
        return
    context.push_scope()
    for stmt in block.statements:
        _validate_gpu_stmt(context, stmt)
    context.pop_scope()


def _validate_gpu_stmt(context: GpuValidationContext, stmt) -> None:
    """Validate a single statement is GPU-compatible."""
    line = getattr(stmt, "line", 0)
    col = getattr(stmt, "col", 0)
    analyzer = context.analyzer
    func_name = context.function_name

    if isinstance(stmt, VarDeclStmt):
        if stmt.type:
            _validate_gpu_type(analyzer, stmt.type, f"variable '{stmt.name}'", func_name, line, col)
        if stmt.initializer:
            validate_gpu_expr(context, stmt.initializer)
        context.declare(stmt.name)

    elif isinstance(stmt, ReturnStmt):
        if stmt.value:
            validate_gpu_expr(context, stmt.value)

    elif isinstance(stmt, IfStmt):
        validate_gpu_expr(context, stmt.condition)
        _validate_gpu_condition(context, stmt.condition)
        _validate_gpu_block(context, stmt.then_block)
        if stmt.else_block:
            eb = stmt.else_block
            if hasattr(eb, "body"):
                _validate_gpu_block(context, eb.body)
            if hasattr(eb, "if_stmt"):
                _validate_gpu_stmt(context, eb.if_stmt)

    elif isinstance(stmt, WhileStmt):
        validate_gpu_expr(context, stmt.condition)
        _validate_gpu_condition(context, stmt.condition)
        _validate_gpu_block(context, stmt.body)

    elif isinstance(stmt, CForStmt):
        context.push_scope()
        if stmt.init:
            init = stmt.init
            if hasattr(init, "var_decl"):
                _validate_gpu_stmt(context, init.var_decl)
            if hasattr(init, "expression"):
                _validate_gpu_update(context, init.expression)
        if stmt.condition:
            validate_gpu_expr(context, stmt.condition)
            _validate_gpu_condition(context, stmt.condition)
        if stmt.update:
            _validate_gpu_update(context, stmt.update)
        _validate_gpu_block(context, stmt.body)
        context.pop_scope()

    elif isinstance(stmt, ExprStmt):
        if not is_gpu_expression_statement(stmt.expr):
            context.error(
                "expression statement must be an assignment, increment, decrement, or WGSL built-in call",
                stmt.expr,
            )
        validate_gpu_expr(context, stmt.expr, update=is_gpu_update_statement(stmt.expr))

    elif isinstance(stmt, (BreakStmt, ContinueStmt)):
        pass  # allowed

    elif isinstance(stmt, (ForInStmt, TryCatchStmt, ThrowStmt, DeleteStmt, KeepStmt, ReleaseStmt)):
        analyzer.context.error(
            f"@gpu function '{func_name}': '{type(stmt).__name__}' not allowed in GPU functions", line, col
        )

    else:
        analyzer.context.error(f"@gpu function '{func_name}': unsupported statement '{type(stmt).__name__}'", line, col)


def _validate_gpu_update(context: GpuValidationContext, expression) -> None:
    if not is_gpu_update_statement(expression):
        context.error("for-loop initializer/update must update a variable or buffer element", expression)
    validate_gpu_expr(context, expression, update=is_gpu_update_statement(expression))


def _validate_gpu_condition(context: GpuValidationContext, expression) -> None:
    type_expr = context.type_of(expression)
    if type_expr is not None and type_expr.base != "bool":
        context.error(f"control-flow condition must be bool, got '{type_expr.base}'", expression)
