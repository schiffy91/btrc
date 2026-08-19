"""White-box contracts for heterogeneous typed declaration planning."""

import pytest

from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.ir.nodes import (
    CType,
    IREnumDef,
    IREnumValue,
    IRFunctionPointerTypedef,
    IRModule,
    IRSizeof,
    IRStructDef,
    IRStructField,
    IRStructForward,
    IRTaggedUnionDef,
    IRTaggedUnionVariant,
    IRTypedefDef,
    IRVar,
)
from src.compiler.python.ir.optimizer import IROptimizer
from src.compiler.python.ir.verifier import IRVerifier


def _names(module: IRModule) -> list[str | None]:
    return [declaration.name for declaration in IROptimizer.plan_type_declarations(module)]


def test_cross_kind_dependencies_have_one_stable_plan():
    module = IRModule(
        enum_defs=[IREnumDef("Color", [IREnumValue("Color_Red")])],
        function_pointer_typedefs=[
            IRFunctionPointerTypedef(
                "Callback",
                CType("int"),
                [CType("int")],
            )
        ],
        typedef_defs=[IRTypedefDef(CType("Callback"), "Handler")],
        tagged_union_defs=[
            IRTaggedUnionDef(
                "Payload",
                CType("Color"),
                [
                    IRTaggedUnionVariant(
                        "Tuple",
                        [IRStructField(CType("PairTuple"), "value")],
                    )
                ],
            )
        ],
        struct_defs=[
            IRStructDef(
                "Outer",
                [IRStructField(CType("Payload"), "payload")],
            ),
            IRStructDef(
                "PairTuple",
                [IRStructField(CType("Pair"), "pair")],
            ),
            IRStructDef(
                "Pair",
                [IRStructField(CType("int"), "value")],
            ),
        ],
    )

    assert _names(module) == [
        "Color",
        "Callback",
        "Handler",
        "Pair",
        "PairTuple",
        "Payload",
        "Outer",
    ]


def test_pointer_through_alias_needs_alias_but_not_complete_target():
    module = IRModule(
        struct_forwards=[IRStructForward("Node")],
        typedef_defs=[IRTypedefDef(CType("Node"), "NodeAlias")],
        struct_defs=[
            IRStructDef(
                "Node",
                [IRStructField(CType("NodeAlias*"), "next")],
            )
        ],
    )

    assert _names(module) == ["NodeAlias", "Node"]


def test_by_value_alias_requires_its_aggregate_target_to_be_complete():
    module = IRModule(
        struct_forwards=[
            IRStructForward("Holder"),
            IRStructForward("Pair"),
        ],
        typedef_defs=[IRTypedefDef(CType("Pair"), "Alias")],
        struct_defs=[
            IRStructDef(
                "Holder",
                [IRStructField(CType("Alias"), "value")],
            ),
            IRStructDef("Pair", [IRStructField(CType("int"), "value")]),
        ],
    )

    assert _names(module) == ["Alias", "Pair", "Holder"]


def test_enum_value_dependencies_are_ordered_without_self_cycles():
    module = IRModule(
        enum_defs=[
            IREnumDef(
                "Second",
                [IREnumValue("Second_Value", IRVar("First_Value"))],
            ),
            IREnumDef(
                "First",
                [
                    IREnumValue("First_Base"),
                    IREnumValue("First_Value", IRVar("First_Base")),
                ],
            ),
        ]
    )

    assert _names(module) == ["First", "Second"]


def test_enum_sizeof_waits_for_complete_aggregate():
    module = IRModule(
        enum_defs=[
            IREnumDef(
                "Size",
                [IREnumValue("Size_Pair", IRSizeof(CType("Pair")))],
            )
        ],
        struct_defs=[IRStructDef("Pair", [IRStructField(CType("int"), "value")])],
    )

    assert _names(module) == ["Pair", "Size"]


def test_function_pointer_signatures_accept_forwarded_aggregates():
    module = IRModule(
        struct_forwards=[IRStructForward("Pair")],
        function_pointer_typedefs=[
            IRFunctionPointerTypedef(
                "Callback",
                CType("Pair"),
                [CType("Pair")],
            )
        ],
        struct_defs=[IRStructDef("Pair", [IRStructField(CType("int"), "value")])],
    )

    assert _names(module) == ["Callback", "Pair"]


def test_fixed_array_elements_require_complete_aggregate():
    module = IRModule(
        struct_defs=[
            IRStructDef(
                "Box",
                [
                    IRStructField(
                        CType("Pair"),
                        "values",
                        array_size=IRVar("COUNT"),
                    )
                ],
            ),
            IRStructDef("Pair", [IRStructField(CType("int"), "value")]),
        ]
    )

    assert _names(module) == ["Pair", "Box"]


def test_nested_value_alias_chain_keeps_complete_target_dependency():
    module = IRModule(
        typedef_defs=[
            IRTypedefDef(CType("Pair"), "FirstAlias"),
            IRTypedefDef(CType("FirstAlias"), "SecondAlias"),
        ],
        struct_defs=[
            IRStructDef(
                "Box",
                [IRStructField(CType("SecondAlias"), "value")],
            ),
            IRStructDef("Pair", [IRStructField(CType("int"), "value")]),
        ],
    )

    assert _names(module) == [
        "FirstAlias",
        "SecondAlias",
        "Pair",
        "Box",
    ]


def test_nested_pointer_alias_chain_does_not_require_complete_target():
    module = IRModule(
        typedef_defs=[
            IRTypedefDef(CType("Pair*"), "PairPointer"),
            IRTypedefDef(CType("PairPointer"), "PointerAlias"),
        ],
        struct_defs=[
            IRStructDef(
                "Box",
                [IRStructField(CType("PointerAlias"), "values")],
            ),
            IRStructDef("Pair", [IRStructField(CType("int"), "value")]),
        ],
    )

    assert _names(module) == [
        "PairPointer",
        "PointerAlias",
        "Box",
        "Pair",
    ]


def test_by_value_aggregate_cycles_fail_closed():
    module = IRModule()
    module.struct_defs = [
        IRStructDef("Left", [IRStructField(CType("Right"), "right")]),
        IRStructDef("Right", [IRStructField(CType("Left"), "left")]),
    ]

    with pytest.raises(ValueError, match="cyclic typed C declaration dependency"):
        IROptimizer.plan_type_declarations(module)


def test_typedef_cycles_fail_closed():
    module = IRModule()
    module.typedef_defs = [
        IRTypedefDef(CType("Second"), "First"),
        IRTypedefDef(CType("First"), "Second"),
    ]

    with pytest.raises(ValueError, match="cyclic typed C declaration dependency"):
        IROptimizer.plan_type_declarations(module)


def test_duplicate_type_providers_fail_closed():
    module = IRModule()
    module.typedef_defs = [IRTypedefDef(CType("int"), "Value")]
    module.struct_defs = [IRStructDef("Value")]

    with pytest.raises(ValueError, match="duplicate typed C declaration provider 'Value'"):
        IROptimizer.plan_type_declarations(module)


def test_module_rejects_a_stale_ordered_declaration_view():
    module = IRModule(struct_defs=[IRStructDef("Pair", [IRStructField(CType("int"), "value")])])
    IROptimizer.refresh_type_declarations(module)
    module.struct_defs.append(IRStructDef("Box"))

    with pytest.raises(ValueError, match="ordered_type_declarations is stale"):
        IRVerifier(module).validate()

    IROptimizer.refresh_type_declarations(module)
    assert [item.name for item in module.ordered_type_declarations] == [
        "Pair",
        "Box",
    ]


def test_archive_header_formats_the_module_ordered_view():
    module = IRModule(
        struct_forwards=[IRStructForward("Outer"), IRStructForward("Pair")],
        struct_defs=[
            IRStructDef("Outer", [IRStructField(CType("Pair"), "pair")]),
            IRStructDef("Pair", [IRStructField(CType("int"), "value")]),
        ],
    )

    IROptimizer.refresh_type_declarations(module)
    header = CEmitter().emit_header(module)
    assert header.index("struct Pair {") < header.index("struct Outer {")
