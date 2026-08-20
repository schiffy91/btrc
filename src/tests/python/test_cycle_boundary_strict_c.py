"""Strict-C proof for helpers introduced by the optimizer boundary pass."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFunctionDef,
    IRHelperDecl,
    IRIf,
    IRInclude,
    IRLiteral,
    IRModule,
    IRReturn,
)
from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _edge_only_module() -> IRModule:
    helper = "__btrc_arc_release_edge"
    declarations = [
        IRHelperDecl.from_runtime(definition) for definition in RuntimeHelperCatalog().definitions_for({helper})
    ]
    headers = sorted({header for declaration in declarations for header in declaration.required_headers})
    return IRModule(
        preprocessor_decls=[IRInclude(header) for header in headers],
        helper_decls=declarations,
        function_defs=[
            IRFunctionDef(
                name="main",
                return_type=CType(text="int"),
                body=IRBlock(
                    stmts=[
                        IRIf(
                            condition=IRLiteral(text="0"),
                            then_block=IRBlock(
                                stmts=[
                                    IRExprStmt(
                                        expr=IRCall(
                                            callee=helper,
                                            helper_ref=helper,
                                            args=[
                                                IRLiteral(text="NULL"),
                                                IRLiteral(text="NULL"),
                                                IRLiteral(text="NULL"),
                                            ],
                                        )
                                    )
                                ]
                            ),
                        ),
                        IRReturn(value=IRLiteral(text="0")),
                    ]
                ),
            )
        ],
    )


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_optimizer_added_flush_helper_is_dependency_safe_strict_c(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    pipeline = CompilationPipeline()
    module = pipeline.optimize(_edge_only_module(), CompilerOptions())
    generated = tmp_path / "cycle-boundary.c"
    generated.write_text(pipeline.emit(module))
    executable = tmp_path / f"cycle-boundary-{Path(c_compiler).name}"

    build = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(generated),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr
