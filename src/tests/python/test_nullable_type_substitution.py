"""Nullable generic substitution must preserve value-level reference ABIs."""

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.analyzer.types import TypeIdentity, TypeShapeError, TypeSystem
from src.compiler.python.ir.lowering.generics import TypeSubstitution
from src.compiler.python.ir.lowering.session import LoweringSession
from src.compiler.python.ir.lowering.types import CTypeLowerer
from src.compiler.python.ir.nodes import IRModule
from src.compiler.python.syntax.ast.generated import Program, TypeExpr

IDENTITY = TypeIdentity()

TYPEDEFS = {
    "ItemAlias": TypeExpr(base="Item", pointer_depth=1),
    "AliasChain": TypeExpr(base="ItemAlias"),
    "TextAlias": TypeExpr(base="string"),
    "RawPointer": TypeExpr(base="int", pointer_depth=1),
    "NullableInt": TypeExpr(base="int", pointer_depth=1, is_nullable=True),
    "IntArray": TypeExpr(base="int", is_array=True),
    "Callback": TypeExpr(base="__fn_ptr", generic_args=[TypeExpr(base="void")]),
}


def _renderer(typedefs: dict[str, TypeExpr] | None = None) -> CTypeLowerer:
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={},
        typedef_table=dict(typedefs or {}),
    )
    session = LoweringSession(module=IRModule(), node_types=analyzed.node_types)
    return CTypeLowerer(session, analyzed, IDENTITY)


def _nullable_parameter() -> TypeExpr:
    return TypeExpr(base="T", pointer_depth=1, is_nullable=True)


def test_nullable_parameter_reuses_resolved_class_reference_layer() -> None:
    resolved = TypeExpr(base="Item", pointer_depth=1)

    result = IDENTITY.substitute(_nullable_parameter(), {"T": resolved})

    assert result == TypeExpr(
        base="Item",
        pointer_depth=1,
        is_nullable=True,
    )


def test_nullable_parameter_reuses_intrinsic_handle_layer() -> None:
    resolved = TypeExpr(base="Mutex", generic_args=[TypeExpr(base="int")])

    result = IDENTITY.substitute(_nullable_parameter(), {"T": resolved})

    assert result == TypeExpr(
        base="Mutex",
        generic_args=[TypeExpr(base="int")],
        is_nullable=True,
    )


def test_normalized_nullable_string_remains_a_scalar_string() -> None:
    result = IDENTITY.substitute(
        _nullable_parameter(),
        {"T": TypeExpr(base="string")},
    )

    assert result == TypeExpr(base="string", is_nullable=True)
    assert IDENTITY.is_scalar_string(result)


def test_nullable_parameter_still_lifts_a_value_type() -> None:
    resolved = TypeExpr(base="int")

    result = IDENTITY.substitute(_nullable_parameter(), {"T": resolved})

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
    renderer = _renderer(TYPEDEFS)
    result = IDENTITY.substitute(
        _nullable_parameter(),
        {"T": TypeExpr(base=alias)},
        reference_resolver=renderer.canonical_type,
    )

    assert result == TypeExpr(base=alias, is_nullable=True)
    assert renderer.canonical_type(result) == canonical


def test_explicit_pointer_and_array_modifiers_compose_once_through_aliases() -> None:
    explicit_pointer = TypeExpr(base="T", pointer_depth=2, is_nullable=True)
    array_of_nullable = TypeExpr(
        base="T",
        pointer_depth=1,
        is_nullable=True,
        is_array=True,
    )
    renderer = _renderer(TYPEDEFS)

    pointer = IDENTITY.substitute(
        explicit_pointer,
        {"T": TypeExpr(base="AliasChain")},
        reference_resolver=renderer.canonical_type,
    )
    array = IDENTITY.substitute(
        array_of_nullable,
        {"T": TypeExpr(base="AliasChain")},
        reference_resolver=renderer.canonical_type,
    )

    assert pointer == TypeExpr(
        base="AliasChain",
        pointer_depth=1,
        is_nullable=True,
        nullable_outer_depth=1,
    )
    assert renderer.canonical_type(pointer) == TypeExpr(
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
    assert renderer.canonical_type(array) == TypeExpr(
        base="Item",
        pointer_depth=1,
        is_nullable=True,
        is_array=True,
        nullable_outer_depth=1,
    )


def test_alias_to_array_still_rejects_nested_array_composition() -> None:
    renderer = _renderer(TYPEDEFS)
    with pytest.raises(TypeShapeError, match="nested array composition"):
        IDENTITY.substitute(
            TypeExpr(base="T", is_array=True),
            {"T": TypeExpr(base="IntArray")},
            reference_resolver=renderer.canonical_type,
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
    resolved = TypeSubstitution(
        arguments={"T": concrete},
        typedefs={},
        identity=IDENTITY,
    ).resolve(template)
    assert _renderer().render(resolved) == expected


def test_transitive_nullable_boundary_is_injective_in_instance_identity() -> None:
    direct = TypeExpr(base="int", pointer_depth=2, is_nullable=True)
    transitive = IDENTITY.substitute(
        TypeExpr(base="T", pointer_depth=1),
        {"T": TypeExpr(base="int", pointer_depth=1, is_nullable=True)},
    )

    assert transitive == TypeExpr(
        base="int",
        pointer_depth=2,
        is_nullable=True,
        nullable_outer_depth=1,
    )
    assert IDENTITY.generic_instance_key("Inner", [direct]) != IDENTITY.generic_instance_key("Inner", [transitive])
    assert IDENTITY.generic_symbol("Inner", [direct]) != IDENTITY.generic_symbol("Inner", [transitive])
    renderer = _renderer()
    assert renderer.render(direct) == "int*"
    assert renderer.render(transitive) == "int**"


@pytest.mark.parametrize("alias", ["RawPointer", "NullableInt", "IntArray", "TextAlias", "ItemAlias", "Callback"])
def test_nullable_typedef_use_reuses_reference_shaped_alias(alias: str) -> None:
    renderer = _renderer(TYPEDEFS)
    assert renderer.render(TypeExpr(base=alias, pointer_depth=1, is_nullable=True)) == alias


def test_outer_storage_add_and_remove_preserve_nullable_boundary() -> None:
    nullable_int = TypeExpr(base="int", pointer_depth=1, is_nullable=True)
    transitive_pointer = IDENTITY.substitute(
        TypeExpr(base="T", pointer_depth=1),
        {"T": nullable_int},
    )

    assert TypeSystem.strip_outer_storage(TypeExpr(base="int", pointer_depth=2, is_nullable=True)) == TypeExpr(
        base="int"
    )
    assert TypeSystem.strip_outer_storage(transitive_pointer) == nullable_int
    nullable_raw_pointer = IDENTITY.substitute(
        TypeExpr(base="T", pointer_depth=2, is_nullable=True),
        {"T": TypeExpr(base="int")},
    )
    assert TypeSystem.strip_outer_storage(nullable_raw_pointer) == TypeExpr(base="int")
    assert TypeSystem.strip_outer_storage(
        TypeExpr(base="int", pointer_depth=1, is_nullable=True, is_array=True),
        array=True,
    ) == TypeExpr(base="int")
    assert (
        TypeSystem.strip_outer_storage(
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
    address = TypeSystem.add_outer_pointer(nullable_int)
    assert address == TypeExpr(
        base="int",
        pointer_depth=2,
        is_nullable=True,
        nullable_outer_depth=1,
    )
    assert _renderer().render(address) == "int**"
    assert TypeSystem.strip_outer_storage(TypeExpr(base="string", pointer_depth=1, is_nullable=True)).pointer_depth == 0


def test_intrinsic_reference_depth_distinguishes_string_pointer_storage() -> None:
    scalar = TypeExpr(base="string", pointer_depth=1, is_nullable=True)
    pointer = TypeExpr(base="string", pointer_depth=2, is_nullable=True)
    types = SemanticAnalyzer().types

    renderer = _renderer()
    assert renderer.render(scalar) == "char*"
    assert renderer.render(pointer) == "char**"
    assert types.semantic_pointer_depth(scalar) == 1
    assert types.semantic_pointer_depth(pointer) == 2
    assert not types.types_compatible(scalar, pointer)
