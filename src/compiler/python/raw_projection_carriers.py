"""Pure AST shape analysis for raw views of projected storage."""

from __future__ import annotations

from dataclasses import dataclass

from .ast_nodes import (
    BinaryExpr,
    CastExpr,
    FieldAccessExpr,
    IndexExpr,
    TernaryExpr,
    UnaryExpr,
)


@dataclass(frozen=True)
class RawProjectionLeaf:
    """A field/index projection that produces, or is addressed as, a raw view."""

    expression: object
    direct_storage: bool = False


@dataclass(frozen=True)
class RawProjectionBranch:
    """One lazily selected arm of a conditional carrier."""

    label: str
    expression: object
    carrier: RawProjectionCarrier | None


@dataclass(frozen=True)
class RawProjectionChoice:
    """A carrier whose backing storage depends on a runtime branch."""

    expression: object
    branches: tuple[RawProjectionBranch, ...]


RawProjectionCarrier = RawProjectionLeaf | RawProjectionChoice


def is_raw_projection_carrier_type(
    type_expr,
    *,
    is_managed,
) -> bool:
    """Match every strict-C pointer/array/address-integer carrier."""
    return bool(
        type_expr
        and not is_managed(type_expr)
        and (type_expr.is_array or type_expr.pointer_depth > 0 or type_expr.base in {"intptr_t", "uintptr_t"})
    )


def raw_projection_carrier(
    expression,
    *,
    type_of,
    is_raw_carrier,
    is_direct_storage=lambda _expression: False,
    return_alias_argument=lambda _expression: None,
):
    """Return the branch-preserving raw-projection shape for ``expression``."""
    return _raw_projection_carrier(
        expression,
        addressed=False,
        type_of=type_of,
        is_raw_carrier=is_raw_carrier,
        is_direct_storage=is_direct_storage,
        return_alias_argument=return_alias_argument,
    )


def _raw_projection_carrier(
    expression,
    *,
    addressed,
    type_of,
    is_raw_carrier,
    is_direct_storage,
    return_alias_argument,
):
    alias_argument = return_alias_argument(expression)
    if alias_argument is not None:
        nested = _raw_projection_carrier(
            alias_argument,
            addressed=False,
            type_of=type_of,
            is_raw_carrier=is_raw_carrier,
            is_direct_storage=is_direct_storage,
            return_alias_argument=return_alias_argument,
        )
        if nested is not None:
            return nested
        if is_direct_storage(alias_argument):
            return RawProjectionLeaf(
                expression=alias_argument,
                direct_storage=True,
            )
        return None
    if isinstance(expression, CastExpr):
        if not is_raw_carrier(type_of(expression)):
            return None
        nested = _raw_projection_carrier(
            expression.expr,
            addressed=False,
            type_of=type_of,
            is_raw_carrier=is_raw_carrier,
            is_direct_storage=is_direct_storage,
            return_alias_argument=return_alias_argument,
        )
        if nested is not None:
            return nested
        if is_direct_storage(expression.expr):
            return RawProjectionLeaf(
                expression=expression.expr,
                direct_storage=True,
            )
        return None
    if isinstance(expression, UnaryExpr) and expression.op == "&":
        return _raw_projection_carrier(
            expression.operand,
            addressed=True,
            type_of=type_of,
            is_raw_carrier=is_raw_carrier,
            is_direct_storage=is_direct_storage,
            return_alias_argument=return_alias_argument,
        )
    if (
        isinstance(expression, UnaryExpr)
        and expression.op == "*"
        and (addressed or is_raw_carrier(type_of(expression)))
    ):
        return _raw_projection_carrier(
            expression.operand,
            addressed=False,
            type_of=type_of,
            is_raw_carrier=is_raw_carrier,
            is_direct_storage=is_direct_storage,
            return_alias_argument=return_alias_argument,
        )
    if isinstance(expression, TernaryExpr):
        if not addressed and not is_raw_carrier(type_of(expression)):
            return None
        return RawProjectionChoice(
            expression=expression,
            branches=(
                _branch(
                    "true",
                    expression.true_expr,
                    addressed,
                    type_of,
                    is_raw_carrier,
                    is_direct_storage,
                    return_alias_argument,
                ),
                _branch(
                    "false",
                    expression.false_expr,
                    addressed,
                    type_of,
                    is_raw_carrier,
                    is_direct_storage,
                    return_alias_argument,
                ),
            ),
        )
    if isinstance(expression, BinaryExpr) and expression.op == "??":
        if not addressed and not is_raw_carrier(type_of(expression)):
            return None
        return RawProjectionChoice(
            expression=expression,
            branches=(
                _branch(
                    "present",
                    expression.left,
                    addressed,
                    type_of,
                    is_raw_carrier,
                    is_direct_storage,
                    return_alias_argument,
                ),
                _branch(
                    "fallback",
                    expression.right,
                    addressed,
                    type_of,
                    is_raw_carrier,
                    is_direct_storage,
                    return_alias_argument,
                ),
            ),
        )
    if isinstance(expression, BinaryExpr) and expression.op in {"+", "-"}:
        if not is_raw_carrier(type_of(expression)):
            return None
        candidates = (expression.left, expression.right) if expression.op == "+" else (expression.left,)
        for candidate in candidates:
            if is_raw_carrier(type_of(candidate)):
                carrier = _raw_projection_carrier(
                    candidate,
                    addressed=False,
                    type_of=type_of,
                    is_raw_carrier=is_raw_carrier,
                    is_direct_storage=is_direct_storage,
                    return_alias_argument=return_alias_argument,
                )
                if carrier is not None:
                    return carrier
        return None
    if isinstance(expression, (FieldAccessExpr, IndexExpr)) and (addressed or is_raw_carrier(type_of(expression))):
        nested = _raw_projection_carrier(
            expression.obj,
            addressed=False,
            type_of=type_of,
            is_raw_carrier=is_raw_carrier,
            is_direct_storage=is_direct_storage,
            return_alias_argument=return_alias_argument,
        )
        if nested is not None:
            return nested
        return RawProjectionLeaf(expression=expression)
    return None


def _branch(
    label,
    expression,
    addressed,
    type_of,
    is_raw_carrier,
    is_direct_storage,
    return_alias_argument,
):
    return RawProjectionBranch(
        label=label,
        expression=expression,
        carrier=_raw_projection_carrier(
            expression,
            addressed=addressed,
            type_of=type_of,
            is_raw_carrier=is_raw_carrier,
            is_direct_storage=is_direct_storage,
            return_alias_argument=return_alias_argument,
        ),
    )


def unconditional_projection_leaves(carrier):
    """Return leaves only when no runtime branch selects the backing store."""
    if carrier is None:
        return ()
    if isinstance(carrier, RawProjectionLeaf):
        return (carrier,)
    return ()


def first_branch_local_storage_choice(carrier, *, storage_for):
    """Find a choice that would require evaluating branch storage eagerly."""
    if not isinstance(carrier, RawProjectionChoice):
        return None
    for branch in carrier.branches:
        if _carrier_has_storage(branch.carrier, storage_for=storage_for):
            return carrier.expression
    return None


def _carrier_has_storage(carrier, *, storage_for):
    if isinstance(carrier, RawProjectionLeaf):
        return storage_for(carrier) is not None
    if isinstance(carrier, RawProjectionChoice):
        return any(_carrier_has_storage(branch.carrier, storage_for=storage_for) for branch in carrier.branches)
    return False


__all__ = [
    "RawProjectionBranch",
    "RawProjectionCarrier",
    "RawProjectionChoice",
    "RawProjectionLeaf",
    "first_branch_local_storage_choice",
    "is_raw_projection_carrier_type",
    "raw_projection_carrier",
    "unconditional_projection_leaves",
]
