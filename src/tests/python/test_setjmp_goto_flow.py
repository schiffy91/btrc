"""Alias and volatility facts on forward edges and repeated goto paths."""

import subprocess

import pytest

from src.compiler.python.ir.lowering.exceptions import ExceptionLowerer, JumpContinuation, PointerFlow
from src.compiler.python.ir.lowering.types import CodegenError
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBlock,
    IRCall,
    IRDeref,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDef,
    IRGoto,
    IRIf,
    IRLabel,
    IRLiteral,
    IRModule,
    IRVar,
    IRVarDecl,
)
from src.tests.c_toolchains import configured_c_compiler, requires_host_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT
from src.tests.python.test_jump_lowering import _emit


def _module(statements):
    return IRModule(function_defs=[IRFunctionDef("probe", CType("void"), body=IRBlock(statements))])


def _writes(statements, write):
    effects = ExceptionLowerer.build_setjmp_call_effects(_module(statements))["probe"]
    return {origin.storage.name for origin in effects.flow.writes[id(write)] if origin.depth == 0}


def _preamble():
    return [IRVarDecl(CType("int"), name, IRLiteral("0")) for name in ("first", "second")] + [
        IRVarDecl(CType("int*"), "pointer", IRAddressOf(IRVar("first"))),
    ]


def _write():
    return IRAssign(IRDeref(IRVar("pointer")), IRLiteral("1"))


def test_forward_edge_survives_intervening_reassignment():
    write = _write()
    statements = [
        *_preamble(),
        IRIf(
            IRLiteral("flag"),
            IRBlock(
                [
                    IRAssign(IRVar("pointer"), IRAddressOf(IRVar("second"))),
                    IRGoto("joined"),
                ]
            ),
        ),
        IRAssign(IRVar("pointer"), IRAddressOf(IRVar("first"))),
        IRLabel("joined"),
        write,
    ]
    assert _writes(statements, write) == {"first", "second"}


def test_jump_retains_outer_alias_while_an_inner_name_shadows_it():
    write = _write()
    statements = [
        *_preamble(),
        IRBlock(
            [
                IRVarDecl(CType("int*"), "pointer", IRAddressOf(IRVar("second"))),
                IRGoto("inside"),
                IRLabel("inside"),
            ]
        ),
        write,
    ]
    assert _writes(statements, write) == {"first"}


@pytest.mark.parametrize("nested", [False, True])
def test_backward_edge_revisits_earlier_pointer_use(nested):
    write = _write()
    jump = IRGoto("again")
    statements = [
        *_preamble(),
        IRLabel("again"),
        write,
        IRAssign(IRVar("pointer"), IRAddressOf(IRVar("second"))),
        IRIf(IRLiteral("flag"), IRBlock([IRBlock([jump]) if nested else jump])),
    ]
    assert _writes(statements, write) == {"first", "second"}


def test_two_labels_propagate_an_initial_forward_edge_into_a_backward_edge():
    write = _write()
    statements = [
        *_preamble(),
        IRGoto("later"),
        IRLabel("earlier"),
        write,
        IRGoto("done"),
        IRLabel("later"),
        IRAssign(IRVar("pointer"), IRAddressOf(IRVar("second"))),
        IRGoto("earlier"),
        IRLabel("done"),
    ]
    assert _writes(statements, write) == {"second"}


def test_backward_widening_covers_a_chain_longer_than_the_iteration_budget(monkeypatch):
    values = [IRVarDecl(CType("int"), f"value{index}") for index in range(22)]
    pointers = [IRVarDecl(CType("int*"), f"p{index}", IRAddressOf(IRVar(f"value{index}"))) for index in range(22)]
    write = IRAssign(IRDeref(IRVar("p0")), IRLiteral("1"))
    updates = [IRAssign(IRVar(f"p{index}"), IRVar(f"p{index + 1}")) for index in range(21)]
    widened = []
    original = PointerFlow._widen

    def record(state):
        widened.append(True)
        return original(state)

    monkeypatch.setattr(PointerFlow, "_widen", staticmethod(record))
    writes = _writes([*values, *pointers, IRLabel("again"), write, *updates, IRGoto("again")], write)
    assert writes == {f"value{index}" for index in range(22)}
    assert widened


def test_continuation_reaches_an_earlier_label_transitively():
    statements = [
        IRLabel("first"),
        IRExprStmt(IRLiteral("1")),
        IRLabel("second"),
        IRIf(IRLiteral("flag"), IRBlock([IRGoto("first")])),
        IRExprStmt(IRCall("setjmp")),
        IRGoto("second"),
    ]
    assert JumpContinuation(statements).start(4) == 0
    assert JumpContinuation(statements).backward(0)
    assert JumpContinuation(statements).backward(2)


def test_unrelated_backward_edge_does_not_extend_the_continuation():
    statements = [IRLabel("earlier"), IRGoto("earlier"), IRExprStmt(IRCall("setjmp"))]
    assert JumpContinuation(statements).start(2) == 3


@pytest.mark.parametrize("nested", [False, True])
def test_jump_continuation_marks_an_aggregate_written_before_setjmp(nested):
    aggregate = IRVarDecl(CType("struct Probe"), "aggregate")
    write = IRAssign(IRFieldAccess(IRVar("aggregate"), "value", arrow=False), IRLiteral("1"))
    jump = IRGoto("again")
    statements = [
        aggregate,
        IRLabel("again"),
        write,
        IRIf(IRCall("setjmp"), IRBlock()),
        IRBlock([jump]) if nested else jump,
    ]
    ExceptionLowerer.apply_setjmp_volatility(_module(statements))
    assert aggregate.is_volatile


def test_new_backward_mutation_reaches_existing_layered_qualifier_refusal():
    aggregate = IRVarDecl(CType("struct Probe"), "aggregate")
    address = IRAddressOf(IRVar("aggregate"), source_expression=True)
    statements = [
        aggregate,
        IRExprStmt(address),
        IRLabel("again"),
        IRAssign(IRFieldAccess(IRVar("aggregate"), "value", arrow=False), IRLiteral("1")),
        IRIf(IRCall("setjmp"), IRBlock()),
        IRGoto("again"),
    ]
    with pytest.raises(CodegenError, match=r"aggregate.*modified across try/throw.*layered pointer qualifiers"):
        ExceptionLowerer.apply_setjmp_volatility(_module(statements))


@requires_host_c_compiler
def test_source_backward_jump_qualifies_and_preserves_an_aggregate(tmp_path):
    emitted = _emit("""
        struct State { int value; };
        int main() {
            struct State state = {0};
            int step = 0;
            label("again");
            state.value++;
            try { if (step == 2) { throw "last"; } } catch (string error) {}
            step++;
            if (step < 3) { jump("again"); }
            return state.value - 3;
        }
    """)
    assert "volatile State state" in emitted
    source = tmp_path / "goto-setjmp.c"
    source.write_text(emitted)
    executable = tmp_path / "goto-setjmp"
    subprocess.run(
        [
            *configured_c_compiler(),
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
