"""Nullable generic substitution must preserve value-level reference ABIs."""

import pytest

from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.ir.gen.type_resolution import canonical_type
from src.compiler.python.type_identity import (
    TypeShapeError,
    is_semantic_scalar_string,
    substitute_type_expr,
)

TYPEDEFS = {
    "ItemAlias": TypeExpr(base="Item", pointer_depth=1),
    "AliasChain": TypeExpr(base="ItemAlias"),
    "TextAlias": TypeExpr(base="string"),
    "RawPointer": TypeExpr(base="int", pointer_depth=1),
    "NullableInt": TypeExpr(base="int", pointer_depth=1, is_nullable=True),
    "IntArray": TypeExpr(base="int", is_array=True),
}


def _nullable_parameter() -> TypeExpr:
    return TypeExpr(base="T", pointer_depth=1, is_nullable=True)


def test_nullable_parameter_reuses_resolved_class_reference_layer() -> None:
    resolved = TypeExpr(base="Item", pointer_depth=1)

    result = substitute_type_expr(_nullable_parameter(), {"T": resolved})

    assert result == TypeExpr(
        base="Item",
        pointer_depth=1,
        is_nullable=True,
    )


def test_nullable_parameter_reuses_intrinsic_handle_layer() -> None:
    resolved = TypeExpr(base="Mutex", generic_args=[TypeExpr(base="int")])

    result = substitute_type_expr(_nullable_parameter(), {"T": resolved})

    assert result == TypeExpr(
        base="Mutex",
        generic_args=[TypeExpr(base="int")],
        is_nullable=True,
    )


def test_normalized_nullable_string_remains_a_scalar_string() -> None:
    result = substitute_type_expr(
        _nullable_parameter(),
        {"T": TypeExpr(base="string")},
    )

    assert result == TypeExpr(base="string", is_nullable=True)
    assert is_semantic_scalar_string(result)


def test_nullable_parameter_still_lifts_a_value_type() -> None:
    resolved = TypeExpr(base="int")

    result = substitute_type_expr(_nullable_parameter(), {"T": resolved})

    assert result == TypeExpr(
        base="int",
        pointer_depth=1,
        is_nullable=True,
    )


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("ItemAlias", TypeExpr(base="Item", pointer_depth=1, is_nullable=True)),
        ("AliasChain", TypeExpr(base="Item", pointer_depth=1, is_nullable=True)),
        ("TextAlias", TypeExpr(base="string", is_nullable=True)),
        ("RawPointer", TypeExpr(base="int", pointer_depth=1, is_nullable=True)),
        ("NullableInt", TypeExpr(base="int", pointer_depth=1, is_nullable=True)),
        ("IntArray", TypeExpr(base="int", is_array=True, is_nullable=True)),
    ],
)
def test_typedef_targets_are_transparent_to_nullable_shape_only(
    alias: str,
    canonical: TypeExpr,
) -> None:
    result = substitute_type_expr(
        _nullable_parameter(),
        {"T": TypeExpr(base=alias)},
        reference_resolver=lambda value: canonical_type(value, TYPEDEFS),
    )

    assert result == TypeExpr(base=alias, is_nullable=True)
    assert canonical_type(result, TYPEDEFS) == canonical


def test_explicit_pointer_and_array_modifiers_compose_once_through_aliases() -> None:
    explicit_pointer = TypeExpr(base="T", pointer_depth=2, is_nullable=True)
    array_of_nullable = TypeExpr(
        base="T",
        pointer_depth=1,
        is_nullable=True,
        is_array=True,
    )

    def resolver(value):
        return canonical_type(value, TYPEDEFS)

    pointer = substitute_type_expr(
        explicit_pointer,
        {"T": TypeExpr(base="AliasChain")},
        reference_resolver=resolver,
    )
    array = substitute_type_expr(
        array_of_nullable,
        {"T": TypeExpr(base="AliasChain")},
        reference_resolver=resolver,
    )

    assert pointer == TypeExpr(
        base="AliasChain",
        pointer_depth=1,
        is_nullable=True,
    )
    assert canonical_type(pointer, TYPEDEFS) == TypeExpr(
        base="Item",
        pointer_depth=2,
        is_nullable=True,
    )
    assert array == TypeExpr(
        base="AliasChain",
        is_nullable=True,
        is_array=True,
    )
    assert canonical_type(array, TYPEDEFS) == TypeExpr(
        base="Item",
        pointer_depth=1,
        is_nullable=True,
        is_array=True,
    )


def test_alias_to_array_still_rejects_nested_array_composition() -> None:
    with pytest.raises(TypeShapeError, match="nested array composition"):
        substitute_type_expr(
            TypeExpr(base="T", is_array=True),
            {"T": TypeExpr(base="IntArray")},
            reference_resolver=lambda value: canonical_type(value, TYPEDEFS),
        )
