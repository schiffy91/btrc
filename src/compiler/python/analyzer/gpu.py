"""GPU kernel, intrinsic, dispatch, and WGSL semantic validation."""

from __future__ import annotations

from dataclasses import replace

from src.compiler.python.abi.hosted import HOSTED_ABI
from src.compiler.python.analyzer.aggregates import AggregateAnalyzer
from src.compiler.python.analyzer.program import AnalysisContext, AnalysisSession, DeclarationIndex, Scope
from src.compiler.python.analyzer.types import TypeSystem
from src.compiler.python.frontend.sources import CompilerStdlibSource
from src.compiler.python.lexer.lexer import LiteralDecoder
from src.compiler.python.syntax.ast.generated import (
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
    FunctionDecl,
    Identifier,
    IfStmt,
    IndexExpr,
    IntLiteral,
    KeepStmt,
    NullLiteral,
    ReleaseStmt,
    ReturnStmt,
    TernaryExpr,
    ThrowStmt,
    TryCatchStmt,
    TypeExpr,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)


class GpuKernelValidator:
    """Own the complete post-analysis contract for WGSL kernels."""

    def __init__(
        self,
        context: AnalysisContext,
        index: DeclarationIndex,
        node_types: dict[int, TypeExpr],
        types: TypeSystem,
        aggregates: AggregateAnalyzer,
    ) -> None:
        self._context = context
        self._index = index
        self._node_types = node_types
        self._types = types
        self._aggregates = aggregates
        self._intrinsics = GpuIntrinsicResolver(context, index)
        self._expressions = GpuExpressionValidator(self._intrinsics)

    def validate(self, function: FunctionDecl, scope: Scope) -> None:
        """Validate one analyzed function without retaining function-local state."""
        name = function.name
        line, col = (function.line, function.col)
        prior_array_params: set[str] = set()
        for parameter in function.params:
            self._validate_type(parameter.type, f"parameter '{parameter.name}'", name, line, col, allow_array=True)
            canonical = self.canonical_type(parameter.type)
            if canonical is not None and canonical.is_array and (parameter.default is not None):
                actual = self._node_types.get(id(parameter.default))
                inherited_capacity = (
                    isinstance(parameter.default, Identifier) and parameter.default.name in prior_array_params
                )
                if (
                    actual is not None
                    and (not inherited_capacity)
                    and (not self._aggregates.array_target_has_capacity(parameter.default, actual))
                ):
                    self._context.error(
                        f"Default for parameter '{parameter.name}' has no provable readable GPU buffer capacity",
                        getattr(parameter.default, "line", line),
                        getattr(parameter.default, "col", col),
                    )
            if canonical is not None and canonical.is_array:
                prior_array_params.add(parameter.name)
        return_type = function.return_type
        if return_type and (not self._types.is_void_value(return_type)):
            if return_type.is_array:
                if return_type.base not in _GPU_ARRAY_ELEM_TYPES:
                    self._context.error(
                        f"@gpu function '{name}' return type must be void or a typed array (int[] or float[]), got '{return_type.base}[]'",
                        line,
                        col,
                    )
            else:
                self._context.error(
                    f"@gpu function '{name}' must return void or a typed array, got '{return_type.base}'", line, col
                )
        validation = GpuKernelValidation(
            self._context,
            self._index.typedef_table,
            self._node_types,
            scope,
            function_name=name,
            scalar_params=frozenset(parameter.name for parameter in function.params if not parameter.type.is_array),
            array_params=frozenset(parameter.name for parameter in function.params if parameter.type.is_array),
        )
        if function.body:
            self._validate_block(validation, function.body)

    def call_uses_intrinsic(self, call: CallExpr, scope: Scope, *, in_gpu_function: bool) -> bool:
        """Resolve a WGSL-shaped call for ordinary expression analysis."""
        return self._intrinsics.call_uses_intrinsic(call, scope, in_gpu_function=in_gpu_function)

    def canonical_type(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        return TypeSystem.canonical_declaration_type(type_expr, self._index.typedef_table)

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
            self._context.error(f"@gpu function '{function_name}': nullable types not allowed in {subject}", line, col)
            return
        if type_expr.pointer_depth > 0:
            self._context.error(f"@gpu function '{function_name}': pointer types not allowed in {subject}", line, col)
            return
        if type_expr.is_array and allow_array:
            if type_expr.is_const or type_expr.is_volatile:
                self._context.error(
                    f"@gpu function '{function_name}': GPU array buffers are read-write and cannot be const- or volatile-qualified in {subject}",
                    line,
                    col,
                )
                return
            if type_expr.base not in _GPU_ARRAY_ELEM_TYPES:
                self._context.error(
                    f"@gpu function '{function_name}': array element type must be int or float in {subject}, got '{type_expr.base}'",
                    line,
                    col,
                )
            return
        if type_expr.is_array:
            self._context.error(f"@gpu function '{function_name}': array types not allowed in {subject}", line, col)
            return
        if type_expr.generic_args:
            self._context.error(f"@gpu function '{function_name}': generic types not allowed in {subject}", line, col)
            return
        if type_expr.base not in _GPU_SCALAR_TYPES:
            self._context.error(
                f"@gpu function '{function_name}': type '{type_expr.base}' not allowed in {subject} (use int, float, or bool)",
                line,
                col,
            )

    def _validate_block(self, validation: GpuKernelValidation, block: Block | None) -> None:
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
                self._validate_type(statement.type, f"variable '{statement.name}'", validation.function_name, line, col)
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
                validation, statement.expr, update=self._expressions.is_update_statement(statement.expr)
            )
            return
        if isinstance(statement, (BreakStmt, ContinueStmt)):
            return
        if isinstance(statement, (ForInStmt, TryCatchStmt, ThrowStmt, DeleteStmt, KeepStmt, ReleaseStmt)):
            self._context.error(
                f"@gpu function '{validation.function_name}': '{type(statement).__name__}' not allowed in GPU functions",
                line,
                col,
            )
            return
        self._context.error(
            f"@gpu function '{validation.function_name}': unsupported statement '{type(statement).__name__}'", line, col
        )

    def _validate_update(self, validation: GpuKernelValidation, expression) -> None:
        update = self._expressions.is_update_statement(expression)
        if not update:
            validation.error("for-loop initializer/update must update a variable or buffer element", expression)
        self._expressions.validate(validation, expression, update=update)

    def _validate_condition(self, validation: GpuKernelValidation, expression) -> None:
        type_expr = validation.type_of(expression)
        if type_expr is not None and type_expr.base != "bool":
            validation.error(f"control-flow condition must be bool, got '{type_expr.base}'", expression)


class GpuDispatchValidator:
    """Own host storage and materialization rules for GPU dispatches."""

    def __init__(
        self,
        context: AnalysisContext,
        index: DeclarationIndex,
        types: TypeSystem,
    ) -> None:
        self._context = context
        self._index = index
        self._types = types

    def is_array_result(self, expression: object, scope: Scope) -> bool:
        """Whether ``expression`` invokes an array-returning GPU kernel."""
        if not isinstance(expression, CallExpr) or not isinstance(expression.callee, Identifier):
            return False
        name = expression.callee.name
        symbol = scope.lookup(name)
        if symbol is not None and symbol.kind != "function":
            return False
        function = self._index.function_table.get(name)
        return bool(function and function.is_gpu and function.return_type.is_array)

    def is_output_assignment(self, expression: object, scope: Scope) -> bool:
        """Whether an assignment materializes a GPU result into host storage."""
        return bool(
            isinstance(expression, AssignExpr)
            and expression.op == "="
            and self.is_array_result(expression.value, scope)
        )

    def validate_result_context(self, expression: object, scope: Scope, boundary: object | None = None) -> None:
        """Reject an output dispatch unless this exact call owns the boundary."""
        if self.is_array_result(expression, scope) and expression is not boundary:
            self._context.error(
                GPU_ARRAY_RESULT_CONTEXT_DIAGNOSTIC, getattr(expression, "line", 0), getattr(expression, "col", 0)
            )

    def array_initializer_boundary(
        self, expression: object, declared_type: TypeExpr | None, scope: Scope
    ) -> object | None:
        """Return the GPU result call permitted by an array initializer."""
        declared = self._types.canonical_type(declared_type)
        array_storage = declared_type is None or bool(declared and declared.is_array)
        return expression if array_storage and self.is_array_result(expression, scope) else None

    def result_statement_boundary(self, expression: object, scope: Scope) -> object | None:
        """Return the direct output RHS permitted by an expression statement."""
        return expression.value if self.is_output_assignment(expression, scope) else None

    def input_has_compatible_storage(self, expected: TypeExpr, actual: TypeExpr) -> bool:
        """Whether an input buffer has the exact unqualified GPU ABI shape."""
        canonical = self._types.canonical_type(actual)
        element = self._buffer_element_type(actual)
        return bool(
            canonical is not None
            and element is not None
            and (not canonical.is_volatile)
            and (not element.is_volatile)
            and self._buffer_elements_exact(expected, actual)
        )

    def output_element_compatible(self, target: TypeExpr, source: TypeExpr) -> bool:
        """Whether a writable host target exactly matches a GPU result element."""
        canonical = self._types.canonical_type(target)
        element = self._buffer_element_type(target)
        return bool(
            canonical is not None
            and element is not None
            and (not canonical.is_const)
            and (not canonical.is_volatile)
            and (not element.is_const)
            and (not element.is_volatile)
            and self._buffer_elements_exact(target, source)
        )

    def _buffer_element_type(self, type_expr: TypeExpr) -> TypeExpr | None:
        canonical = self._types.canonical_type(type_expr)
        if canonical is None:
            return None
        if canonical.base in {"Array", "Vector"} and len(canonical.generic_args) == 1:
            element = self._types.canonical_type(canonical.generic_args[0])
        elif canonical.is_array:
            element = self._types.canonical_type(TypeSystem.strip_outer_storage(canonical, array=True))
        else:
            return None
        if element is None:
            return None
        return replace(element, is_static=False, is_extern=False)

    def _buffer_elements_exact(self, expected: TypeExpr, actual: TypeExpr) -> bool:
        expected_element = self._buffer_element_type(expected)
        actual_element = self._buffer_element_type(actual)
        return bool(
            expected_element is not None
            and actual_element is not None
            and (self._types.type_shape_key(expected_element) == self._types.type_shape_key(actual_element))
        )


class GpuKernelValidation:
    """Mutable lexical and type state for exactly one kernel validation."""

    def __init__(
        self,
        context: AnalysisContext,
        typedefs: dict[str, TypeExpr],
        node_types: dict[int, TypeExpr],
        scope: Scope,
        *,
        function_name: str,
        scalar_params: frozenset[str],
        array_params: frozenset[str],
    ) -> None:
        self._context = context
        self._typedefs = typedefs
        self._node_types = node_types
        self.scope = scope
        self.function_name = function_name
        self.scalar_params = scalar_params
        self.array_params = array_params
        self._scopes: list[set[str]] = []

    def push_scope(self) -> None:
        self._scopes.append(set())

    def pop_scope(self) -> None:
        self._scopes.pop()

    def declare(self, name: str) -> None:
        self._scopes[-1].add(name)

    def knows(self, name: str) -> bool:
        return (
            name in self.scalar_params
            or name in self.array_params
            or any(name in scope for scope in reversed(self._scopes))
        )

    def error(self, message: str, node) -> None:
        self._context.error(
            f"@gpu function '{self.function_name}': {message}", getattr(node, "line", 0), getattr(node, "col", 0)
        )

    def type_of(self, expression) -> TypeExpr | None:
        """Return the type recorded by ordinary body analysis."""
        return self._node_types.get(id(expression))

    def record_type(self, expression, base: str) -> None:
        canonical = TypeSystem.canonical_declaration_type(TypeExpr(base=base), self._typedefs)
        if canonical is not None:
            self._node_types[id(expression)] = canonical

    def format_type(self, type_expr: TypeExpr) -> str:
        result = type_expr.base
        if type_expr.generic_args:
            arguments = ", ".join(self.format_type(argument) for argument in type_expr.generic_args)
            result += f"<{arguments}>"
        result += "*" * type_expr.pointer_depth
        if type_expr.is_array:
            result += "[]"
        return result


class GpuExpressionValidator:
    """Own the recursive WGSL expression contract."""

    def __init__(self, intrinsics: GpuIntrinsicResolver) -> None:
        self._intrinsics = intrinsics

    def validate(self, validation: GpuKernelValidation, expression, *, update: bool = False) -> None:
        """Validate one expression, allowing an update at statement level."""
        if expression is None:
            return
        if isinstance(expression, IntLiteral):
            self._require_exact_type(validation, expression, {"int"}, "integer literal")
            if expression.value > 2147483647:
                validation.error("integer literal is outside the WGSL i32 range", expression)
            return
        if isinstance(expression, FloatLiteral):
            if LiteralDecoder.float32_problem(expression.raw, expression.value):
                validation.error("floating literal is outside the WGSL f32 range", expression)
            validation.record_type(expression, "float")
            return
        if isinstance(expression, BoolLiteral):
            return
        if isinstance(expression, NullLiteral):
            validation.error("null has no WGSL value representation", expression)
            return
        if isinstance(expression, Identifier):
            if not validation.knows(expression.name):
                validation.error(f"identifier '{expression.name}' is not a GPU parameter or local", expression)
            return
        if isinstance(expression, BinaryExpr):
            self._validate_binary(validation, expression)
            return
        if isinstance(expression, UnaryExpr):
            self._validate_unary(validation, expression, update=update)
            return
        if isinstance(expression, CallExpr):
            self._validate_call(validation, expression)
            return
        if isinstance(expression, IndexExpr):
            self.validate(validation, expression.obj)
            self.validate(validation, expression.index)
            self._require_exact_type(validation, expression.index, {"int"}, "array index")
            object_type = validation.type_of(expression.obj)
            if object_type is not None and (not object_type.is_array):
                validation.error("only GPU array parameters may be indexed", expression.obj)
            return
        if isinstance(expression, AssignExpr):
            if not update:
                validation.error("assignment is only supported as a standalone update statement", expression)
            self._validate_update_target(validation, expression.target)
            self.validate(validation, expression.value)
            if expression.op != "=":
                self._validate_compound_assignment(validation, expression)
            self._copy_type(validation, expression, expression.target)
            return
        if isinstance(expression, TernaryExpr):
            self._validate_ternary(validation, expression)
            return
        if isinstance(expression, CastExpr):
            self.validate(validation, expression.expr)
            self._validate_cast(validation, expression)
            validation.record_type(expression, expression.target_type.base)
            return
        if isinstance(expression, FieldAccessExpr):
            validation.error("field and method access has no WGSL lowering", expression)
            return
        validation.error(f"'{type(expression).__name__}' has no WGSL lowering", expression)

    def is_update_statement(self, expression) -> bool:
        return isinstance(expression, AssignExpr) or (
            isinstance(expression, UnaryExpr) and expression.op in ("++", "--")
        )

    def is_expression_statement(self, expression) -> bool:
        return self.is_update_statement(expression) or isinstance(expression, CallExpr)

    def _validate_binary(self, validation: GpuKernelValidation, expression: BinaryExpr) -> None:
        self.validate(validation, expression.left)
        self.validate(validation, expression.right)
        if expression.op not in _BINARY_OPERATORS:
            validation.error(f"operator '{expression.op}' has no WGSL lowering", expression)
        elif expression.op == "%":
            self._require_exact_type(validation, expression.left, {"int"}, "remainder operand")
            self._require_exact_type(validation, expression.right, {"int"}, "remainder operand")
        elif expression.op in ("<<", ">>"):
            self._require_exact_type(validation, expression.left, {"int"}, "shift operand")
            self._require_exact_type(validation, expression.right, {"int"}, "shift count")
        elif expression.op in ("&", "|", "^"):
            left_type = validation.type_of(expression.left)
            right_type = validation.type_of(expression.right)
            if (
                left_type is not None
                and right_type is not None
                and (left_type.base not in ("int", "bool") or right_type.base != left_type.base)
            ):
                validation.error("bitwise operands must have the same int or bool GPU type", expression)
            elif left_type is not None and left_type.base == "bool":
                validation.record_type(expression, "bool")
        self._set_binary_result_type(validation, expression)

    def _validate_unary(self, validation: GpuKernelValidation, expression: UnaryExpr, *, update: bool) -> None:
        if expression.op in ("++", "--"):
            if not update:
                validation.error(f"'{expression.op}' is only supported as a standalone update statement", expression)
            self._validate_update_target(validation, expression.operand)
            self._require_exact_type(validation, expression.operand, {"int", "float"}, "increment/decrement target")
            self._copy_type(validation, expression, expression.operand)
            return
        if (
            expression.op == "-"
            and isinstance(expression.operand, IntLiteral)
            and (expression.operand.value == 2147483648)
        ):
            validation.record_type(expression.operand, "int")
        else:
            self.validate(validation, expression.operand)
        if expression.op not in _VALUE_UNARY_OPERATORS:
            validation.error(f"unary operator '{expression.op}' has no WGSL lowering", expression)
        elif expression.op == "!":
            self._require_exact_type(validation, expression.operand, {"bool"}, "logical-not operand")
        elif expression.op == "~":
            self._require_exact_type(validation, expression.operand, {"int"}, "bitwise-not operand")
        else:
            self._require_exact_type(validation, expression.operand, {"int", "float"}, "unary numeric operand")
        if expression.op == "!":
            validation.record_type(expression, "bool")
        else:
            self._copy_type(validation, expression, expression.operand)

    def _validate_call(self, validation: GpuKernelValidation, call: CallExpr) -> None:
        for argument in call.args:
            self.validate(validation, argument)
        if any(call.arg_names):
            validation.error("WGSL built-ins do not accept named arguments", call)
        if not isinstance(call.callee, Identifier):
            validation.error("indirect and method calls have no WGSL definition", call.callee)
            return
        name = call.callee.name
        source_function = self._intrinsics.call_resolves_to_source_symbol(call, validation.scope, in_gpu_function=True)
        if validation.knows(name) or source_function:
            validation.error(f"call to '{name}' has no WGSL definition because it resolves to a source symbol", call)
            return
        if name == "gpu_id":
            if call.args:
                validation.error("gpu_id() takes no arguments", call)
            return
        if name not in WGSL_CALL_BUILTINS:
            validation.error(
                f"call to '{name}' has no WGSL definition; only gpu_id() and WGSL built-ins are allowed", call
            )
            return
        expected = WGSL_BUILTIN_ARITY[name]
        if len(call.args) != expected:
            validation.error(f"{name}() expects {expected} argument(s), got {len(call.args)}", call)
            return
        argument_types = [validation.type_of(argument) for argument in call.args]
        bases = [type_expr.base for type_expr in argument_types if type_expr is not None]
        if name in WGSL_FLOAT_UNARY_BUILTINS or name == "pow":
            if any(
                not self._is_gpu_scalar(type_expr, {"float"}) for type_expr in argument_types if type_expr is not None
            ):
                validation.error(f"{name}() requires float arguments in GPU functions", call)
            result_base = "float"
        elif name in WGSL_SAME_TYPE_BUILTINS:
            if any(
                not self._is_gpu_scalar(type_expr, {"int", "float"})
                for type_expr in argument_types
                if type_expr is not None
            ):
                validation.error(f"{name}() requires int or float arguments in GPU functions", call)
            if bases and any(base != bases[0] for base in bases[1:]):
                validation.error(f"{name}() arguments must have the same GPU scalar type", call)
            result_base = bases[0] if bases else "float"
        else:
            result_base = "float"
        validation.record_type(call, result_base)

    def _validate_ternary(self, validation: GpuKernelValidation, expression: TernaryExpr) -> None:
        self.validate(validation, expression.condition)
        condition_type = validation.type_of(expression.condition)
        if condition_type is not None and condition_type.base != "bool":
            validation.error(f"ternary condition must be bool, got '{condition_type.base}'", expression.condition)
        self.validate(validation, expression.true_expr)
        self.validate(validation, expression.false_expr)
        result_type = validation.type_of(expression)
        if result_type is not None and result_type.is_array:
            validation.error("ternary expressions cannot select whole GPU arrays", expression)
        self._set_ternary_result_type(validation, expression)

    def _validate_cast(self, validation: GpuKernelValidation, cast: CastExpr) -> None:
        target = cast.target_type
        if not self._is_gpu_scalar(target, {"int", "float", "bool"}):
            validation.error(f"cast target '{validation.format_type(target)}' has no WGSL scalar representation", cast)

    def _validate_compound_assignment(self, validation: GpuKernelValidation, expression: AssignExpr) -> None:
        if expression.op == "%=":
            self._require_exact_type(validation, expression.target, {"int"}, "remainder assignment target")
            self._require_exact_type(validation, expression.value, {"int"}, "remainder assignment operand")
        elif expression.op in _COMPOUND_ARITHMETIC:
            for operand in (expression.target, expression.value):
                self._require_exact_type(
                    validation, operand, {"int", "float"}, "arithmetic compound-assignment operand"
                )
        elif expression.op in _COMPOUND_BITWISE:
            for operand in (expression.target, expression.value):
                self._require_exact_type(validation, operand, {"int", "bool"}, "bitwise compound-assignment operand")
        elif expression.op in _COMPOUND_SHIFTS:
            self._require_exact_type(validation, expression.target, {"int"}, "shift assignment target")
            self._require_exact_type(validation, expression.value, {"int"}, "shift assignment count")
        else:
            validation.error(f"compound operator '{expression.op}' has no WGSL lowering", expression)
            return
        target_type = validation.type_of(expression.target)
        value_type = validation.type_of(expression.value)
        if target_type is not None and value_type is not None and (target_type.base != value_type.base):
            validation.error("compound assignment operands must have the same GPU scalar type", expression)

    def _validate_update_target(self, validation: GpuKernelValidation, target) -> None:
        if isinstance(target, Identifier):
            self.validate(validation, target)
            target_type = validation.type_of(target)
            if target.name in validation.scalar_params:
                validation.error(f"scalar parameter '{target.name}' is a read-only uniform", target)
            elif target_type is not None and target_type.is_array:
                validation.error("whole GPU arrays cannot be assigned or incremented", target)
            return
        if isinstance(target, IndexExpr):
            self.validate(validation, target)
            return
        validation.error("update target must be a local scalar or an indexed GPU buffer", target)

    def _require_exact_type(self, validation: GpuKernelValidation, expression, allowed: set[str], role: str) -> None:
        type_expr = validation.type_of(expression)
        if type_expr is not None and (not self._is_gpu_scalar(type_expr, allowed)):
            expected = " or ".join(sorted(allowed))
            validation.error(f"{role} must be {expected}, got '{type_expr.base}'", expression)

    def _copy_type(self, validation: GpuKernelValidation, result, operand) -> None:
        operand_type = validation.type_of(operand)
        if operand_type is not None:
            validation.record_type(result, operand_type.base)

    def _set_binary_result_type(self, validation: GpuKernelValidation, expression: BinaryExpr) -> None:
        if expression.op in {"==", "!=", "<", ">", "<=", ">=", "&&", "||"}:
            validation.record_type(expression, "bool")
            return
        left_type = validation.type_of(expression.left)
        right_type = validation.type_of(expression.right)
        if left_type is None or right_type is None:
            return
        if expression.op in {"&", "|", "^"} and left_type.base == right_type.base == "bool":
            validation.record_type(expression, "bool")
        elif "float" in {left_type.base, right_type.base}:
            validation.record_type(expression, "float")
        else:
            validation.record_type(expression, "int")

    def _set_ternary_result_type(self, validation: GpuKernelValidation, expression: TernaryExpr) -> None:
        true_type = validation.type_of(expression.true_expr)
        false_type = validation.type_of(expression.false_expr)
        if true_type is None or false_type is None:
            return
        if true_type.base == false_type.base:
            validation.record_type(expression, true_type.base)
        elif {true_type.base, false_type.base} == {"int", "float"}:
            validation.record_type(expression, "float")

    @staticmethod
    def _is_gpu_scalar(type_expr: TypeExpr, allowed: set[str]) -> bool:
        return bool(
            type_expr.base in allowed
            and (not type_expr.is_array)
            and (type_expr.pointer_depth == 0)
            and (not type_expr.generic_args)
            and (not type_expr.is_nullable)
        )


class GpuIntrinsicResolver:
    """Own source-symbol versus WGSL-intrinsic call resolution."""

    def __init__(self, context: AnalysisContext, index: DeclarationIndex) -> None:
        self._context = context
        self._index = index

    def call_uses_intrinsic(self, call: CallExpr, scope: Scope, *, in_gpu_function: bool) -> bool:
        """Whether a direct call resolves to the GPU intrinsic."""
        if not in_gpu_function or not isinstance(call.callee, Identifier):
            return False
        name = call.callee.name
        if name not in WGSL_CALL_BUILTINS:
            return False
        symbol = scope.lookup(name)
        if symbol is not None and symbol.kind != "function":
            return False
        declaration = self._index.function_table.get(name)
        return declaration is None or self._hosted_call_uses_owned_symbol(name, scope)

    def call_resolves_to_source_symbol(self, call: CallExpr, scope: Scope, *, in_gpu_function: bool) -> bool:
        """Whether a WGSL-shaped call is owned by a source declaration."""
        return bool(
            isinstance(call.callee, Identifier)
            and call.callee.name in self._index.function_table
            and (not self.call_uses_intrinsic(call, scope, in_gpu_function=in_gpu_function))
        )

    def _hosted_call_uses_owned_symbol(self, name: str, scope: Scope) -> bool:
        if not HOSTED_ABI.owned_name(name):
            return False
        symbol = scope.lookup(name)
        if symbol is not None and symbol.kind != "function":
            return False
        declaration = self._index.function_table.get(name)
        return bool(
            declaration is None or declaration.body is None or self._hosted_name_bypasses_source_definition(name)
        )

    def _hosted_name_bypasses_source_definition(self, name: str) -> bool:
        declaration = self._index.function_table.get(name)
        return bool(
            declaration is not None
            and declaration.body is not None
            and HOSTED_ABI.owned_name(name)
            and CompilerStdlibSource.authenticated(self._context.current_source_file)
            and (not CompilerStdlibSource.authenticated(getattr(declaration, "source_file", None)))
        )


_GPU_SCALAR_TYPES = frozenset({"int", "float", "bool"})
_GPU_ARRAY_ELEM_TYPES = frozenset({"int", "float"})
GPU_ARRAY_RESULT_CONTEXT_DIAGNOSTIC = (
    "Array-returning @gpu call is only valid as an array declaration initializer or direct array assignment statement"
)
_BINARY_OPERATORS = frozenset(
    {"+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=", "&&", "||", "&", "|", "^", "<<", ">>"}
)
_VALUE_UNARY_OPERATORS = frozenset({"!", "~", "+", "-"})
_COMPOUND_ARITHMETIC = frozenset({"+=", "-=", "*=", "/="})
_COMPOUND_BITWISE = frozenset({"&=", "|=", "^="})
_COMPOUND_SHIFTS = frozenset({"<<=", ">>="})
WGSL_FLOAT_UNARY_BUILTINS = frozenset({"ceil", "cos", "exp", "floor", "log", "round", "sin", "sqrt", "tan"})
WGSL_SAME_TYPE_BUILTINS = frozenset({"abs", "clamp", "max", "min"})
WGSL_BUILTIN_ARITY = {
    "abs": 1,
    "ceil": 1,
    "clamp": 3,
    "cos": 1,
    "exp": 1,
    "floor": 1,
    "log": 1,
    "max": 2,
    "min": 2,
    "pow": 2,
    "round": 1,
    "sin": 1,
    "sqrt": 1,
    "tan": 1,
}
WGSL_CALL_BUILTINS = frozenset(WGSL_BUILTIN_ARITY)
GPU_STATUS_BOUNDS = 1
GPU_STATUS_DIV_ZERO = 2
GPU_STATUS_MOD_ZERO = 3
GPU_STATUS_DIV_OVERFLOW = 4
GPU_UNKNOWN_STATUS_MESSAGE = "[btrc-gpu] GPU kernel reported an unknown failure status\n"
GPU_TRANSFER_FAILURE_MESSAGE = "[btrc-gpu] GPU dispatch or result transfer failed after submission\n"
GPU_STATUS_MESSAGES = {
    GPU_STATUS_BOUNDS: "GPU array index out of bounds\n",
    GPU_STATUS_DIV_ZERO: "Division by zero\n",
    GPU_STATUS_MOD_ZERO: "Modulo by zero\n",
    GPU_STATUS_DIV_OVERFLOW: "Integer division overflow\n",
}


class GpuAnalyzer:
    """GPU kernel, intrinsic, dispatch, and WGSL semantic validation."""

    def __init__(
        self,
        session: AnalysisSession,
        index: DeclarationIndex,
        types: TypeSystem,
        aggregates: AggregateAnalyzer,
    ) -> None:
        self.session = session
        self.index = index
        self.types = types
        self._dispatch = GpuDispatchValidator(
            session,
            index,
            types,
        )
        self._kernels = GpuKernelValidator(
            session,
            index,
            session.node_types,
            types,
            aggregates,
        )

    def is_array_result(self, expression: object) -> bool:
        return self._dispatch.is_array_result(expression, self.session.scope)

    def is_output_assignment(self, expression: object) -> bool:
        return self._dispatch.is_output_assignment(expression, self.session.scope)

    def array_initializer_boundary(self, expression: object, declared_type: TypeExpr | None) -> object | None:
        return self._dispatch.array_initializer_boundary(expression, declared_type, self.session.scope)

    def result_statement_boundary(self, expression: object) -> object | None:
        return self._dispatch.result_statement_boundary(expression, self.session.scope)

    def validate_result_context(self, expression: object) -> None:
        self._dispatch.validate_result_context(expression, self.session.scope, self.session.gpu_result_boundary)

    def input_has_compatible_storage(self, expected: TypeExpr, actual: TypeExpr) -> bool:
        return self._dispatch.input_has_compatible_storage(expected, actual)

    def output_element_compatible(self, target: TypeExpr, source: TypeExpr) -> bool:
        return self._dispatch.output_element_compatible(target, source)

    def call_uses_intrinsic(self, call: CallExpr) -> bool:
        return self._kernels.call_uses_intrinsic(call, self.session.scope, in_gpu_function=self.session.in_gpu_function)

    def validate_kernel(self, function: FunctionDecl) -> None:
        self._kernels.validate(function, self.session.scope)


__all__ = [
    "GpuAnalyzer",
    "GpuDispatchValidator",
    "GpuExpressionValidator",
    "GpuIntrinsicResolver",
    "GpuKernelValidation",
    "GpuKernelValidator",
]
