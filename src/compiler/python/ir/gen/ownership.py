"""Ownership classification for analyzed managed-value expressions."""

from __future__ import annotations

from ...ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BraceInitializer,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    FStringExpr,
    FStringLiteral,
    Identifier,
    IndexExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    NullLiteral,
    TernaryExpr,
    UnaryExpr,
)
from ...index_protocol import indexed_protocol_info
from .assignment_result_ownership import (
    assignment_pins_borrowed_target as _assignment_pins_borrowed_target,
)
from .assignment_result_ownership import virtual_assignment_rhs_owns_result
from .callable_provenance import known_language_call
from .types import is_generic_class_type, mangle_generic_type


def owns_result(gen, expression) -> bool:
    """Whether evaluating ``expression`` produces a caller-owned +1 value."""
    if isinstance(expression, NewExpr):
        result_type = gen.analyzed.node_types.get(id(expression))
        return _is_managed_type(gen, result_type)
    if isinstance(expression, (BraceInitializer, ListLiteral, MapLiteral)):
        result_type = gen.analyzed.node_types.get(id(expression))
        return bool(result_type and result_type.base in gen.analyzed.class_table)
    if isinstance(expression, CastExpr):
        result_type = gen.analyzed.node_types.get(id(expression))
        return _is_managed_type(gen, result_type) and owns_result(gen, expression.expr)
    if isinstance(expression, FStringLiteral):
        return any(isinstance(part, FStringExpr) for part in expression.parts)
    if isinstance(expression, AssignExpr):
        result_type = gen.analyzed.node_types.get(id(expression))
        target = expression.target
        rhs_owned = virtual_assignment_rhs_owns_result(
            gen,
            target,
            expression.value,
            type_of=lambda value: gen.analyzed.node_types.get(id(value)),
            owns=lambda value: owns_result(gen, value),
        )

        return bool(
            _is_managed_type(gen, result_type)
            and (
                (
                    isinstance(target, (FieldAccessExpr, IndexExpr))
                    and (owns_result(gen, target.obj) or _assignment_pins_borrowed_target(gen, target))
                )
                or (expression.op == "=" and rhs_owned)
            )
        )
    if isinstance(expression, (FieldAccessExpr, IndexExpr)):
        result_type = gen.analyzed.node_types.get(id(expression))
        custom_getter = False
        if isinstance(expression, FieldAccessExpr):
            from ...class_storage import custom_property_getter

            custom_getter = custom_property_getter(
                gen.analyzed.class_table,
                gen.analyzed.node_types.get(id(expression.obj)),
                expression.field,
            )
        return bool(
            _is_managed_type(gen, result_type)
            and (projection_is_owned_call(gen, expression) or custom_getter or owns_result(gen, expression.obj))
        )
    if isinstance(expression, TernaryExpr):
        return _conditional_result_is_owned(
            gen,
            expression,
            (expression.true_expr, expression.false_expr),
        )
    if isinstance(expression, BinaryExpr) and expression.op == "??":
        return _conditional_result_is_owned(
            gen,
            expression,
            (expression.left, expression.right),
        )
    if isinstance(expression, BinaryExpr):
        result_type = gen.analyzed.node_types.get(id(expression))
        if _is_string_concat(gen, expression, result_type):
            return True
        return _overloaded_result_is_owned(
            gen,
            expression,
            expression.left,
            expression.op,
        )
    if isinstance(expression, UnaryExpr):
        return _overloaded_result_is_owned(
            gen,
            expression,
            expression.operand,
            expression.op,
            unary=True,
        )
    if not isinstance(expression, CallExpr):
        return False
    result_type = gen.analyzed.node_types.get(id(expression))
    if not _is_managed_type(gen, result_type):
        return False
    if _is_string_type(gen, result_type):
        return _string_call_owns_result(gen, expression)
    # Constructors and every source-language function/method use the same
    # managed-return ABI: the callee yields one reference owned by its caller.
    # Unknown C/function-pointer calls remain borrowed because IR generation
    # cannot prove that they implement that ABI.
    return known_language_call(gen, expression)


def managed_type_name(gen, type_expr) -> str:
    """Return the concrete destructor prefix for a managed source type."""
    from .managed_values import MUTEX_RUNTIME_NAME, is_mutex_type

    if is_mutex_type(gen, type_expr):
        return MUTEX_RUNTIME_NAME
    if is_generic_class_type(type_expr, gen.analyzed.class_table):
        return mangle_generic_type(type_expr.base, type_expr.generic_args)
    return type_expr.base


def _owned_or_null(gen, expression) -> bool:
    return isinstance(expression, NullLiteral) or owns_result(gen, expression)


def normalize_owned_branch(gen, expression, lowered):
    """Promote a selected borrowed branch when its conditional yields +1."""
    if isinstance(expression, NullLiteral) or owns_result(gen, expression):
        return lowered
    type_expr = gen.analyzed.node_types.get(id(expression))
    if not _is_managed_type(gen, type_expr):
        return lowered

    from ..nodes import CType, IRBinOp, IRCommaExpr, IRStmtExpr, IRVar, IRVarDecl
    from .managed_values import retain_value
    from .types import type_to_c

    declaration = IRVarDecl(
        c_type=CType(text=type_to_c(type_expr)),
        name=gen.fresh_temp("__btrc_promoted_branch"),
    )
    gen._func_var_decls.append(declaration)
    value = IRVar(name=declaration.name)
    return IRStmtExpr(
        stmts=[declaration],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(left=value, op="=", right=lowered),
                retain_value(gen, value, type_expr),
                value,
            ]
        ),
    )


def _conditional_result_is_owned(gen, expression, branches) -> bool:
    result_type = gen.analyzed.node_types.get(id(expression))
    if not _is_managed_type(gen, result_type):
        return False
    if not any(owns_result(gen, branch) for branch in branches):
        return False
    return all(_promotable_branch(gen, branch) for branch in branches)


def _promotable_branch(gen, expression) -> bool:
    if _owned_or_null(gen, expression):
        return True
    type_expr = gen.analyzed.node_types.get(id(expression))
    return _is_managed_type(gen, type_expr)


def _is_managed_type(gen, type_expr) -> bool:
    from .managed_values import is_managed_type

    return is_managed_type(gen, type_expr)


def _is_string_type(gen, type_expr) -> bool:
    from .managed_values import is_string_type

    return is_string_type(gen, type_expr)


def _is_string_concat(gen, expression: BinaryExpr, result_type) -> bool:
    """Distinguish allocation-producing concatenation from char* arithmetic."""
    if expression.op != "+" or not _is_string_type(gen, result_type):
        return False
    node_types = gen.analyzed.node_types
    return _is_string_type(gen, node_types.get(id(expression.left))) and _is_string_type(
        gen, node_types.get(id(expression.right))
    )


def _string_call_owns_result(gen, expression: CallExpr) -> bool:
    """Classify only source/runtime calls with the managed-string +1 ABI."""
    if known_language_call(gen, expression):
        return True
    callee = expression.callee
    if isinstance(callee, Identifier):
        return callee.name in {
            "__btrc_str_track",
            "__btrc_string_adopt",
            "__btrc_string_alloc",
        }
    if not isinstance(callee, FieldAccessExpr):
        return False
    receiver_type = gen.analyzed.node_types.get(id(callee.obj))
    if _is_string_type(gen, receiver_type):
        from ...string_methods import STRING_METHODS

        method = STRING_METHODS.get(callee.field)
        return bool(method and method.tracked)
    if callee.field != "toString" or receiver_type is None:
        return False
    return bool(
        receiver_type.base != "bool"
        and receiver_type.base not in gen.analyzed.enum_table
        and receiver_type.base not in gen.analyzed.rich_enum_table
    )


def projection_is_owned_call(gen, expression) -> bool:
    """Whether a projection invokes a managed-return source callable."""
    receiver_type = gen.analyzed.node_types.get(id(expression.obj))
    if receiver_type is None:
        return False
    if isinstance(expression, IndexExpr):
        return indexed_protocol_info(receiver_type, gen.analyzed.class_table, method="get") is not None
    # Properties are field-like borrowed projections even though their C
    # representation uses a generated getter function.
    return False


def _overloaded_result_is_owned(
    gen,
    expression,
    operand,
    operator: str,
    *,
    unary: bool = False,
) -> bool:
    result_type = gen.analyzed.node_types.get(id(expression))
    expression_type = gen.analyzed.node_types.get(id(operand))
    if expression_type is None:
        return False
    class_info = gen.analyzed.class_table.get(expression_type.base)
    magic = {
        "+": "__add__",
        "-": "__sub__",
        "*": "__mul__",
        "/": "__div__",
        "%": "__mod__",
    }.get(operator)
    if unary:
        magic = "__neg__" if operator == "-" else None
    return bool(
        result_type is not None
        and result_type.base in gen.analyzed.class_table
        and class_info is not None
        and magic in class_info.methods
    )


__all__ = [
    "known_language_call",
    "managed_type_name",
    "normalize_owned_branch",
    "owns_result",
    "projection_is_owned_call",
]
