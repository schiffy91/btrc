"""Strict-C warning contracts for structured IR and archive emission."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import src.compiler.python.artifacts.stdlib as archive
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRExprStmt,
    IRFunctionDecl,
    IRFunctionDef,
    IRModule,
    IRParam,
    IRVar,
)
from src.compiler.python.ir.optimizer import IROptimizer

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def test_parameter_discards_run_after_function_dce_and_are_idempotent():
    main = IRFunctionDef(
        name="main",
        return_type=CType("void"),
        params=[
            IRParam(CType("int"), "used"),
            IRParam(CType("int"), "dead"),
        ],
        body=IRBlock(stmts=[IRExprStmt(expr=IRVar(name="used"))]),
    )
    module = IRModule(
        function_defs=[
            main,
            IRFunctionDef(
                name="dead",
                return_type=CType("void"),
                body=IRBlock(),
            ),
        ]
    )

    IROptimizer(module).optimize()
    IROptimizer(module).optimize()

    assert [function.name for function in module.function_defs] == ["main"]
    discards = [
        statement.expr.name
        for statement in main.body.stmts
        if (isinstance(statement, IRExprStmt) and isinstance(statement.expr, IRVar))
    ]
    assert discards == ["dead", "used"]
    assert [parameter.name for parameter in main.params] == ["used", "dead"]
    assert CEmitter().emit(module).count("(void)(dead);") == 1


def test_archive_exports_structured_callbacks_with_their_signatures():
    callback = IRFunctionDef(
        name="Node_visit",
        return_type=CType("void"),
        body=IRBlock(),
        is_static=True,
        archive_export=True,
    )
    module = IRModule(
        function_decls=[
            IRFunctionDecl(
                name="Node_visit",
                return_type=CType("void"),
                is_static=True,
            )
        ],
        function_defs=[callback],
    )

    CompilationPipeline().stdlib_archive.transform_module(module)

    assert not callback.is_static
    assert not module.function_decls[0].is_static
    assert CEmitter().emit(module).count("void Node_visit(void);") == 1


@pytest.mark.skipif(not COMPILERS or sys.platform == "win32", reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_stdlib_archive_is_warning_clean_under_strict_c11(tmp_path: Path, c_compiler: str):
    output = tmp_path / "stdlib"
    compiler = Compiler(CompilationPipeline(archive_repository=archive.StdlibArtifactRepository()))
    assert compiler.build_stdlib_archive(str(output)).successful

    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-c",
            str(output / archive.IMPL_NAME),
            "-o",
            str(output / "btrc_stdlib.o"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
