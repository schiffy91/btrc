"""Owned semantic validation for ``@gpu`` kernels."""

from __future__ import annotations

from collections.abc import Callable
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
from ..numeric_literals import NumericLiteralSemantics
from ..type_identity import TypeIdentity
from .declarations.type_resolution import canonical_declaration_type
from .gpu_exprs import GpuExpressionValidator, GpuKernelValidation
from .gpu_type_contracts import GpuIntrinsicResolver

if TYPE_CHECKING:
    from ..ast_nodes import CallExpr, FunctionDecl
    from .analysis_context import AnalysisContext
    from .core_models import Scope
    from .declarations.registry import DeclarationRegistry

_GPU_SCALAR_TYPES = frozenset({"int", "float", "bool"})
_GPU_ARRAY_ELEM_TYPES = frozenset({"int", "float"})


class GpuKernelValidator:
    """Own the complete post-analysis contract for WGSL kernels."""

    def __init__(
        self,
        context: AnalysisContext,
        declarations: DeclarationRegistry,
        node_types: dict[int, TypeExpr],
        numeric_literals: NumericLiteralSemantics,
        type_identity: TypeIdentity,
    ) -> None:
        self._context = context
        self._declarations = declarations
        self._node_types = node_types
        self._type_identity = type_identity
        self._intrinsics = GpuIntrinsicResolver(context, declarations)
        self._expressions = GpuExpressionValidator(
            self._intrinsics,
            numeric_literals,
        )

    def validate(
        self,
        function: FunctionDecl,
        scope: Scope,
        *,
        array_target_has_capacity: Callable[[object, TypeExpr], bool],
    ) -> None:
        """Validate one analyzed function without retaining function-local state."""
        name = function.name
        line, col = function.line, function.col

        prior_array_params: set[str] = set()
        for parameter in function.params:
            self._validate_type(
                parameter.type,
                f"parameter '{parameter.name}'",
                name,
                line,
                col,
                allow_array=True,
            )
            canonical = self._canonical_type(parameter.type)
            if canonical is not None and canonical.is_array and parameter.default is not None:
                actual = self._node_types.get(id(parameter.default))
                inherited_capacity = (
                    isinstance(parameter.default, Identifier) and parameter.default.name in prior_array_params
                )
                if (
                    actual is not None
                    and not inherited_capacity
                    and not array_target_has_capacity(parameter.default, actual)
                ):
                    self._context.error(
                        f"Default for parameter '{parameter.name}' has no provable readable GPU buffer capacity",
                        getattr(parameter.default, "line", line),
                        getattr(parameter.default, "col", col),
                    )
            if canonical is not None and canonical.is_array:
                prior_array_params.add(parameter.name)

        return_type = function.return_type
        if return_type and not self._type_identity.is_scalar_void(return_type):
            if return_type.is_array:
                if return_type.base not in _GPU_ARRAY_ELEM_TYPES:
                    self._context.error(
                        f"@gpu function '{name}' return type must be void or a "
                        f"typed array (int[] or float[]), got '{return_type.base}[]'",
                        line,
                        col,
                    )
            else:
                self._context.error(
                    f"@gpu function '{name}' must return void or a typed array, got '{return_type.base}'",
                    line,
                    col,
                )

        validation = GpuKernelValidation(
            self._context,
            self._declarations.typedef_table,
            self._node_types,
            scope,
            function_name=name,
            scalar_params=frozenset(parameter.name for parameter in function.params if not parameter.type.is_array),
            array_params=frozenset(parameter.name for parameter in function.params if parameter.type.is_array),
        )
        if function.body:
            self._validate_block(validation, function.body)

    def call_uses_intrinsic(
        self,
        call: CallExpr,
        scope: Scope,
        *,
        in_gpu_function: bool,
    ) -> bool:
        """Resolve a WGSL-shaped call for ordinary expression analysis."""
        return self._intrinsics.call_uses_intrinsic(
            call,
            scope,
            in_gpu_function=in_gpu_function,
        )

    def _canonical_type(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        return canonical_declaration_type(
            type_expr,
            self._declarations.typedef_table,
        )

    def _validate_type(
        self,
        type_expr: TypeExpr | None,
        subject: str,
        function_name: str,
        line: int,
        col: int,
        *,
        allow_array: bool = False,
    ) -> None:
        if type_expr is None:
            return
        if type_expr.is_nullable:
            self._context.error(
                f"@gpu function '{function_name}': nullable types not allowed in {subject}",
                line,
                col,
            )
            return
        if type_expr.pointer_depth > 0:
            self._context.error(
                f"@gpu function '{function_name}': pointer types not allowed in {subject}",
                line,
                col,
            )
            return
        if type_expr.is_array and allow_array:
            if type_expr.is_const or type_expr.is_volatile:
                self._context.error(
                    f"@gpu function '{function_name}': GPU array buffers are read-write "
                    f"and cannot be const- or volatile-qualified in {subject}",
                    line,
                    col,
                )
                return
            if type_expr.base not in _GPU_ARRAY_ELEM_TYPES:
                self._context.error(
                    f"@gpu function '{function_name}': array element type must be "
                    f"int or float in {subject}, got '{type_expr.base}'",
                    line,
                    col,
                )
            return
        if type_expr.is_array:
            self._context.error(
                f"@gpu function '{function_name}': array types not allowed in {subject}",
                line,
                col,
            )
            return
        if type_expr.generic_args:
            self._context.error(
                f"@gpu function '{function_name}': generic types not allowed in {subject}",
                line,
                col,
            )
            return
        if type_expr.base not in _GPU_SCALAR_TYPES:
            self._context.error(
                f"@gpu function '{function_name}': type '{type_expr.base}' not allowed "
                f"in {subject} (use int, float, or bool)",
                line,
                col,
            )

    def _validate_block(
        self,
        validation: GpuKernelValidation,
        block: Block | None,
    ) -> None:
        if block is None:
            return
        validation.push_scope()
        try:
            for statement in block.statements:
                self._validate_statement(validation, statement)
        finally:
            validation.pop_scope()

    def _validate_statement(self, validation: GpuKernelValidation, statement) -> None:
        line = getattr(statement, "line", 0)
        col = getattr(statement, "col", 0)

        if isinstance(statement, VarDeclStmt):
            if statement.type:
                self._validate_type(
                    statement.type,
                    f"variable '{statement.name}'",
                    validation.function_name,
                    line,
                    col,
                )
            if statement.initializer:
                self._expressions.validate(validation, statement.initializer)
            validation.declare(statement.name)
            return
        if isinstance(statement, ReturnStmt):
            if statement.value:
                self._expressions.validate(validation, statement.value)
            return
        if isinstance(statement, IfStmt):
            self._expressions.validate(validation, statement.condition)
            self._validate_condition(validation, statement.condition)
            self._validate_block(validation, statement.then_block)
            if statement.else_block:
                else_block = statement.else_block
                if hasattr(else_block, "body"):
                    self._validate_block(validation, else_block.body)
                if hasattr(else_block, "if_stmt"):
                    self._validate_statement(validation, else_block.if_stmt)
            return
        if isinstance(statement, WhileStmt):
            self._expressions.validate(validation, statement.condition)
            self._validate_condition(validation, statement.condition)
            self._validate_block(validation, statement.body)
            return
        if isinstance(statement, CForStmt):
            validation.push_scope()
            try:
                if statement.init:
                    initializer = statement.init
                    if hasattr(initializer, "var_decl"):
                        self._validate_statement(validation, initializer.var_decl)
                    if hasattr(initializer, "expression"):
                        self._validate_update(validation, initializer.expression)
                if statement.condition:
                    self._expressions.validate(validation, statement.condition)
                    self._validate_condition(validation, statement.condition)
                if statement.update:
                    self._validate_update(validation, statement.update)
                self._validate_block(validation, statement.body)
            finally:
                validation.pop_scope()
            return
        if isinstance(statement, ExprStmt):
            if not self._expressions.is_expression_statement(statement.expr):
                validation.error(
                    "expression statement must be an assignment, increment, decrement, or WGSL built-in call",
                    statement.expr,
                )
            self._expressions.validate(
                validation,
                statement.expr,
                update=self._expressions.is_update_statement(statement.expr),
            )
            return
        if isinstance(statement, (BreakStmt, ContinueStmt)):
            return
        if isinstance(
            statement,
            (ForInStmt, TryCatchStmt, ThrowStmt, DeleteStmt, KeepStmt, ReleaseStmt),
        ):
            self._context.error(
                f"@gpu function '{validation.function_name}': "
                f"'{type(statement).__name__}' not allowed in GPU functions",
                line,
                col,
            )
            return
        self._context.error(
            f"@gpu function '{validation.function_name}': unsupported statement '{type(statement).__name__}'",
            line,
            col,
        )

    def _validate_update(
        self,
        validation: GpuKernelValidation,
        expression,
    ) -> None:
        update = self._expressions.is_update_statement(expression)
        if not update:
            validation.error(
                "for-loop initializer/update must update a variable or buffer element",
                expression,
            )
        self._expressions.validate(validation, expression, update=update)

    def _validate_condition(
        self,
        validation: GpuKernelValidation,
        expression,
    ) -> None:
        type_expr = validation.type_of(expression)
        if type_expr is not None and type_expr.base != "bool":
            validation.error(
                f"control-flow condition must be bool, got '{type_expr.base}'",
                expression,
            )


__all__ = ["GpuKernelValidator"]
