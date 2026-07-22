"""Contracts for setjmp mutations reached through structured continuations."""

from src.compiler.python.ir.gen.setjmp_call_effects import build_setjmp_call_effects
from src.compiler.python.ir.gen.setjmp_effect_model import ParameterEffect
from src.compiler.python.ir.gen.setjmp_volatility import apply_setjmp_volatility
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCase,
    IRCommaExpr,
    IRDeref,
    IRExprStmt,
    IRFor,
    IRFunctionDecl,
    IRFunctionDef,
    IRIf,
    IRIndex,
    IRLiteral,
    IRModule,
    IRParam,
    IRStmtExpr,
    IRSwitch,
    IRTypedefDef,
    IRVar,
    IRVarDecl,
)
from src.tests.python.test_codegen import emit_c


def _setjmp_condition():
    return IRBinOp(
        IRCall("setjmp", [IRVar("frame")]),
        "==",
        IRLiteral("0"),
    )


def _module(*statements):
    return IRModule(
        function_defs=[
            IRFunctionDef(
                name="probe",
                return_type=CType("void"),
                body=IRBlock(stmts=list(statements)),
            )
        ]
    )


def test_following_sequence_mutation_is_volatile():
    value = IRVarDecl(CType("int"), "value", IRLiteral("0"))
    branch = IRIf(condition=_setjmp_condition(), then_block=IRBlock())
    module = _module(
        value,
        branch,
        IRAssign(IRVar("value"), IRLiteral("1")),
    )

    apply_setjmp_volatility(module)

    assert value.is_volatile


def test_switch_case_sequence_mutation_is_volatile():
    value = IRVarDecl(CType("int"), "value", IRLiteral("0"))
    branch = IRIf(condition=_setjmp_condition(), then_block=IRBlock())
    switch = IRSwitch(
        value=IRLiteral("1"),
        cases=[
            IRCase(
                value=IRLiteral("1"),
                body=[
                    branch,
                    IRAssign(IRVar("value"), IRLiteral("1")),
                ],
            )
        ],
    )
    module = _module(value, switch)

    apply_setjmp_volatility(module)

    assert value.is_volatile


def test_switch_fallthrough_mutation_is_volatile():
    value = IRVarDecl(CType("int"), "value", IRLiteral("0"))
    branch = IRIf(condition=_setjmp_condition(), then_block=IRBlock())
    switch = IRSwitch(
        value=IRLiteral("1"),
        cases=[
            IRCase(
                value=IRLiteral("1"),
                body=[branch],
                falls_through=True,
            ),
            IRCase(
                value=IRLiteral("2"),
                body=[IRAssign(IRVar("value"), IRLiteral("1"))],
            ),
        ],
    )
    module = _module(value, switch)

    apply_setjmp_volatility(module)

    assert value.is_volatile


def test_loop_backedge_marks_update_and_following_body_mutation():
    finally_count = IRVarDecl(CType("int"), "finally_count", IRLiteral("0"))
    index = IRVarDecl(CType("int"), "index", IRLiteral("0"))
    branch = IRIf(condition=_setjmp_condition(), then_block=IRBlock())
    loop = IRFor(
        init=index,
        condition=IRBinOp(IRVar("index"), "<", IRLiteral("2")),
        update=IRBinOp(
            IRVar("index"),
            "=",
            IRBinOp(IRVar("index"), "+", IRLiteral("1")),
        ),
        body=IRBlock(
            stmts=[
                branch,
                IRAssign(
                    IRVar("finally_count"),
                    IRBinOp(IRVar("finally_count"), "+", IRLiteral("1")),
                ),
            ]
        ),
    )
    module = _module(finally_count, loop)

    apply_setjmp_volatility(module)

    assert index.is_volatile
    assert finally_count.is_volatile


def test_future_shadow_mutation_does_not_qualify_outer_aggregate():
    outer = IRVarDecl(CType("struct Probe"), "value")
    branch = IRIf(condition=_setjmp_condition(), then_block=IRBlock())
    inner = IRVarDecl(CType("int"), "value", IRLiteral("0"))
    module = _module(
        outer,
        branch,
        IRBlock(
            stmts=[
                inner,
                IRAssign(IRVar("value"), IRLiteral("1")),
            ]
        ),
    )

    apply_setjmp_volatility(module)

    assert not outer.is_volatile
    assert not inner.is_volatile


def test_lowered_aggregate_store_retains_original_storage_root():
    aggregate = IRVarDecl(CType("struct Probe"), "value")
    pointer = IRVarDecl(CType("volatile int*"), "slot")
    load = IRDeref(
        expr=IRVar("slot"),
        storage_root="value",
        storage_root_known=True,
    )
    lowered_store = IRStmtExpr(
        stmts=[pointer],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(
                    IRVar("slot"),
                    "=",
                    IRAddressOf(IRIndex(IRVar("value"), IRLiteral("0"))),
                ),
                IRBinOp(load, "=", IRLiteral("1")),
            ]
        ),
    )
    branch = IRIf(
        condition=_setjmp_condition(),
        then_block=IRBlock(stmts=[IRExprStmt(lowered_store)]),
    )
    module = _module(aggregate, branch)

    apply_setjmp_volatility(module)

    assert aggregate.is_volatile


def test_pointer_index_store_does_not_mark_pointer_object_modified():
    pointer = IRVarDecl(CType("int*"), "pointer")
    pointee = IRIndex(
        IRVar("pointer"),
        IRLiteral("0"),
        storage_root_known=True,
    )
    branch = IRIf(
        condition=_setjmp_condition(),
        then_block=IRBlock(stmts=[IRExprStmt(IRBinOp(pointee, "=", IRLiteral("1")))]),
    )
    module = _module(pointer, branch)

    apply_setjmp_volatility(module)

    assert not pointer.is_volatile


def test_call_effect_summary_resolves_pointer_typedefs():
    pointer = IRTypedefDef(CType("int*"), "IntPointer")
    mutate = IRFunctionDef(
        name="mutate",
        return_type=CType("void"),
        params=[IRParam(CType("IntPointer"), "value")],
        body=IRBlock(
            stmts=[
                IRExprStmt(
                    IRBinOp(
                        IRDeref(IRVar("value")),
                        "=",
                        IRLiteral("1"),
                    )
                )
            ]
        ),
    )
    probe = IRFunctionDef(
        name="probe",
        return_type=CType("void"),
        body=IRBlock(),
    )

    effects = build_setjmp_call_effects(IRModule(typedef_defs=[pointer], function_defs=[mutate, probe]))["probe"]

    assert effects.written_arguments("mutate", 1) == frozenset({0})


def test_custom_external_const_pointer_is_not_a_read_only_contract():
    mutable = IRTypedefDef(CType("int*"), "IntPointer")
    read_only = IRTypedefDef(CType("const int*"), "ConstIntPointer")
    declarations = [
        IRFunctionDecl(
            name="mutate",
            return_type=CType("void"),
            params=[IRParam(CType("IntPointer"), "value")],
        ),
        IRFunctionDecl(
            name="custom_read",
            return_type=CType("int"),
            params=[IRParam(CType("ConstIntPointer"), "value")],
        ),
    ]
    probe = IRFunctionDef(
        name="probe",
        return_type=CType("void"),
        body=IRBlock(),
    )

    effects = build_setjmp_call_effects(
        IRModule(
            typedef_defs=[mutable, read_only],
            function_decls=declarations,
            function_defs=[probe],
        )
    )["probe"]

    assert effects.written_arguments("mutate", 1) == frozenset({0})
    assert effects.written_arguments("custom_read", 1) == frozenset({0})
    assert effects.effect_for("custom_read", 1).captures == frozenset({ParameterEffect(0)})


def test_static_shadow_blocks_outer_automatic_qualification():
    outer = IRVarDecl(CType("int"), "value", IRLiteral("0"))
    shadow = IRVarDecl(
        CType("int"),
        "value",
        IRLiteral("0"),
        is_static=True,
    )
    branch = IRIf(
        condition=_setjmp_condition(),
        then_block=IRBlock(stmts=[IRAssign(IRVar("value"), IRLiteral("1"))]),
    )
    module = _module(
        outer,
        IRBlock(stmts=[shadow, branch]),
    )

    apply_setjmp_volatility(module)

    assert not outer.is_volatile
    assert not shadow.is_volatile


def test_try_finally_loop_emits_volatile_continuation_objects():
    emitted = emit_c("""
        int main() {
            int finallyCount = 0;
            for (int i = 0; i < 2; i++) {
                try { if (i == 0) { continue; } }
                finally { finallyCount++; }
            }
            return finallyCount;
        }
    """)

    assert "volatile int finallyCount = 0;" in emitted
    assert "volatile int i = 0;" in emitted
