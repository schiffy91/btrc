"""File-scope value reachability and strict-C regression contracts."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFunctionDef,
    IRFunctionRef,
    IRGlobalDecl,
    IRLiteral,
    IRMacroDef,
    IRModule,
    IRReturn,
    IRVar,
)
from src.compiler.python.ir.optimizer import optimize

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _function(name: str, statements=None) -> IRFunctionDef:
    return IRFunctionDef(
        name=name,
        return_type=CType("int"),
        body=IRBlock(statements or [IRReturn(IRLiteral("0"))]),
        is_static=name != "main",
    )


def test_dead_function_and_internal_global_cycle_is_pruned() -> None:
    module = IRModule(
        function_defs=[
            _function("main"),
            _function("dead", [IRReturn(IRVar("dead_state"))]),
        ],
        global_decls=[
            IRGlobalDecl(CType("int"), "dead_state", IRLiteral("41")),
            IRGlobalDecl(
                CType("int (*)(void)"),
                "dead_callback",
                IRFunctionRef("dead"),
            ),
        ],
    )

    optimize(module)

    assert [function.name for function in module.function_defs] == ["main"]
    assert module.global_decls == []


def test_live_global_dependencies_are_closed_transitively() -> None:
    module = IRModule(
        function_defs=[
            _function("main", [IRReturn(IRVar("live_pointer"))]),
        ],
        global_decls=[
            IRGlobalDecl(CType("int"), "live_value", IRLiteral("42")),
            IRGlobalDecl(
                CType("int*"),
                "live_pointer",
                IRAddressOf(IRVar("live_value")),
            ),
            IRGlobalDecl(CType("int"), "dead_value", IRLiteral("7")),
        ],
    )

    optimize(module)

    assert [declaration.name for declaration in module.global_decls] == [
        "live_value",
        "live_pointer",
    ]


def test_direct_call_through_global_callback_roots_the_slot() -> None:
    module = IRModule(
        function_defs=[
            _function(
                "main",
                [
                    IRExprStmt(IRCall("callback_slot")),
                    IRReturn(IRLiteral("0")),
                ],
            ),
            _function("callback"),
        ],
        global_decls=[
            IRGlobalDecl(
                CType("int (*)(void)"),
                "callback_slot",
                IRFunctionRef("callback"),
            ),
        ],
    )

    optimize(module)

    assert [declaration.name for declaration in module.global_decls] == ["callback_slot"]
    assert {function.name for function in module.function_defs} == {
        "main",
        "callback",
    }


def test_external_effectful_roots_and_internal_volatile_pruning() -> None:
    module = IRModule(
        function_defs=[_function("main"), _function("initialize")],
        global_decls=[
            IRGlobalDecl(
                CType("int"),
                "exported",
                IRLiteral("1"),
                is_static=False,
            ),
            IRGlobalDecl(
                CType("int"),
                "signal_state",
                IRLiteral("0"),
                is_volatile=True,
            ),
            IRGlobalDecl(
                CType("int"),
                "initialized",
                IRCall("initialize"),
            ),
        ],
    )

    optimize(module)

    assert {declaration.name for declaration in module.global_decls} == {
        "exported",
        "initialized",
    }
    assert {function.name for function in module.function_defs} == {
        "main",
        "initialize",
    }


def test_macro_replacements_root_whole_global_identifiers() -> None:
    module = IRModule(
        function_defs=[_function("main")],
        global_decls=[
            IRGlobalDecl(CType("int"), "state", IRLiteral("1")),
            IRGlobalDecl(CType("int"), "state_extra", IRLiteral("2")),
        ],
        preprocessor_decls=[
            IRMacroDef(name="READ_STATE", replacement="(state + 1)"),
        ],
    )

    optimize(module)

    assert [declaration.name for declaration in module.global_decls] == ["state"]


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_pruned_internal_global_is_strict_c11(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    module = IRModule(
        function_defs=[
            _function("main"),
            _function("dead", [IRReturn(IRVar("dead_state"))]),
        ],
        global_decls=[
            IRGlobalDecl(CType("int"), "dead_state", IRLiteral("41")),
        ],
    )
    optimize(module)
    source = tmp_path / "global_dce.c"
    source.write_text(CEmitter().emit(module))

    result = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-c",
            str(source),
            "-o",
            str(tmp_path / "global_dce.o"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
