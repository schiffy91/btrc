"""Jump IR invariants, sequence flow and strict C11 emission."""

import subprocess

import pytest

from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRCall,
    IRCase,
    IRCxxExceptionBoundary,
    IRExprStmt,
    IRFunctionDef,
    IRGoto,
    IRGpuKernel,
    IRGpuShaderModule,
    IRIf,
    IRLabel,
    IRLineMarker,
    IRLiteral,
    IRModule,
    IRObjectiveCAutoreleasePool,
    IRObjectiveCExceptionBoundary,
    IRReturn,
    IRStatementSequence,
    IRStmtExpr,
    IRSwitch,
)
from src.compiler.python.ir.verifier import IRVerifier
from src.tests.c_toolchains import configured_c_compiler, requires_host_c_compiler


def _module(statements, *, language="c", realtime=False):
    return IRModule(
        language=language,
        function_defs=[
            IRFunctionDef(
                name="main",
                return_type=CType("int"),
                body=IRBlock(stmts=statements),
                is_realtime=realtime,
            )
        ],
    )


@pytest.mark.parametrize(
    "statements, expected",
    [
        ([IRGoto("done")], False),
        ([IRGoto("done"), IRLabel("done")], True),
        ([IRReturn(), IRLabel("done"), IRLineMarker(file="a.btrc", line=1)], True),
        ([IRGoto("done"), IRLabel("done"), IRReturn()], False),
        ([IRLabel("again"), IRGoto("again")], False),
        ([IRBlock(stmts=[IRGoto("done")]), IRLabel("done")], True),
        (
            [
                IRIf(
                    condition=IRLiteral("1"),
                    then_block=IRBlock(stmts=[IRGoto("done")]),
                    else_block=IRBlock(stmts=[IRReturn()]),
                )
            ],
            False,
        ),
    ],
)
def test_jump_sequence_fallthrough(statements, expected):
    assert IRStatementSequence(statements).may_fall_through() is expected


@pytest.mark.parametrize(
    "statements, diagnostic",
    [
        ([IRGoto("missing")], "has no label"),
        ([IRLabel("unused")], "has no goto"),
        ([IRGoto("x"), IRLabel("x"), IRLabel("x")], "Duplicate IR label"),
        ([IRGoto("inner"), IRBlock(stmts=[IRLabel("inner")])], "nested statement list"),
        ([IRBlock(stmts=[IRGoto("other")]), IRBlock(stmts=[IRLabel("other")])], "nested statement list"),
        (
            [IRExprStmt(expr=IRStmtExpr(stmts=[IRGoto("out")], result=IRLiteral("0"))), IRLabel("out")],
            "statement expression",
        ),
        (
            [IRIf(condition=IRCall(callee="setjmp"), then_block=IRBlock(stmts=[IRGoto("out")])), IRLabel("out")],
            "exception or autorelease",
        ),
    ],
)
def test_malformed_jump_ir_is_rejected(statements, diagnostic):
    with pytest.raises(ValueError, match=diagnostic):
        IRVerifier(_module(statements)).validate()


@pytest.mark.parametrize(
    "boundary, language",
    [
        (lambda body: IRObjectiveCAutoreleasePool(body=body), "objective-c"),
        (lambda body: IRObjectiveCExceptionBoundary(body=body, failure=IRBlock()), "objective-c"),
        (lambda body: IRCxxExceptionBoundary(body=body, failure=IRBlock()), "c++"),
    ],
)
def test_jump_cannot_leave_native_protected_region(boundary, language):
    module = _module([boundary(IRBlock(stmts=[IRGoto("out")])), IRLabel("out")], language=language)
    with pytest.raises(ValueError, match="exception or autorelease"):
        IRVerifier(module).validate()


def test_jump_within_setjmp_branch_and_out_of_plain_block_is_valid():
    body = IRBlock(stmts=[IRBlock(stmts=[IRGoto("done")]), IRLabel("done"), IRReturn(IRLiteral("0"))])
    IRVerifier(_module([IRIf(condition=IRCall(callee="setjmp"), then_block=body)])).validate()


def test_jump_cannot_enter_another_switch_case():
    switch = IRSwitch(
        value=IRLiteral("0"),
        cases=[IRCase(value=IRLiteral("0"), body=[IRGoto("other")]), IRCase(body=[IRLabel("other")])],
    )
    with pytest.raises(ValueError, match="nested statement list"):
        IRVerifier(_module([switch])).validate()


def test_gpu_shader_cannot_contain_jump_ir():
    kernel = IRGpuKernel(
        name="kernel", shader_module=IRGpuShaderModule(body=IRBlock(stmts=[IRGoto("x"), IRLabel("x")]))
    )
    module = _module([])
    module.gpu_kernels.append(kernel)
    with pytest.raises(ValueError, match="GPU kernels"):
        IRVerifier(module).validate()


def test_labels_are_local_to_each_function():
    module = _module([IRGoto("done"), IRLabel("done"), IRReturn(IRLiteral("0"))])
    module.function_defs.append(
        IRFunctionDef(name="other", return_type=CType("void"), body=IRBlock(stmts=[IRGoto("done"), IRLabel("done")]))
    )
    IRVerifier(module).validate()


def test_realtime_ir_refuses_backward_jump_and_accepts_forward_jump():
    with pytest.raises(ValueError, match="backward goto"):
        IRVerifier.prove_realtime_within(_module([IRLabel("again"), IRGoto("again")]), ["main"], [()])
    assert IRVerifier.prove_realtime_within(_module([IRGoto("done"), IRLabel("done")]), ["main"], [()]) == []


def test_label_emission_is_a_c11_statement_and_keeps_fallthrough_comment():
    text = CEmitter().emit(_module([IRGoto("done"), IRLabel("done", falls_through=True), IRReturn(IRLiteral("0"))]))
    assert "goto done;" in text
    assert "/* fall through */\n    done: ;" in text


@requires_host_c_compiler
def test_emitted_forward_jump_compiles_and_runs_as_strict_c11(tmp_path):
    text = CEmitter().emit(_module([IRGoto("done"), IRLabel("done"), IRReturn(IRLiteral("0"))]))
    source = tmp_path / "jump.c"
    binary = tmp_path / "jump"
    source.write_text(text)
    subprocess.run(
        [
            *configured_c_compiler(),
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
