"""Expression-level contracts for the btrc subset representable in WGSL."""

from __future__ import annotations

from dataclasses import dataclass, field

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
from ..numeric_literals import float32_literal_problem
from .gpu_result_types import (
    copy_gpu_type,
    set_binary_result_type,
    set_gpu_type,
    set_ternary_result_type,
)
from .gpu_type_contracts import (
    require_exact_gpu_type,
    validate_gpu_call,
    validate_gpu_cast,
)

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


@dataclass
class GpuValidationContext:
    analyzer: object
    function_name: str
    scalar_params: frozenset[str]
    array_params: frozenset[str]
    scopes: list[set[str]] = field(default_factory=list)

    def push_scope(self) -> None:
        self.scopes.append(set())

    def pop_scope(self) -> None:
        self.scopes.pop()

    def declare(self, name: str) -> None:
        self.scopes[-1].add(name)

    def knows(self, name: str) -> bool:
        return (
            name in self.scalar_params
            or name in self.array_params
            or any(name in scope for scope in reversed(self.scopes))
        )

    def error(self, message: str, node) -> None:
        self.analyzer._error(
            f"@gpu function '{self.function_name}': {message}",
            getattr(node, "line", 0),
            getattr(node, "col", 0),
        )

    def type_of(self, expression):
        return self.analyzer.node_types.get(id(expression)) or self.analyzer._infer_type(expression)


def validate_gpu_expr(context: GpuValidationContext, expression, *, update: bool = False) -> None:
    """Validate one expression, allowing an update only at statement level."""

    if expression is None:
        return
    if isinstance(expression, IntLiteral):
        require_exact_gpu_type(context, expression, {"int"}, "integer literal")
        if expression.value > 2_147_483_647:
            context.error("integer literal is outside the WGSL i32 range", expression)
        return
    if isinstance(expression, FloatLiteral):
        if float32_literal_problem(expression.raw, expression.value):
            context.error("floating literal is outside the WGSL f32 range", expression)
        set_gpu_type(context, expression, "float")
        return
    if isinstance(expression, BoolLiteral):
        return
    if isinstance(expression, NullLiteral):
        context.error("null has no WGSL value representation", expression)
        return
    if isinstance(expression, Identifier):
        if not context.knows(expression.name):
            context.error(
                f"identifier '{expression.name}' is not a GPU parameter or local",
                expression,
            )
        return
    if isinstance(expression, BinaryExpr):
        validate_gpu_expr(context, expression.left)
        validate_gpu_expr(context, expression.right)
        if expression.op not in _BINARY_OPERATORS:
            context.error(f"operator '{expression.op}' has no WGSL lowering", expression)
        elif expression.op == "%":
            require_exact_gpu_type(context, expression.left, {"int"}, "remainder operand")
            require_exact_gpu_type(context, expression.right, {"int"}, "remainder operand")
        elif expression.op in ("<<", ">>"):
            require_exact_gpu_type(context, expression.left, {"int"}, "shift operand")
            require_exact_gpu_type(context, expression.right, {"int"}, "shift count")
        elif expression.op in ("&", "|", "^"):
            left_type = context.type_of(expression.left)
            right_type = context.type_of(expression.right)
            if (
                left_type is not None
                and right_type is not None
                and (left_type.base not in ("int", "bool") or right_type.base != left_type.base)
            ):
                context.error("bitwise operands must have the same int or bool GPU type", expression)
            elif left_type is not None and left_type.base == "bool":
                context.analyzer.node_types[id(expression)] = TypeExpr(base="bool")
        set_binary_result_type(context, expression)
        return
    if isinstance(expression, UnaryExpr):
        if expression.op in ("++", "--"):
            if not update:
                context.error(
                    f"'{expression.op}' is only supported as a standalone update statement",
                    expression,
                )
            _validate_update_target(context, expression.operand)
            require_exact_gpu_type(
                context,
                expression.operand,
                {"int", "float"},
                "increment/decrement target",
            )
            copy_gpu_type(context, expression, expression.operand)
            return
        if (
            expression.op == "-"
            and isinstance(expression.operand, IntLiteral)
            and expression.operand.value == 2_147_483_648
        ):
            set_gpu_type(context, expression.operand, "int")
        else:
            validate_gpu_expr(context, expression.operand)
        if expression.op not in _VALUE_UNARY_OPERATORS:
            context.error(f"unary operator '{expression.op}' has no WGSL lowering", expression)
        elif expression.op == "!":
            require_exact_gpu_type(context, expression.operand, {"bool"}, "logical-not operand")
        elif expression.op == "~":
            require_exact_gpu_type(context, expression.operand, {"int"}, "bitwise-not operand")
        else:
            require_exact_gpu_type(context, expression.operand, {"int", "float"}, "unary numeric operand")
        if expression.op == "!":
            set_gpu_type(context, expression, "bool")
        else:
            copy_gpu_type(context, expression, expression.operand)
        return
    if isinstance(expression, CallExpr):
        validate_gpu_call(context, expression)
        return
    if isinstance(expression, IndexExpr):
        validate_gpu_expr(context, expression.obj)
        validate_gpu_expr(context, expression.index)
        require_exact_gpu_type(context, expression.index, {"int"}, "array index")
        object_type = context.type_of(expression.obj)
        if object_type is not None and not object_type.is_array:
            context.error("only GPU array parameters may be indexed", expression.obj)
        return
    if isinstance(expression, AssignExpr):
        if not update:
            context.error("assignment is only supported as a standalone update statement", expression)
        _validate_update_target(context, expression.target)
        validate_gpu_expr(context, expression.value)
        if expression.op != "=":
            _validate_compound_assignment(context, expression)
        copy_gpu_type(context, expression, expression.target)
        return
    if isinstance(expression, TernaryExpr):
        validate_gpu_expr(context, expression.condition)
        condition_type = context.type_of(expression.condition)
        if condition_type is not None and condition_type.base != "bool":
            context.error(
                f"ternary condition must be bool, got '{condition_type.base}'",
                expression.condition,
            )
        validate_gpu_expr(context, expression.true_expr)
        validate_gpu_expr(context, expression.false_expr)
        result_type = context.type_of(expression)
        if result_type is not None and result_type.is_array:
            context.error("ternary expressions cannot select whole GPU arrays", expression)
        set_ternary_result_type(context, expression)
        return
    if isinstance(expression, CastExpr):
        validate_gpu_expr(context, expression.expr)
        validate_gpu_cast(context, expression)
        set_gpu_type(context, expression, expression.target_type.base)
        return
    if isinstance(expression, FieldAccessExpr):
        context.error("field and method access has no WGSL lowering", expression)
        return
    context.error(f"'{type(expression).__name__}' has no WGSL lowering", expression)


def _validate_compound_assignment(context: GpuValidationContext, expression: AssignExpr) -> None:
    if expression.op == "%=":
        require_exact_gpu_type(context, expression.target, {"int"}, "remainder assignment target")
        require_exact_gpu_type(context, expression.value, {"int"}, "remainder assignment operand")
    elif expression.op in _COMPOUND_ARITHMETIC:
        for operand in (expression.target, expression.value):
            require_exact_gpu_type(
                context,
                operand,
                {"int", "float"},
                "arithmetic compound-assignment operand",
            )
    elif expression.op in _COMPOUND_BITWISE:
        for operand in (expression.target, expression.value):
            require_exact_gpu_type(
                context,
                operand,
                {"int", "bool"},
                "bitwise compound-assignment operand",
            )
    elif expression.op in _COMPOUND_SHIFTS:
        require_exact_gpu_type(context, expression.target, {"int"}, "shift assignment target")
        require_exact_gpu_type(context, expression.value, {"int"}, "shift assignment count")
    else:
        context.error(
            f"compound operator '{expression.op}' has no WGSL lowering",
            expression,
        )
        return

    target_type = context.type_of(expression.target)
    value_type = context.type_of(expression.value)
    if target_type is not None and value_type is not None and target_type.base != value_type.base:
        context.error(
            "compound assignment operands must have the same GPU scalar type",
            expression,
        )


def is_gpu_update_statement(expression) -> bool:
    return isinstance(expression, AssignExpr) or (isinstance(expression, UnaryExpr) and expression.op in ("++", "--"))


def is_gpu_expression_statement(expression) -> bool:
    return is_gpu_update_statement(expression) or isinstance(expression, CallExpr)


def _validate_update_target(context: GpuValidationContext, target) -> None:
    if isinstance(target, Identifier):
        validate_gpu_expr(context, target)
        target_type = context.type_of(target)
        if target.name in context.scalar_params:
            context.error(f"scalar parameter '{target.name}' is a read-only uniform", target)
        elif target_type is not None and target_type.is_array:
            context.error("whole GPU arrays cannot be assigned or incremented", target)
        return
    if isinstance(target, IndexExpr):
        validate_gpu_expr(context, target)
        return
    context.error("update target must be a local scalar or an indexed GPU buffer", target)
