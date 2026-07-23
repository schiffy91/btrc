"""Nullable generic substitution must preserve value-level reference ABIs."""

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.ir.gen.generics.core import _resolve_type_c
from src.compiler.python.ir.gen.type_resolution import canonical_type
from src.compiler.python.ir.gen.types import CTypeRenderer
from src.compiler.python.type_composition import add_outer_pointer, strip_outer_storage
from src.compiler.python.type_identity import (
    TypeShapeError,
    generic_instance_key,
    is_semantic_scalar_string,
    mangle_generic_symbol,
    substitute_type_expr,
)

TYPEDEFS = {
    "ItemAlias": TypeExpr(base="Item", pointer_depth=1),
    "AliasChain": TypeExpr(base="ItemAlias"),
    "TextAlias": TypeExpr(base="string"),
    "RawPointer": TypeExpr(base="int", pointer_depth=1),
    "NullableInt": TypeExpr(base="int", pointer_depth=1, is_nullable=True),
    "IntArray": TypeExpr(base="int", is_array=True),
    "Callback": TypeExpr(base="__fn_ptr", generic_args=[TypeExpr(base="void")]),
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
        nullable_outer_depth=1,
    )
    assert canonical_type(pointer, TYPEDEFS) == TypeExpr(
        base="Item",
        pointer_depth=2,
        is_nullable=True,
        nullable_outer_depth=1,
    )
    assert array == TypeExpr(
        base="AliasChain",
        is_nullable=True,
        is_array=True,
        nullable_outer_depth=1,
    )
    assert canonical_type(array, TYPEDEFS) == TypeExpr(
        base="Item",
        pointer_depth=1,
        is_nullable=True,
        is_array=True,
        nullable_outer_depth=1,
    )


def test_alias_to_array_still_rejects_nested_array_composition() -> None:
    with pytest.raises(TypeShapeError, match="nested array composition"):
        substitute_type_expr(
            TypeExpr(base="T", is_array=True),
            {"T": TypeExpr(base="IntArray")},
            reference_resolver=lambda value: canonical_type(value, TYPEDEFS),
        )


@pytest.mark.parametrize(
    ("template", "concrete", "expected"),
    [
        (TypeExpr(base="T"), TypeExpr(base="int", pointer_depth=1, is_nullable=True), "int*"),
        (TypeExpr(base="T", pointer_depth=1), TypeExpr(base="int", pointer_depth=1, is_nullable=True), "int**"),
        (
            TypeExpr(base="T", pointer_depth=1, is_nullable=True),
            TypeExpr(base="int", pointer_depth=1, is_nullable=True),
            "int*",
        ),
        (TypeExpr(base="T", pointer_depth=1), TypeExpr(base="string", pointer_depth=1, is_nullable=True), "char**"),
        (
            TypeExpr(base="T", pointer_depth=1, is_nullable=True),
            TypeExpr(base="string"),
            "char*",
        ),
        (
            TypeExpr(base="T", pointer_depth=1, is_nullable=True),
            TypeExpr(base="Item", pointer_depth=1),
            "Item*",
        ),
        (TypeExpr(base="T", pointer_depth=1), TypeExpr(base="Item", pointer_depth=1), "Item**"),
        (
            TypeExpr(base="T", is_array=True),
            TypeExpr(base="int", pointer_depth=1, is_nullable=True),
            "int**",
        ),
        (
            TypeExpr(base="T"),
            TypeExpr(base="int", pointer_depth=2, is_nullable=True),
            "int*",
        ),
        (
            TypeExpr(base="T", pointer_depth=1),
            TypeExpr(base="int", pointer_depth=2, is_nullable=True),
            "int**",
        ),
    ],
)
def test_generic_c_rendering_preserves_template_pointer_boundaries(
    template: TypeExpr,
    concrete: TypeExpr,
    expected: str,
) -> None:
    assert (
        _resolve_type_c(
            template,
            {"T": concrete},
            render=CTypeRenderer().render,
        )
        == expected
    )


def test_transitive_nullable_boundary_is_injective_in_instance_identity() -> None:
    direct = TypeExpr(base="int", pointer_depth=2, is_nullable=True)
    transitive = substitute_type_expr(
        TypeExpr(base="T", pointer_depth=1),
        {"T": TypeExpr(base="int", pointer_depth=1, is_nullable=True)},
    )

    assert transitive == TypeExpr(
        base="int",
        pointer_depth=2,
        is_nullable=True,
        nullable_outer_depth=1,
    )
    assert generic_instance_key("Inner", [direct]) != generic_instance_key("Inner", [transitive])
    assert mangle_generic_symbol("Inner", [direct]) != mangle_generic_symbol("Inner", [transitive])
    renderer = CTypeRenderer()
    assert renderer.render(direct) == "int*"
    assert renderer.render(transitive) == "int**"


@pytest.mark.parametrize("alias", ["RawPointer", "NullableInt", "IntArray", "TextAlias", "ItemAlias", "Callback"])
def test_nullable_typedef_use_reuses_reference_shaped_alias(alias: str) -> None:
    renderer = CTypeRenderer(TYPEDEFS)
    assert renderer.render(TypeExpr(base=alias, pointer_depth=1, is_nullable=True)) == alias


def test_outer_storage_add_and_remove_preserve_nullable_boundary() -> None:
    nullable_int = TypeExpr(base="int", pointer_depth=1, is_nullable=True)
    transitive_pointer = substitute_type_expr(
        TypeExpr(base="T", pointer_depth=1),
        {"T": nullable_int},
    )

    assert strip_outer_storage(TypeExpr(base="int", pointer_depth=2, is_nullable=True)) == TypeExpr(base="int")
    assert strip_outer_storage(transitive_pointer) == nullable_int
    nullable_raw_pointer = substitute_type_expr(
        TypeExpr(base="T", pointer_depth=2, is_nullable=True),
        {"T": TypeExpr(base="int")},
    )
    assert strip_outer_storage(nullable_raw_pointer) == TypeExpr(base="int")
    assert strip_outer_storage(
        TypeExpr(base="int", pointer_depth=1, is_nullable=True, is_array=True),
        array=True,
    ) == TypeExpr(base="int")
    assert (
        strip_outer_storage(
            TypeExpr(
                base="int",
                pointer_depth=1,
                is_nullable=True,
                nullable_outer_depth=1,
                is_array=True,
            ),
            array=True,
        )
        == nullable_int
    )
    address = add_outer_pointer(nullable_int)
    assert address == TypeExpr(
        base="int",
        pointer_depth=2,
        is_nullable=True,
        nullable_outer_depth=1,
    )
    assert CTypeRenderer().render(address) == "int**"
    assert strip_outer_storage(TypeExpr(base="string", pointer_depth=1, is_nullable=True)).pointer_depth == 0


def test_intrinsic_reference_depth_distinguishes_string_pointer_storage() -> None:
    scalar = TypeExpr(base="string", pointer_depth=1, is_nullable=True)
    pointer = TypeExpr(base="string", pointer_depth=2, is_nullable=True)
    analyzer = SemanticAnalyzer()

    renderer = CTypeRenderer()
    assert renderer.render(scalar) == "char*"
    assert renderer.render(pointer) == "char**"
    assert analyzer._semantic_pointer_depth(scalar) == 1
    assert analyzer._semantic_pointer_depth(pointer) == 2
    assert not analyzer._types_compatible(scalar, pointer)
