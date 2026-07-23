"""Owned expression validation for the btrc subset representable in WGSL."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BoolLiteral,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    FloatLiteral,
    Identifier,
    IndexExpr,
    IntLiteral,
    NullLiteral,
    TernaryExpr,
    TypeExpr,
    UnaryExpr,
)
from ..gpu_builtins import (
    WGSL_BUILTIN_ARITY,
    WGSL_CALL_BUILTINS,
    WGSL_FLOAT_UNARY_BUILTINS,
    WGSL_SAME_TYPE_BUILTINS,
)
from ..numeric_literals import float32_literal_problem
from .declarations.type_resolution import canonical_declaration_type
from .gpu_type_contracts import GpuIntrinsicResolver

if TYPE_CHECKING:
    from .analysis_context import AnalysisContext
    from .core_models import Scope

_BINARY_OPERATORS = frozenset(
    {
        "+",
        "-",
        "*",
        "/",
        "%",
        "==",
        "!=",
        "<",
        ">",
        "<=",
        ">=",
        "&&",
        "||",
        "&",
        "|",
        "^",
        "<<",
        ">>",
    }
)
_VALUE_UNARY_OPERATORS = frozenset({"!", "~", "+", "-"})
_COMPOUND_ARITHMETIC = frozenset({"+=", "-=", "*=", "/="})
_COMPOUND_BITWISE = frozenset({"&=", "|=", "^="})
_COMPOUND_SHIFTS = frozenset({"<<=", ">>="})


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
            f"@gpu function '{self.function_name}': {message}",
            getattr(node, "line", 0),
            getattr(node, "col", 0),
        )

    def type_of(self, expression) -> TypeExpr | None:
        """Return the type recorded by ordinary body analysis."""
        return self._node_types.get(id(expression))

    def record_type(self, expression, base: str) -> None:
        canonical = canonical_declaration_type(
            TypeExpr(base=base),
            self._typedefs,
        )
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

    def validate(
        self,
        validation: GpuKernelValidation,
        expression,
        *,
        update: bool = False,
    ) -> None:
        """Validate one expression, allowing an update at statement level."""
        if expression is None:
            return
        if isinstance(expression, IntLiteral):
            self._require_exact_type(validation, expression, {"int"}, "integer literal")
            if expression.value > 2_147_483_647:
                validation.error("integer literal is outside the WGSL i32 range", expression)
            return
        if isinstance(expression, FloatLiteral):
            if float32_literal_problem(expression.raw, expression.value):
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
                validation.error(
                    f"identifier '{expression.name}' is not a GPU parameter or local",
                    expression,
                )
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
            if object_type is not None and not object_type.is_array:
                validation.error("only GPU array parameters may be indexed", expression.obj)
            return
        if isinstance(expression, AssignExpr):
            if not update:
                validation.error(
                    "assignment is only supported as a standalone update statement",
                    expression,
                )
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

    def _validate_binary(
        self,
        validation: GpuKernelValidation,
        expression: BinaryExpr,
    ) -> None:
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
                validation.error(
                    "bitwise operands must have the same int or bool GPU type",
                    expression,
                )
            elif left_type is not None and left_type.base == "bool":
                validation.record_type(expression, "bool")
        self._set_binary_result_type(validation, expression)

    def _validate_unary(
        self,
        validation: GpuKernelValidation,
        expression: UnaryExpr,
        *,
        update: bool,
    ) -> None:
        if expression.op in ("++", "--"):
            if not update:
                validation.error(
                    f"'{expression.op}' is only supported as a standalone update statement",
                    expression,
                )
            self._validate_update_target(validation, expression.operand)
            self._require_exact_type(
                validation,
                expression.operand,
                {"int", "float"},
                "increment/decrement target",
            )
            self._copy_type(validation, expression, expression.operand)
            return
        if (
            expression.op == "-"
            and isinstance(expression.operand, IntLiteral)
            and expression.operand.value == 2_147_483_648
        ):
            validation.record_type(expression.operand, "int")
        else:
            self.validate(validation, expression.operand)
        if expression.op not in _VALUE_UNARY_OPERATORS:
            validation.error(
                f"unary operator '{expression.op}' has no WGSL lowering",
                expression,
            )
        elif expression.op == "!":
            self._require_exact_type(validation, expression.operand, {"bool"}, "logical-not operand")
        elif expression.op == "~":
            self._require_exact_type(validation, expression.operand, {"int"}, "bitwise-not operand")
        else:
            self._require_exact_type(
                validation,
                expression.operand,
                {"int", "float"},
                "unary numeric operand",
            )
        if expression.op == "!":
            validation.record_type(expression, "bool")
        else:
            self._copy_type(validation, expression, expression.operand)

    def _validate_call(
        self,
        validation: GpuKernelValidation,
        call: CallExpr,
    ) -> None:
        for argument in call.args:
            self.validate(validation, argument)
        if any(call.arg_names):
            validation.error("WGSL built-ins do not accept named arguments", call)
        if not isinstance(call.callee, Identifier):
            validation.error(
                "indirect and method calls have no WGSL definition",
                call.callee,
            )
            return
        name = call.callee.name
        source_function = self._intrinsics.call_resolves_to_source_symbol(
            call,
            validation.scope,
            in_gpu_function=True,
        )
        if validation.knows(name) or source_function:
            validation.error(
                f"call to '{name}' has no WGSL definition because it resolves to a source symbol",
                call,
            )
            return
        if name == "gpu_id":
            if call.args:
                validation.error("gpu_id() takes no arguments", call)
            return
        if name not in WGSL_CALL_BUILTINS:
            validation.error(
                f"call to '{name}' has no WGSL definition; only gpu_id() and WGSL built-ins are allowed",
                call,
            )
            return
        expected = WGSL_BUILTIN_ARITY[name]
        if len(call.args) != expected:
            validation.error(
                f"{name}() expects {expected} argument(s), got {len(call.args)}",
                call,
            )
            return
        argument_types = [validation.type_of(argument) for argument in call.args]
        bases = [type_expr.base for type_expr in argument_types if type_expr is not None]
        if name in WGSL_FLOAT_UNARY_BUILTINS or name == "pow":
            if any(
                not self._is_gpu_scalar(type_expr, {"float"}) for type_expr in argument_types if type_expr is not None
            ):
                validation.error(
                    f"{name}() requires float arguments in GPU functions",
                    call,
                )
            result_base = "float"
        elif name in WGSL_SAME_TYPE_BUILTINS:
            if any(
                not self._is_gpu_scalar(type_expr, {"int", "float"})
                for type_expr in argument_types
                if type_expr is not None
            ):
                validation.error(
                    f"{name}() requires int or float arguments in GPU functions",
                    call,
                )
            if bases and any(base != bases[0] for base in bases[1:]):
                validation.error(
                    f"{name}() arguments must have the same GPU scalar type",
                    call,
                )
            result_base = bases[0] if bases else "float"
        else:
            result_base = "float"
        validation.record_type(call, result_base)

    def _validate_ternary(
        self,
        validation: GpuKernelValidation,
        expression: TernaryExpr,
    ) -> None:
        self.validate(validation, expression.condition)
        condition_type = validation.type_of(expression.condition)
        if condition_type is not None and condition_type.base != "bool":
            validation.error(
                f"ternary condition must be bool, got '{condition_type.base}'",
                expression.condition,
            )
        self.validate(validation, expression.true_expr)
        self.validate(validation, expression.false_expr)
        result_type = validation.type_of(expression)
        if result_type is not None and result_type.is_array:
            validation.error("ternary expressions cannot select whole GPU arrays", expression)
        self._set_ternary_result_type(validation, expression)

    def _validate_cast(
        self,
        validation: GpuKernelValidation,
        cast: CastExpr,
    ) -> None:
        target = cast.target_type
        if not self._is_gpu_scalar(target, {"int", "float", "bool"}):
            validation.error(
                f"cast target '{validation.format_type(target)}' has no WGSL scalar representation",
                cast,
            )

    def _validate_compound_assignment(
        self,
        validation: GpuKernelValidation,
        expression: AssignExpr,
    ) -> None:
        if expression.op == "%=":
            self._require_exact_type(validation, expression.target, {"int"}, "remainder assignment target")
            self._require_exact_type(validation, expression.value, {"int"}, "remainder assignment operand")
        elif expression.op in _COMPOUND_ARITHMETIC:
            for operand in (expression.target, expression.value):
                self._require_exact_type(
                    validation,
                    operand,
                    {"int", "float"},
                    "arithmetic compound-assignment operand",
                )
        elif expression.op in _COMPOUND_BITWISE:
            for operand in (expression.target, expression.value):
                self._require_exact_type(
                    validation,
                    operand,
                    {"int", "bool"},
                    "bitwise compound-assignment operand",
                )
        elif expression.op in _COMPOUND_SHIFTS:
            self._require_exact_type(validation, expression.target, {"int"}, "shift assignment target")
            self._require_exact_type(validation, expression.value, {"int"}, "shift assignment count")
        else:
            validation.error(
                f"compound operator '{expression.op}' has no WGSL lowering",
                expression,
            )
            return

        target_type = validation.type_of(expression.target)
        value_type = validation.type_of(expression.value)
        if target_type is not None and value_type is not None and target_type.base != value_type.base:
            validation.error(
                "compound assignment operands must have the same GPU scalar type",
                expression,
            )

    def _validate_update_target(
        self,
        validation: GpuKernelValidation,
        target,
    ) -> None:
        if isinstance(target, Identifier):
            self.validate(validation, target)
            target_type = validation.type_of(target)
            if target.name in validation.scalar_params:
                validation.error(
                    f"scalar parameter '{target.name}' is a read-only uniform",
                    target,
                )
            elif target_type is not None and target_type.is_array:
                validation.error("whole GPU arrays cannot be assigned or incremented", target)
            return
        if isinstance(target, IndexExpr):
            self.validate(validation, target)
            return
        validation.error(
            "update target must be a local scalar or an indexed GPU buffer",
            target,
        )

    def _require_exact_type(
        self,
        validation: GpuKernelValidation,
        expression,
        allowed: set[str],
        role: str,
    ) -> None:
        type_expr = validation.type_of(expression)
        if type_expr is not None and not self._is_gpu_scalar(type_expr, allowed):
            expected = " or ".join(sorted(allowed))
            validation.error(
                f"{role} must be {expected}, got '{type_expr.base}'",
                expression,
            )

    def _copy_type(
        self,
        validation: GpuKernelValidation,
        result,
        operand,
    ) -> None:
        operand_type = validation.type_of(operand)
        if operand_type is not None:
            validation.record_type(result, operand_type.base)

    def _set_binary_result_type(
        self,
        validation: GpuKernelValidation,
        expression: BinaryExpr,
    ) -> None:
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

    def _set_ternary_result_type(
        self,
        validation: GpuKernelValidation,
        expression: TernaryExpr,
    ) -> None:
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
            and not type_expr.is_array
            and type_expr.pointer_depth == 0
            and not type_expr.generic_args
            and not type_expr.is_nullable
        )


__all__ = ["GpuExpressionValidator", "GpuKernelValidation"]
