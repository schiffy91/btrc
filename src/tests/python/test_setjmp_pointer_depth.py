"""Pointer-depth parity contracts for Python setjmp effect analysis."""

import pytest

from src.compiler.python.ir.lowering.exceptions import (
    OPAQUE_POINTER_DEPTH,
    ExceptionLowerer,
    ParameterEffect,
)
from src.compiler.python.ir.lowering.types import CodegenError
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBlock,
    IRCall,
    IRCast,
    IRDeref,
    IRExprStmt,
    IRFunctionDef,
    IRIndex,
    IRLiteral,
    IRModule,
    IRParam,
    IRReturn,
    IRTernary,
    IRTypedefDef,
    IRVar,
    IRVarDecl,
)
from src.tests.python.test_codegen import emit_c


def _dereference(value, count):
    for _ in range(count):
        value = IRDeref(value)
    return value


def _deep_typedefs():
    return [
        IRTypedefDef(CType("Middle*"), "Triple"),
        IRTypedefDef(CType("int*"), "Single"),
        IRTypedefDef(CType("Single*"), "Middle"),
    ]


def test_pointer_depth_closure_is_exact_and_order_independent():
    facts = ExceptionLowerer.pointer_type_facts(IRModule(typedef_defs=_deep_typedefs()))

    assert facts.pointer_depth(CType("Single")) == 1
    assert facts.pointer_depth(CType("Middle")) == 2
    assert facts.pointer_depth(CType("Triple")) == 3
    assert facts.pointer_depth(CType("const Triple*")) == 4


def test_terminal_scalar_dereference_drops_return_provenance_through_casts():
    pointer = IRVar("pointer")
    cast_chain = IRCast(CType("char***"), IRCast(CType("void***"), pointer))
    scalar = IRFunctionDef(
        "scalar",
        CType("int"),
        [IRParam(CType("Triple"), "pointer")],
        IRBlock([IRReturn(_dereference(cast_chain, 3))]),
    )
    peel = IRFunctionDef(
        "peel",
        CType("int*"),
        [IRParam(CType("Triple"), "pointer")],
        IRBlock([IRReturn(_dereference(IRVar("pointer"), 2))]),
    )
    probe = IRFunctionDef("probe", CType("void"), body=IRBlock())

    catalog = ExceptionLowerer.build_setjmp_call_effects(
        IRModule(typedef_defs=_deep_typedefs(), function_defs=[scalar, peel, probe])
    )["probe"].catalog

    assert catalog.resolve("scalar", 1).returns == frozenset()
    assert catalog.resolve("peel", 1).returns == frozenset({ParameterEffect(0, 3)})


def test_recursive_return_summary_reaches_a_finite_declared_depth_fixed_point():
    recursive_call = IRCall("recursive", [IRVar("pointer")])
    recursive = IRFunctionDef(
        "recursive",
        CType("int*"),
        [IRParam(CType("int*"), "pointer")],
        IRBlock(
            [
                IRReturn(
                    IRTernary(
                        IRLiteral("1"),
                        IRVar("pointer"),
                        IRDeref(recursive_call),
                    )
                )
            ]
        ),
    )

    catalog = ExceptionLowerer.build_setjmp_call_effects(IRModule(function_defs=[recursive]))["recursive"].catalog

    assert catalog.resolve("recursive", 1).returns == frozenset({ParameterEffect(0, 1)})


def test_unresolved_pointer_depth_saturates_instead_of_growing():
    typedefs = [
        IRTypedefDef(CType("OpaqueB"), "OpaqueA"),
        IRTypedefDef(CType("OpaqueA*"), "OpaqueB"),
    ]
    module = IRModule()
    module.typedef_defs = typedefs
    facts = ExceptionLowerer.pointer_type_facts(module)
    opaque = IRFunctionDef(
        "opaque",
        CType("int*"),
        [IRParam(CType("OpaqueA"), "pointer")],
        IRBlock([IRReturn(_dereference(IRVar("pointer"), 8))]),
    )

    module.function_defs = [opaque]
    catalog = ExceptionLowerer.build_setjmp_call_effects(module)["opaque"].catalog

    assert facts.pointer_depth(CType("OpaqueA")) == OPAQUE_POINTER_DEPTH
    assert facts.pointer_depth(CType("OpaqueB")) == OPAQUE_POINTER_DEPTH
    assert catalog.resolve("opaque", 1).returns == frozenset({ParameterEffect(0, OPAQUE_POINTER_DEPTH)})


def test_saturated_write_effect_maps_back_to_concrete_caller_storage():
    typedefs = [
        IRTypedefDef(CType("OpaqueB"), "OpaqueA"),
        IRTypedefDef(CType("OpaqueA*"), "OpaqueB"),
    ]
    opaque_write = IRFunctionDef(
        "opaque_write",
        CType("void"),
        [IRParam(CType("OpaqueA"), "pointer")],
        IRBlock([IRAssign(_dereference(IRVar("pointer"), 8), IRLiteral("7"))]),
    )
    value = IRVarDecl(CType("int"), "value", IRLiteral("0"))
    pointer = IRVarDecl(
        CType("int*"),
        "pointer",
        IRAddressOf(IRVar("value"), source_expression=True),
    )
    call = IRCall("opaque_write", [IRVar("pointer")])
    caller = IRFunctionDef(
        "caller",
        CType("void"),
        body=IRBlock([value, pointer, IRExprStmt(call)]),
    )
    module = IRModule()
    module.typedef_defs = typedefs
    module.function_defs = [opaque_write, caller]

    effects = ExceptionLowerer.build_setjmp_call_effects(module)

    assert effects["opaque_write"].catalog.resolve("opaque_write", 1).writes == frozenset(
        {ParameterEffect(0, OPAQUE_POINTER_DEPTH)}
    )
    assert {(origin.storage.identity, origin.depth) for origin in effects["caller"].flow.writes[id(call)]} == {
        (id(value), 0)
    }


def test_pointer_array_element_store_is_a_capture_not_a_scalar_strong_update():
    value = IRVarDecl(CType("int"), "value", IRLiteral("0"))
    slots = IRVarDecl(CType("int*"), "slots", array_size=IRLiteral("1"))
    store = IRAssign(
        IRIndex(
            IRVar("slots", array_storage_root="slots", array_storage_known=True),
            IRLiteral("0"),
            storage_root="slots",
            storage_root_known=True,
        ),
        IRAddressOf(IRVar("value"), source_expression=True),
    )
    probe = IRFunctionDef(
        "probe",
        CType("void"),
        body=IRBlock([value, slots, store]),
    )

    flow = ExceptionLowerer.build_setjmp_call_effects(IRModule(function_defs=[probe]))["probe"].flow
    slots_storage = flow.storages[id(slots)]

    assert slots_storage.pointer_depth == 1
    assert slots_storage.is_array
    assert {origin.storage.identity for origin in flow.captures} == {id(value)}


def test_deep_typedef_pointer_write_reaches_the_concrete_automatic():
    with pytest.raises(CodegenError, match="requires volatile storage"):
        emit_c("""
            typedef int* Single;
            typedef Single* Middle;
            typedef Middle* Triple;
            void mutate(Triple pointer) { ***pointer = 7; }
            int main() {
                int value = 0;
                Single single = &value;
                Middle middle = &single;
                Triple triple = &middle;
                try { mutate(triple); throw "boom"; }
                catch (string error) {}
                return value;
            }
        """)


@pytest.mark.parametrize(
    "setup, cast_type, dereferences, argument",
    [
        ("int* pointer = &value;", "int**", "**slot", "&pointer"),
        (
            "int* pointer = &value; int** middle = &pointer;",
            "int***",
            "***slot",
            "&middle",
        ),
    ],
)
def test_void_pointer_round_trip_widening_saturates_conservatively(
    setup,
    cast_type,
    dereferences,
    argument,
):
    with pytest.raises(CodegenError, match="unmodelled pointer value"):
        emit_c(f"""
            void mutate(void* opaque) {{
                {cast_type} slot = ({cast_type})opaque;
                {dereferences} = 7;
            }}
            int main() {{
                int value = 0;
                {setup}
                try {{ mutate({argument}); throw "boom"; }}
                catch (string error) {{}}
                return value;
            }}
        """)


@pytest.mark.parametrize(
    "declarations, cast_type",
    [
        ("", "void"),
        ("", "const void"),
        ("typedef void Nothing;", "Nothing"),
    ],
)
def test_void_discard_cast_does_not_capture_pointer_provenance(declarations, cast_type):
    emitted = emit_c(f"""
        {declarations}
        int main() {{
            int value = 0;
            ({cast_type})(&value);
            try {{ throw "boom"; }}
            catch (string error) {{}}
            return value;
        }}
    """)

    assert "int value = 0;" in emitted
    assert "volatile int value" not in emitted
