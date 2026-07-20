"""Adversarial IR contracts for setjmp visibility and cleanup metadata."""

import pytest

from src.compiler.python.ir.gen.setjmp_volatility import apply_setjmp_volatility
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCleanupSlot,
    IRExprStmt,
    IRFor,
    IRFunctionDef,
    IRFunctionRef,
    IRIf,
    IRLiteral,
    IRModule,
    IRStmtExpr,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)


def _setjmp_condition():
    return IRBinOp(
        IRCall("setjmp", [IRVar("frame")]),
        "==",
        IRLiteral("0"),
    )


def _direct_registration(metadata: IRCleanupSlot) -> IRExprStmt:
    return IRExprStmt(
        expr=IRCall(
            callee="__btrc_register_direct_cleanup",
            args=[
                IRCast(
                    target_type=CType("void*"),
                    expr=IRAddressOf(expr=IRVar(metadata.name)),
                ),
                IRFunctionRef(metadata.take_function),
                IRFunctionRef("destroy"),
            ],
            helper_ref="__btrc_register_direct_cleanup",
            cleanup_slot=metadata,
        )
    )


def _cleanup_declaration(metadata: IRCleanupSlot) -> IRVarDecl:
    return IRVarDecl(
        metadata.c_type,
        metadata.name,
        is_volatile=True,
        cleanup_slot=metadata,
    )


def _take_adapter() -> IRFunctionDef:
    return IRFunctionDef(
        name="take_slot",
        return_type=CType("void*"),
        body=IRBlock(),
        is_static=True,
    )


def test_current_setjmp_preserves_values_written_in_its_catch_branch():
    aggregate = IRVarDecl(CType("struct Probe"), "aggregate")
    branch = IRIf(
        condition=_setjmp_condition(),
        then_block=IRBlock(),
        else_block=IRBlock(stmts=[IRAssign(IRVar("aggregate"), IRLiteral("(struct Probe){0}"))]),
    )
    module = IRModule(
        function_defs=[
            IRFunctionDef(
                name="probe",
                return_type=CType("void"),
                body=IRBlock(stmts=[aggregate, branch]),
            )
        ]
    )

    apply_setjmp_volatility(module)

    assert aggregate.is_volatile


def test_vla_bound_write_resolves_before_the_new_declaration_is_bound():
    outer_extent = IRVarDecl(CType("int"), "extent")
    inner_extent = IRVarDecl(
        CType("int"),
        "extent",
        array_size=IRUnaryOp(op="++", operand=IRVar("extent")),
    )
    branch = IRIf(
        condition=_setjmp_condition(),
        then_block=IRBlock(stmts=[inner_extent]),
    )
    module = IRModule(
        function_defs=[
            IRFunctionDef(
                name="probe",
                return_type=CType("void"),
                body=IRBlock(stmts=[outer_extent, branch]),
            )
        ]
    )

    apply_setjmp_volatility(module)

    assert outer_extent.is_volatile
    assert not inner_extent.is_volatile


def test_stmt_expr_vla_bound_setjmp_observes_declaration_point_order():
    outer = IRVarDecl(CType("int"), "shadow")
    setup = IRVarDecl(
        CType("int"),
        "shadow",
        array_size=IRCall("setjmp", [IRVar("frame")]),
    )
    later = IRVarDecl(CType("int"), "__btrc_later")
    expression = IRStmtExpr(stmts=[setup, later], result=IRLiteral("0"))
    module = IRModule(
        function_defs=[
            IRFunctionDef(
                name="probe",
                return_type=CType("void"),
                body=IRBlock(stmts=[outer, IRExprStmt(expr=expression)]),
            )
        ]
    )

    apply_setjmp_volatility(module)

    assert outer.is_volatile
    assert not setup.is_volatile
    assert not later.is_volatile


def test_stmt_expr_to_the_right_is_hoisted_before_containing_setjmp_statement():
    call_result = IRVarDecl(CType("char*"), "__btrc_call_result")
    condition = IRBinOp(
        left=IRCall("setjmp", [IRVar("frame")]),
        op="==",
        right=IRStmtExpr(stmts=[call_result], result=IRLiteral("0")),
    )
    module = IRModule(
        function_defs=[
            IRFunctionDef(
                name="probe",
                return_type=CType("void"),
                body=IRBlock(stmts=[IRIf(condition=condition, then_block=IRBlock())]),
            )
        ]
    )

    apply_setjmp_volatility(module)

    assert call_result.is_volatile


def test_for_header_hoists_precede_setjmp_in_init_initializer():
    loop_index = IRVarDecl(
        CType("int"),
        "index",
        init=IRCall("setjmp", [IRVar("frame")]),
    )
    condition_temp = IRVarDecl(CType("int"), "__btrc_condition_temp")
    module = IRModule(
        function_defs=[
            IRFunctionDef(
                name="probe",
                return_type=CType("void"),
                body=IRBlock(
                    stmts=[
                        IRFor(
                            init=loop_index,
                            condition=IRStmtExpr(
                                stmts=[condition_temp],
                                result=IRLiteral("0"),
                            ),
                            body=IRBlock(),
                        )
                    ]
                ),
            )
        ]
    )

    apply_setjmp_volatility(module)

    assert loop_index.is_volatile
    assert condition_temp.is_volatile


def test_cleanup_validation_distinguishes_equal_metadata_at_distinct_sites():
    first_metadata = IRCleanupSlot("slot", CType("void*"), "take_slot")
    second_metadata = IRCleanupSlot("slot", CType("void*"), "take_slot")
    module = IRModule(
        function_defs=[
            _take_adapter(),
            IRFunctionDef(
                name="first",
                return_type=CType("void"),
                body=IRBlock(
                    stmts=[
                        _cleanup_declaration(first_metadata),
                        _direct_registration(first_metadata),
                    ]
                ),
            ),
            IRFunctionDef(
                name="second",
                return_type=CType("void"),
                body=IRBlock(stmts=[_cleanup_declaration(second_metadata)]),
            ),
        ]
    )

    with pytest.raises(ValueError, match="metadata has no registration: slot"):
        module.validate_declarations()


def test_cleanup_validation_rejects_shared_metadata_across_functions():
    shared_metadata = IRCleanupSlot("slot", CType("void*"), "take_slot")
    functions = [_take_adapter()]
    for name in ("first", "second"):
        functions.append(
            IRFunctionDef(
                name=name,
                return_type=CType("void"),
                body=IRBlock(
                    stmts=[
                        _cleanup_declaration(shared_metadata),
                        _direct_registration(shared_metadata),
                    ]
                ),
            )
        )
    module = IRModule(function_defs=functions)

    with pytest.raises(ValueError, match="attached more than once"):
        module.validate_declarations()
